from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ENTRYPOINT_PATH = REPO_ROOT / "coding-agent" / "entrypoint.sh"


def _extract_skill_projection_script() -> str:
    """Extract the Dynamic Skill Projection Engine block from coding-agent/entrypoint.sh."""
    content = ENTRYPOINT_PATH.read_text(encoding="utf-8")
    start_marker = "# ─── Dynamic Skill Projection Engine ───────────────────────────────────────"
    end_marker = "if [ -x .pa-container/dependencies/agent/commands.sh ]; then"
    assert start_marker in content, f"start_marker not found in {ENTRYPOINT_PATH}"
    assert end_marker in content, f"end_marker not found in {ENTRYPOINT_PATH}"
    start_idx = content.index(start_marker)
    end_idx = content.index(end_marker)
    return content[start_idx:end_idx]


def _run_projection(
    home_agent_dir: Path,
    share_pkgs_dir: Path,
    share_agents_dir: Path | None = None,
    agent_skills_dirs: list[Path] | None = None,
    nounset: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Execute the skill projection script with isolated environment variables."""
    script = _extract_skill_projection_script()
    env = {
        **os.environ,
        "PA_HOME_AGENT_DIR": str(home_agent_dir),
        "PA_SHARE_PACKAGES_DIR": str(share_pkgs_dir),
    }
    if share_agents_dir is not None:
        env["PA_SHARE_AGENTS_DIR"] = str(share_agents_dir)
    if agent_skills_dirs is not None:
        env["PA_AGENT_SKILLS_DIRS"] = ":".join(str(p) for p in agent_skills_dirs)
    bash_flags = ["-e", "-u"] if nounset else ["-e"]
    return subprocess.run(
        ["bash", *bash_flags, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )


def test_skill_projection_via_filesystem_discovery(tmp_path: Path):
    """Verify that installed packages project skills discovered via /usr/local/share/pa-container/agents/*/skills_path."""
    home_agent = tmp_path / "home" / "agent"
    share_pkgs = tmp_path / "share" / "packages"
    share_agents = tmp_path / "share" / "agents"

    # Register agent skill paths dynamically
    agent_paths = {
        "pi": ".pi/agent/skills",
        "antigravity": ".gemini/antigravity/skills",
        "claude": ".claude/skills",
        "opencode": ".config/opencode/skills",
    }
    for agent_name, rel_path in agent_paths.items():
        ad = share_agents / agent_name
        ad.mkdir(parents=True)
        (ad / "skills_path").write_text(rel_path, encoding="utf-8")

    # Create two installed packages with skills
    git_skill = share_pkgs / "git" / "skill"
    git_skill.mkdir(parents=True)
    (git_skill / "SKILL.md").write_text("# Git Skill\n", encoding="utf-8")

    python_skill = share_pkgs / "python" / "skill"
    python_skill.mkdir(parents=True)
    (python_skill / "SKILL.md").write_text("# Python Skill\n", encoding="utf-8")

    _run_projection(home_agent, share_pkgs, share_agents_dir=share_agents)

    # Check that skills are projected across all registered agent targets
    for rel_path in agent_paths.values():
        agent_skills = home_agent / rel_path
        git_dest = agent_skills / "git"
        assert git_dest.is_dir()
        assert (git_dest / "SKILL.md").read_text(encoding="utf-8") == "# Git Skill\n"
        assert (git_dest / ".pa-projected").is_file()

        py_dest = agent_skills / "python"
        assert py_dest.is_dir()
        assert (py_dest / "SKILL.md").read_text(encoding="utf-8") == "# Python Skill\n"
        assert (py_dest / ".pa-projected").is_file()


def test_skill_projection_via_env_override(tmp_path: Path):
    """Verify that PA_AGENT_SKILLS_DIRS restricts skill projection strictly to active agent paths."""
    home_agent = tmp_path / "home" / "agent"
    share_pkgs = tmp_path / "share" / "packages"

    git_skill = share_pkgs / "git" / "skill"
    git_skill.mkdir(parents=True)
    (git_skill / "SKILL.md").write_text("# Git Skill\n", encoding="utf-8")

    pi_skills = home_agent / ".pi" / "agent" / "skills"
    claude_skills = home_agent / ".claude" / "skills"

    # Only pass pi_skills in PA_AGENT_SKILLS_DIRS
    _run_projection(home_agent, share_pkgs, agent_skills_dirs=[pi_skills])

    assert (pi_skills / "git" / "SKILL.md").is_file()
    assert (pi_skills / "git" / ".pa-projected").is_file()
    # claude_skills was not active, should not be created
    assert not claude_skills.exists()


def test_skill_pruning_stale_managed_skills(tmp_path: Path):
    """Verify that stale projected skills marked with .pa-projected are pruned."""
    home_agent = tmp_path / "home" / "agent"
    share_pkgs = tmp_path / "share" / "packages"

    # Previously projected skill for 'podman'
    pi_skills = home_agent / ".pi" / "agent" / "skills"
    stale_podman = pi_skills / "podman"
    stale_podman.mkdir(parents=True)
    (stale_podman / "SKILL.md").write_text("# Podman Skill\n", encoding="utf-8")
    (stale_podman / ".pa-projected").touch()

    # Current container image only has 'git'
    git_skill = share_pkgs / "git" / "skill"
    git_skill.mkdir(parents=True)
    (git_skill / "SKILL.md").write_text("# Git Skill\n", encoding="utf-8")

    _run_projection(home_agent, share_pkgs, agent_skills_dirs=[pi_skills])

    # Stale podman skill must be deleted
    assert not stale_podman.exists()

    # Git skill must be active
    assert (pi_skills / "git" / "SKILL.md").is_file()
    assert (pi_skills / "git" / ".pa-projected").is_file()


def test_skill_pruning_legacy_unmarked_acp_skills(tmp_path: Path):
    """Verify that legacy ACP skills lacking .pa-projected are also pruned when uninstalled."""
    home_agent = tmp_path / "home" / "agent"
    share_pkgs = tmp_path / "share" / "packages"

    pi_skills = home_agent / ".pi" / "agent" / "skills"

    # Pre-populate legacy un-marked skills
    for legacy_pkg in ["code-intelligence", "data-tools", "podman"]:
        d = pi_skills / legacy_pkg
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"# {legacy_pkg}\n", encoding="utf-8")
        # Notice: no .pa-projected file created

    # Current container image only has 'git'
    git_skill = share_pkgs / "git" / "skill"
    git_skill.mkdir(parents=True)
    (git_skill / "SKILL.md").write_text("# Git Skill\n", encoding="utf-8")

    _run_projection(home_agent, share_pkgs, agent_skills_dirs=[pi_skills])

    for legacy_pkg in ["code-intelligence", "data-tools", "podman"]:
        assert not (pi_skills / legacy_pkg).exists(), f"Legacy skill {legacy_pkg} should have been pruned"

    assert (pi_skills / "git" / "SKILL.md").is_file()


def test_skill_preserves_custom_user_skills(tmp_path: Path):
    """Verify that user-authored custom skills without .pa-projected are not deleted."""
    home_agent = tmp_path / "home" / "agent"
    share_pkgs = tmp_path / "share" / "packages"

    pi_skills = home_agent / ".pi" / "agent" / "skills"

    # User-created custom skill
    custom_skill = pi_skills / "my-custom-assistant-skill"
    custom_skill.mkdir(parents=True)
    (custom_skill / "SKILL.md").write_text("# My Custom Skill\n", encoding="utf-8")
    (custom_skill / "helper.py").write_text("print('custom')\n", encoding="utf-8")

    # Current container image has 'git'
    git_skill = share_pkgs / "git" / "skill"
    git_skill.mkdir(parents=True)
    (git_skill / "SKILL.md").write_text("# Git Skill\n", encoding="utf-8")

    _run_projection(home_agent, share_pkgs, agent_skills_dirs=[pi_skills])

    # Custom skill must remain intact
    assert custom_skill.is_dir()
    assert (custom_skill / "SKILL.md").read_text(encoding="utf-8") == "# My Custom Skill\n"
    assert (custom_skill / "helper.py").read_text(encoding="utf-8") == "print('custom')\n"
    assert not (custom_skill / ".pa-projected").exists()

    # Git skill must also be projected
    assert (pi_skills / "git" / "SKILL.md").is_file()


def test_skill_projection_works_with_nounset_enabled(tmp_path: Path):
    """Verify that skill projection runs cleanly even under set -u (nounset) when PA_AGENT_SKILLS_DIRS is unset."""
    home_agent = tmp_path / "home" / "agent"
    share_pkgs = tmp_path / "share" / "packages"
    share_agents = tmp_path / "share" / "agents"

    pi_skills = home_agent / ".pi" / "agent" / "skills"
    pi_skills.mkdir(parents=True)

    git_skill = share_pkgs / "git" / "skill"
    git_skill.mkdir(parents=True)
    (git_skill / "SKILL.md").write_text("# Git Skill\n", encoding="utf-8")

    # Run with nounset=True and without setting PA_AGENT_SKILLS_DIRS
    res = _run_projection(home_agent, share_pkgs, share_agents_dir=share_agents, nounset=True)
    assert res.returncode == 0
