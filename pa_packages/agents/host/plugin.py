from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

sys.dont_write_bytecode = True

from logging_driver import LogCategory, get_category_logger
from network import read_agent_extras
from packages.plugin import (
    ACPAgentPlugin,
    ContainerRunSpec,
    RunContext,
    SecretTokenMapping,
)

from .registry import (
    get_agent_driver,
    resolve_selected_agent_names,
)
from .synthesis import load_project_models

if TYPE_CHECKING:
    from pathlib import Path

    from config_types import PackageSecretDeclaration, ProjectConfig
    from packages.manifest import PackageManifest

    from .base import AgentDriver

logger = get_category_logger(__name__, LogCategory.AGENT)


class AgentsPlugin(ACPAgentPlugin):
    """ACP Plugin for unified coding agents capability."""

    def __init__(
        self,
        manifest: PackageManifest,
        package_dir: Path,
        project_dir: Path | None = None,
    ) -> None:
        super().__init__(manifest, package_dir, project_dir)
        self.active_driver: AgentDriver | None = None
        self.selected_drivers: list[AgentDriver] = []

    def get_agent_driver(self, name: str | None = None) -> AgentDriver:
        """Instantiate and return an AgentDriver instance."""
        target_name = name or (self.active_driver.name if self.active_driver else "pi")
        return get_agent_driver(target_name, repo_root=self.package_dir.parent.parent, project_dir=self.project_dir)

    def contribute_config_schema(self) -> dict[str, Any]:
        """Contribute validation schema dictionary for the 'agent' section in config.yaml."""
        return {
            "type": dict,
            "required": False,
            "keys": {
                "default": {"type": str, "required": False},
                "read_only_pa_container": {"type": bool, "required": False},
                "env": {"type": dict, "required": False},
                "mounts": {"type": list, "required": False},
                "capabilities": {"type": list, "required": False},
                "devices": {"type": list, "required": False},
                "ports": {"type": dict, "required": False},
            },
        }

    def _resolve_enabled_agents(self, config: ProjectConfig | None) -> list[str]:
        if not config:
            return ["pi"]
        pkgs = config.get("packages")
        if not isinstance(pkgs, list):
            return ["pi"]

        agents: list[str] = []
        for entry in pkgs:
            if isinstance(entry, str) and entry.strip().lower() == "agents":
                if "pi" not in agents:
                    agents.append("pi")
            elif isinstance(entry, dict) and "agents" in entry:
                v = entry["agents"]
                if isinstance(v, list):
                    for f in v:
                        if isinstance(f, str) and f.strip():
                            s = f.strip().lower()
                            if s not in agents:
                                agents.append(s)
                        elif isinstance(f, dict) and len(f) == 1:
                            s = str(next(iter(f.keys()))).strip().lower()
                            if s and s not in agents:
                                agents.append(s)
                elif isinstance(v, dict) and isinstance(v.get("features"), list):
                    for f in v["features"]:
                        if isinstance(f, str) and f.strip():
                            s = f.strip().lower()
                            if s not in agents:
                                agents.append(s)
                        elif isinstance(f, dict) and len(f) == 1:
                            s = str(next(iter(f.keys()))).strip().lower()
                            if s and s not in agents:
                                agents.append(s)

        return agents if agents else ["pi"]

    def get_secret_mappings(self, config: ProjectConfig) -> list[SecretTokenMapping]:
        """Contribute secret mappings linking explicitly declared OS keyring credentials to proxy token replacer rules."""
        mappings: list[SecretTokenMapping] = []
        pkgs_list = config.get("packages") or []
        agents_secrets: list[PackageSecretDeclaration] = []
        if isinstance(pkgs_list, list):
            for item in pkgs_list:
                if isinstance(item, dict) and "agents" in item:
                    val = item["agents"]
                    if isinstance(val, dict):
                        agents_secrets = list(val.get("secrets") or [])
                        feats = val.get("features") or []
                        if isinstance(feats, list):
                            for f in feats:
                                if isinstance(f, dict) and len(f) == 1:
                                    f_val = next(iter(f.values()))
                                    if isinstance(f_val, dict):
                                        agents_secrets.extend(f_val.get("secrets") or [])
                    break

        secret_defs: dict[str, tuple[str, str, tuple[str, ...], str, str]] = {
            "anthropic": (
                "Anthropic API Key",
                "ANTHROPIC_API_KEY_PLACEHOLDER",
                ("api.anthropic.com",),
                "x-api-key",
                "ANTHROPIC_API_KEY_PLACEHOLDER",
            ),
            "gemini": (
                "Google Gemini API Key",
                "GEMINI_API_KEY_PLACEHOLDER",
                ("generativelanguage.googleapis.com",),
                "x-goog-api-key",
                "GEMINI_API_KEY_PLACEHOLDER",
            ),
        }

        for s in agents_secrets:
            if not isinstance(s, dict):
                continue
            name = str(s.get("name", "")).strip().lower()
            account = str(s.get("account", "")).strip()
            if not name or not account or name not in secret_defs:
                continue
            desc, placeholder, hosts, header, pattern = secret_defs[name]
            mappings.append(
                SecretTokenMapping(
                    name=desc,
                    keyring_account=account,
                    placeholder=placeholder,
                    hosts=hosts,
                    keyring_service="pa-container",
                    header=header,
                    pattern=pattern,
                    required=True,
                )
            )

        return mappings

    def on_run_init(self, context: RunContext) -> None:
        """Resolve active and selected agents, configure drivers, and synthesize configs."""
        enabled_agents = self._resolve_enabled_agents(context.config)
        agent_sec = context.config.get("agent") if context.config else None
        default_agent = (
            str(agent_sec.get("default")).strip().lower()
            if isinstance(agent_sec, dict) and agent_sec.get("default")
            else enabled_agents[0]
        )

        repo_root = self.package_dir.parent.parent
        cli_agent = context.options.agent if hasattr(context.options, "agent") else None
        multi_agent = context.has_mode("multi-agent")

        active_agent_name, selected_agent_names = resolve_selected_agent_names(
            cli_agent=cli_agent,
            enabled_agents=enabled_agents,
            default_agent=default_agent,
            multi_agent=multi_agent,
            repo_root=repo_root,
        )

        self.active_driver = get_agent_driver(active_agent_name, repo_root=repo_root, project_dir=self.project_dir)
        self.selected_drivers = [
            get_agent_driver(name, repo_root=repo_root, project_dir=self.project_dir) for name in selected_agent_names
        ]

        context.set_attribute("agents.active_name", active_agent_name)
        context.set_attribute("agents.selected_names", selected_agent_names)
        context.set_attribute("agents.active_driver", self.active_driver)
        context.set_attribute("agents.selected_drivers", self.selected_drivers)
        context.set_attribute("agents.plugin", self)

        # Synthesize configurations for all active agents
        if self.project_dir:
            pa_dir = self.project_dir / ".pa-container"
            if pa_dir.is_dir():
                try:
                    (
                        models_data,
                        server_configs,
                        llama_hostnames,
                        gateway_configs,
                        default_model,
                        _,
                    ) = load_project_models(pa_dir)

                    context.set_attribute("agents.models_data", models_data)
                    context.set_attribute("agents.server_configs", server_configs)
                    context.set_attribute("agents.llama_hostnames", llama_hostnames)
                    context.set_attribute("agents.gateway_configs", gateway_configs)
                    context.set_attribute("agents.default_model", default_model)

                    for drv in self.selected_drivers:
                        agent_gw_configs = [gw for gw in gateway_configs if drv.is_gateway_enabled_for_agent(gw)]
                        drv.synthesize_config(
                            server_configs=server_configs,
                            gateway_configs=agent_gw_configs,
                            default_model=default_model,
                            project_dir=self.project_dir,
                        )
                except Exception as e:
                    logger.debug(f"Could not synthesize agent model configurations: {e}")

    def on_container_configure(
        self,
        spec: ContainerRunSpec,
        context: RunContext,
    ) -> None:
        """Inject container runtime arguments (mounts, env vars, shadow paths) for active agents."""
        active_driver: AgentDriver | None = context.get_attribute("agents.active_driver") or self.active_driver
        selected_drivers: list[AgentDriver] = context.get_attribute("agents.selected_drivers") or self.selected_drivers
        selected_names: list[str] = context.get_attribute("agents.selected_names") or (
            [d.name for d in selected_drivers] if selected_drivers else []
        )

        if not active_driver and selected_drivers:
            active_driver = selected_drivers[0]

        if not active_driver:
            return

        # Inject mounts
        seen_dests = {m.destination for m in spec.mounts}
        for d in selected_drivers:
            if self.project_dir:
                for m in d.get_mounts(self.project_dir):
                    if m.destination not in seen_dests:
                        seen_dests.add(m.destination)
                        spec.mounts.append(m)

        # Inject environment variables
        try:
            agent_extras = read_agent_extras((self.project_dir / ".pa-container") if self.project_dir else None)
        except Exception:
            agent_extras = {"env": {}, "mounts": [], "capabilities": [], "devices": []}
        gateway_configs = context.get_attribute("agents.gateway_configs") or []
        for d in selected_drivers:
            d_gateways = [gw for gw in gateway_configs if d.is_gateway_enabled_for_agent(gw)]
            spec.env.update(d.get_environment(agent_extras, gateway_configs=d_gateways))

        # Inject shadow paths
        for d in selected_drivers:
            for p in d.get_shadow_paths():
                if p not in spec.chown_paths:
                    spec.chown_paths.append(p)

        # Environment agent markers
        spec.env["PA_CONTAINER_AGENT"] = active_driver.name
        spec.env["PA_CONTAINER_ENABLED_AGENTS"] = ",".join(selected_names)

        active_skills_paths = [f"/home/agent/{d.get_skills_path()}" for d in selected_drivers if d.get_skills_path()]
        if active_skills_paths:
            spec.env["PA_AGENT_SKILLS_DIRS"] = ":".join(active_skills_paths)

        active_skills_paths = [f"/home/agent/{d.get_skills_path()}" for d in selected_drivers if d.get_skills_path()]
        if active_skills_paths:
            spec.env["PA_AGENT_SKILLS_DIRS"] = ":".join(active_skills_paths)
