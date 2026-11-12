from __future__ import annotations

import atexit
import contextlib
import logging
import os
import re
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

sys.dont_write_bytecode = True

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.syntax import Syntax
from rich.text import Text

# ─── Log Categories ──────────────────────────────────────────────────────────


class LogCategory(StrEnum):
    """Semantic category tags for explicit message routing and filtering."""

    PREFLIGHT = "preflight"
    MODEL = "model"
    SERVER = "server"
    PROXY = "proxy"
    NETWORK = "network"
    BUILD = "build"
    VOLUME = "volume"
    SECURITY = "security"
    AGENT = "agent"
    DESKTOP = "desktop"
    FLOW_EXPORT = "flow_export"
    CLEANUP = "cleanup"


# ─── Tagged Logger Adapter ───────────────────────────────────────────────────


class CategoryLogger(logging.LoggerAdapter[logging.Logger]):
    """Logger adapter that injects an explicit LogCategory tag into every record."""

    def __init__(self, logger: logging.Logger, category: LogCategory | str) -> None:
        cat_str = str(category.value if isinstance(category, LogCategory) else category)
        super().__init__(logger, {"category": cat_str})
        self.category: str = cat_str

    def process(self, msg: Any, kwargs: Any) -> tuple[Any, Any]:
        extra = kwargs.setdefault("extra", {})
        if "category" not in extra:
            extra["category"] = self.category
        return msg, kwargs


def get_category_logger(name: str, category: LogCategory | str) -> CategoryLogger:
    """Return a CategoryLogger instance bound to the specified semantic category."""
    base_logger = logging.getLogger(name)
    return CategoryLogger(base_logger, category)


# ─── Custom Formatter ────────────────────────────────────────────────────────


class TaggedFileFormatter(logging.Formatter):
    """File log formatter rendering timestamp, level, category tag, and origin."""

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "category"):
            record.category = "system"
        return super().format(record)


# ─── Regular Expressions ───────────────────────────────────────────────────

_ANSI_ESCAPE: re.Pattern[str] = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


# ─── Stage Status & Lifecycle ────────────────────────────────────────────────


class StageStatus(StrEnum):
    """Execution status for a pipeline stage."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Stage:
    """Tracks state and rendering text for a single pipeline stage."""

    def __init__(self, category: LogCategory | str, label: str) -> None:
        self.category: str = str(category.value if isinstance(category, LogCategory) else category)
        self.label: str = label
        self.detail: str = ""
        self.status: StageStatus = StageStatus.RUNNING
        self.spinner: Spinner = Spinner("dots")

    @property
    def completed(self) -> bool:
        return self.status == StageStatus.COMPLETED

    @property
    def failed(self) -> bool:
        return self.status == StageStatus.FAILED

    def update(self, detail: str) -> None:
        """Update detail text for this stage."""
        self.detail = detail

    def complete(self, detail: str | None = None) -> None:
        """Mark stage as completed with optional final detail."""
        self.status = StageStatus.COMPLETED
        self.detail = detail or ""

    def fail(self, message: str) -> None:
        """Mark stage as failed with an error message."""
        self.status = StageStatus.FAILED
        self.detail = message

    def render(self, now: float | None = None) -> Text:
        """Render a single compact line for this stage."""
        current_time = time.monotonic() if now is None else now
        text = Text()
        cat_tag = f"[{self.category}] "

        if self.status == StageStatus.COMPLETED:
            text.append("  ✔ ", style="bold green")
            text.append(cat_tag, style="dim")
            text.append(self.label, style="bold")
            if self.detail:
                text.append(f" ({self.detail})", style="dim")

        elif self.status == StageStatus.FAILED:
            text.append("  ✗ ", style="bold red")
            text.append(cat_tag, style="dim")
            text.append(self.label, style="bold red")
            if self.detail:
                text.append(f" ({self.detail})", style="red")

        else:
            text.append("  ")
            spin_render = self.spinner.render(current_time)
            if isinstance(spin_render, Text):
                text.append_text(spin_render)
            else:
                text.append(str(spin_render))
            text.append(" ")
            text.append(cat_tag, style="dim cyan")
            text.append(self.label, style="bold cyan")
            if self.detail:
                text.append(f": {self.detail}", style="yellow")

        return text


# ─── Console Log Handler ─────────────────────────────────────────────────────


class _ConsoleLogHandler(logging.Handler):
    """Routes category-tagged log records to the LogDriver console and live widgets."""

    def __init__(self, driver: LogDriver) -> None:
        super().__init__()
        self.driver: LogDriver = driver

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.driver._handle_log_record(record)
        except Exception:
            self.handleError(record)


# ─── Unified Log Driver ──────────────────────────────────────────────────────


def _render_error_panel(
    title: str,
    cat_str: str,
    message: str,
    hints: Sequence[Any] = (),
    target_log: Path | str | None = None,
) -> Panel:
    from remediation import RemediationAction

    renderables: list[Any] = []

    body = Text()
    body.append(message, style="bold")
    renderables.append(body)

    if hints:
        renderables.append(Text())
        renderables.append(Text("Suggested remediation:", style="yellow"))
        for hint in hints:
            if isinstance(hint, RemediationAction):
                renderables.append(Text(f"  {hint.description}", style="dim yellow"))
                if hint.snippet:
                    renderables.append(Text())
                    syntax = Syntax(
                        hint.snippet,
                        hint.snippet_lang,
                        theme="monokai",
                        background_color="default",
                        indent_guides=True,
                        padding=(0, 2),
                    )
                    renderables.append(syntax)
                if hint.companion_commands:
                    renderables.append(Text())
                    renderables.append(Text("  Credential setup command:", style="dim yellow"))
                    for cmd in hint.companion_commands:
                        renderables.append(Text(f"    $ {cmd}", style="bold cyan"))
            else:
                renderables.append(Text(f"  {hint}", style="dim yellow"))

    if target_log:
        renderables.append(Text())
        renderables.append(Text(f"Diagnostic log:\n  {target_log}", style="dim cyan"))

    return Panel(
        Group(*renderables),
        title=f"[bold red]Error: {title} [category: {cat_str}][/bold red]",
        border_style="red",
        expand=False,
    )


class LogDriver:
    """Coordinates file-based diagnostic logging with real-time terminal progress."""

    def __init__(
        self,
        project_dir: Path,
        *,
        log_level: str = "INFO",
        verbose: bool = False,
        quiet: bool = False,
        no_color: bool = False,
        log_file: Path | None = None,
        max_days: int | None = 14,
        max_launches: int | None = 10,
    ) -> None:
        self.project_dir: Path = project_dir.resolve()
        self.verbose: bool = verbose
        self.quiet: bool = quiet
        self.no_color: bool = no_color or bool(os.environ.get("NO_COLOR"))
        self.max_days: int | None = max_days
        self.max_launches: int | None = max_launches

        from project import get_project_logs_dir

        self.logs_dir: Path = get_project_logs_dir(self.project_dir)
        self.session_timestamp: str = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")

        # Session file path
        if log_file is not None:
            self.session_log_path: Path = log_file.resolve()
            self.session_log_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            self.session_log_path = self.logs_dir / f"run-{self.session_timestamp}.log"

        self.build_log_path: Path = self.logs_dir / f"build-{self.session_timestamp}.log"

        # Console setup
        force_terminal = None if "CI" not in os.environ else False
        self.console: Console = Console(
            stderr=True,
            no_color=self.no_color,
            force_terminal=force_terminal,
            highlight=False,
        )

        self._file_handler: logging.FileHandler | None = None
        self._build_file_handler: logging.FileHandler | None = None
        self._console_handler: _ConsoleLogHandler | None = None

        # Live terminal state
        self.stages: list[Stage] = []
        self.active_stage: Stage | None = None
        self._lock: threading.RLock = threading.RLock()
        self._live: Live | None = None
        self._interactive_paused: bool = False

        self._setup_file_logging(log_level)
        self._update_symlinks()
        self.prune_expired_logs()

        atexit.register(self.shutdown)

    def _setup_file_logging(self, log_level_str: str) -> None:
        """Attach file and console handlers to root logger with structured category tags."""
        level = getattr(logging, log_level_str.upper(), logging.INFO)
        root = logging.getLogger()
        root.setLevel(logging.DEBUG)

        # Clear existing handlers to avoid duplicates, preserving test capture handlers (e.g. pytest caplog)
        preserved = [h for h in root.handlers if "LogCapture" in type(h).__name__]
        root.handlers.clear()
        for h in preserved:
            root.addHandler(h)

        # Session log handler
        fmt = TaggedFileFormatter(
            fmt="[%(asctime)s.%(msecs)03d] [%(levelname)-7s] [%(category)-10s] [%(name)s:%(lineno)d] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self._file_handler = logging.FileHandler(self.session_log_path, encoding="utf-8")
        self._file_handler.setLevel(level)
        self._file_handler.setFormatter(fmt)
        root.addHandler(self._file_handler)

        # Build log handler for BUILD category messages
        self._build_file_handler = logging.FileHandler(self.build_log_path, encoding="utf-8")
        self._build_file_handler.setLevel(logging.DEBUG)
        self._build_file_handler.setFormatter(fmt)

        class _BuildFilter(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:
                return getattr(record, "category", "") == LogCategory.BUILD.value

        self._build_file_handler.addFilter(_BuildFilter())
        root.addHandler(self._build_file_handler)

        # CLI console handler to route category events to the terminal
        self._console_handler = _ConsoleLogHandler(self)
        self._console_handler.setLevel(level)
        root.addHandler(self._console_handler)

    def _print(self, *args: Any, **kwargs: Any) -> None:
        """Print to console, routing through active Live context if running."""
        if self._live is not None and not self._interactive_paused:
            self._live.console.print(*args, **kwargs)
        else:
            self.console.print(*args, **kwargs)

    def _handle_log_record(self, record: logging.LogRecord) -> None:
        """Route standard logging records into the LogDriver console and live widgets."""
        if self._interactive_paused:
            return

        cat_str = getattr(record, "category", None)
        msg = record.getMessage()

        # 1. Quiet mode: display errors only
        if self.quiet:
            if record.levelno >= logging.ERROR:
                cat_tag = f"[{cat_str}]" if cat_str else "[system]"
                self._print(f"[bold red]✗ {cat_tag} {msg}[/bold red]")
            return

        # 2. Verbose mode: stream every record with formatted category tag
        if self.verbose:
            tag = f"[{cat_str}]" if cat_str else f"[{record.name}]"
            if record.levelno >= logging.ERROR:
                self.console.print(f"[bold red]✗ {tag}[/bold red] [red]{msg}[/red]")
            elif record.levelno >= logging.WARNING:
                self.console.print(f"[bold yellow]⚠ {tag}[/bold yellow] [yellow]{msg}[/yellow]")
            elif record.levelno == logging.INFO:
                self.console.print(f"  [dim cyan]{tag}[/dim cyan] {msg}")
            elif record.levelno <= logging.DEBUG:
                self.console.print(f"    [dim]{tag} {msg}[/dim]")
            return

        if getattr(record, "subprocess_raw", False):
            return

        # 3. Standard live terminal mode
        if record.levelno >= logging.ERROR:
            if self.active_stage is not None and (cat_str is None or self.active_stage.category == cat_str):
                self.fail_stage(msg)
            else:
                tag = f"[{cat_str}]" if cat_str else "[system]"
                self._print(f"[bold red]✗ {tag} {msg}[/bold red]")
            return

        if record.levelno >= logging.WARNING:
            tag = f"[{cat_str}]" if cat_str else f"[{record.name}]"
            self._print(f"[bold yellow]⚠ {tag} {msg}[/bold yellow]")
            return

        if record.levelno == logging.INFO and cat_str:
            if self.active_stage is not None and self.active_stage.category == cat_str:
                self.update_stage(msg)
            elif not self.console.is_terminal:
                self.console.print(f"[{cat_str}] {msg}")

    def _update_symlinks(self) -> None:
        """Atomically update latest.log and latest-build.log symlinks."""
        try:
            latest_run = self.logs_dir / "latest.log"
            if latest_run.is_symlink() or latest_run.exists():
                latest_run.unlink(missing_ok=True)
            latest_run.symlink_to(self.session_log_path.name)

            latest_build = self.logs_dir / "latest-build.log"
            if latest_build.is_symlink() or latest_build.exists():
                latest_build.unlink(missing_ok=True)
            latest_build.symlink_to(self.build_log_path.name)
        except OSError:
            pass

    # ─── Live Stage Progress UI ──────────────────────────────────────────────

    def _render_stages(self) -> Text:
        """Render all registered stages for the Live display."""
        with self._lock:
            now = time.monotonic()
            text = Text()
            max_w = max(20, self.console.width - 1) if self.console.width else 100
            for stage in self.stages:
                line = stage.render(now)
                line.truncate(max_w, overflow="ellipsis")
                text.append_text(line)
                text.append("\n")
            return text

    def _ensure_live(self) -> None:
        """Ensure Live console widget is active on interactive terminals."""
        if self.quiet or self.verbose or not self.console.is_terminal:
            return

        needs_start = False
        with self._lock:
            if self._live is None and not self._interactive_paused:
                self._live = Live(
                    console=self.console,
                    refresh_per_second=10,
                    transient=False,
                    auto_refresh=True,
                    get_renderable=self._render_stages,
                )
                needs_start = True

        if needs_start and self._live is not None:
            self._live.start()
        elif self._live is not None and not self._interactive_paused:
            self._live.refresh()

    def start_stage(self, category: LogCategory | str, label: str) -> Stage:
        """Begin a new execution stage. Auto-completes any previous in-flight stage."""
        cat_str = str(category.value if isinstance(category, LogCategory) else category)
        with self._lock:
            if self.active_stage is not None and self.active_stage.status == StageStatus.RUNNING:
                self.active_stage.complete()

            st = Stage(cat_str, label)
            self.stages.append(st)
            self.active_stage = st

        if self.verbose:
            self.console.print(f"[dim]⠋ [{cat_str}][/dim] {label}...")
        elif not self.console.is_terminal and not self.quiet:
            self.console.print(f"[{cat_str}] {label}...")
        else:
            self._ensure_live()

        return st

    def update_stage(self, detail: str) -> None:
        """Update in-place detail text for the active in-flight stage."""
        with self._lock:
            if self.active_stage is not None and self.active_stage.status == StageStatus.RUNNING:
                self.active_stage.update(detail)
                cat_str = self.active_stage.category
            else:
                return

        if self.verbose:
            self.console.print(f"  [{cat_str}] {detail}")
        elif self._live is not None and not self._interactive_paused:
            self._live.refresh()

    def complete_stage(self, detail: str | None = None) -> None:
        """Mark the active in-flight stage as successfully completed."""
        with self._lock:
            if self.active_stage is not None and self.active_stage.status == StageStatus.RUNNING:
                self.active_stage.complete(detail)
                cat_str = self.active_stage.category
                label = self.active_stage.label
                self.active_stage = None
            else:
                return

        if self.verbose:
            self.console.print(f"[bold green]✔ [{cat_str}][/bold green] done")
        elif not self.console.is_terminal and not self.quiet:
            det_suffix = f" - {detail}" if detail else ""
            self.console.print(f"[{cat_str}] ✔ {label}{det_suffix}")
        elif self._live is not None and not self._interactive_paused:
            self._live.refresh()

    def fail_stage(self, message: str) -> None:
        """Mark the active in-flight stage as failed."""
        with self._lock:
            if self.active_stage is not None and self.active_stage.status == StageStatus.RUNNING:
                self.active_stage.fail(message)
                cat_str = self.active_stage.category
                self.active_stage = None
            else:
                cat_str = "system"

        if self.verbose or not self.console.is_terminal:
            self.console.print(f"[bold red]✗ [{cat_str}][/bold red] {message}")
        elif self._live is not None and not self._interactive_paused:
            self._live.refresh()

    @contextlib.contextmanager
    def stage(self, category: LogCategory | str, label: str) -> Iterator[Stage]:
        """Context manager for stage execution."""
        st = self.start_stage(category, label)
        try:
            yield st
            if st.status == StageStatus.RUNNING:
                self.complete_stage()
        except Exception as err:
            self.fail_stage(str(err))
            raise

    def pause_for_interactive(self) -> None:
        """Clean up live console display immediately prior to interactive container execution."""
        with self._lock:
            self._interactive_paused = True
            if self._live is not None:
                self._live.stop()
                self._live = None

    def resume_after_interactive(self) -> None:
        """Resume live console management after container termination."""
        with self._lock:
            self._interactive_paused = False

    def render_hard_error(
        self,
        category: LogCategory | str,
        title: str,
        message: str,
        hints: Sequence[Any] = (),
        log_path: Path | None = None,
    ) -> None:
        """Render a formatted diagnostics card for fatal errors."""
        cat_str = str(category.value if isinstance(category, LogCategory) else category)

        with self._lock:
            if self.active_stage is not None and self.active_stage.status == StageStatus.RUNNING:
                self.active_stage.fail(message)

            if self._live is not None and not self._interactive_paused:
                self._live.update(self._render_stages())

        self.pause_for_interactive()

        target_log = log_path or self.session_log_path
        panel = _render_error_panel(
            title=title,
            cat_str=cat_str,
            message=message,
            hints=hints,
            target_log=target_log,
        )
        self.console.print(panel)

    def fail_and_render(
        self,
        category: LogCategory | str,
        title: str,
        message: str,
        hints: Sequence[Any] = (),
        log_path: Path | None = None,
        exc: BaseException | None = None,
        source_logger: CategoryLogger | logging.Logger | None = None,
    ) -> None:
        """Log error at ERROR level with category and source tags, and render diagnostics panel."""
        cat_str = str(category.value if isinstance(category, LogCategory) else category)
        logger_to_use = source_logger or get_category_logger("system", category)
        log_msg = f"{title}: {message}" if title and title not in message else message
        logger_to_use.error(log_msg, exc_info=exc or True, extra={"category": cat_str})
        self.render_hard_error(
            category=category,
            title=title,
            message=message,
            hints=hints,
            log_path=log_path,
        )

    # ─── Subprocess Command Execution ────────────────────────────────────────

    def run_command_logged(
        self,
        cmd: list[str],
        *,
        category: LogCategory | str = LogCategory.BUILD,
        label: str | None = None,
        check: bool = True,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Execute a subprocess, streaming lines to disk logs while updating live stage status.

        Args:
            cmd: Command line arguments.
            category: Semantic category tag for logging and stage progression.
            label: Display label for the command in error diagnostics and stage display.
            check: Raise CalledProcessError on non-zero exit code if True.
            cwd: Working directory.
            env: Process environment overrides.

        Returns:
            CompletedProcess instance.
        """
        cat_str = str(category.value if isinstance(category, LogCategory) else category)
        display_label = label or (cmd[0] if cmd else "command")
        logger = get_category_logger("subprocess", category)

        logger.info(f"Executing: {' '.join(cmd)}")

        with self._lock:
            has_matching_active = (
                self.active_stage is not None
                and self.active_stage.status == StageStatus.RUNNING
                and self.active_stage.category == cat_str
            )

        if not has_matching_active:
            self.start_stage(category, f"Running {display_label}")

        sub_env = dict(env or os.environ)
        sub_env["PYTHONUNBUFFERED"] = "1"

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=cwd,
            env=sub_env,
        )

        captured_lines: list[str] = []

        def _stream() -> None:
            if process.stdout is None:
                return
            for line in process.stdout:
                stripped = line.rstrip()
                captured_lines.append(stripped)
                logger.info(stripped, extra={"category": cat_str, "subprocess_raw": True})

                if not self.verbose:
                    clean_line = _ANSI_ESCAPE.sub("", line.split("\r")[-1]).strip()
                    if clean_line:
                        self.update_stage(clean_line)

        reader_thread = threading.Thread(target=_stream, daemon=True)
        reader_thread.start()
        returncode = process.wait()
        reader_thread.join()

        full_output = "\n".join(captured_lines)
        result: subprocess.CompletedProcess[str] = subprocess.CompletedProcess(
            cmd, returncode, stdout=full_output, stderr=""
        )

        if returncode != 0:
            err_msg = f"{display_label} failed with exit code {returncode}"
            logger.error(err_msg)
            self.fail_stage(err_msg)
            if check:
                recent_tail = "\n".join(captured_lines[-15:])
                self.render_hard_error(
                    category=category,
                    title=f"{display_label} Failed",
                    message=f"Command failed (exit {returncode}):\n{recent_tail}",
                    log_path=self.build_log_path if cat_str == LogCategory.BUILD.value else self.session_log_path,
                )
                raise subprocess.CalledProcessError(returncode, cmd, output=full_output)
        else:
            if not has_matching_active:
                self.complete_stage()

        return result

    # ─── Retention & Cleaning ────────────────────────────────────────────────

    def prune_expired_logs(self) -> int:
        """Delete log files exceeding max_launches or older than max_days.

        Returns:
            Number of files removed.
        """
        return prune_project_logs(
            self.logs_dir,
            max_days=self.max_days,
            max_launches=self.max_launches,
        )

    def shutdown(self) -> None:
        """Flush handlers and release console resources."""
        self.pause_for_interactive()
        if self._console_handler is not None:
            logging.getLogger().removeHandler(self._console_handler)
            self._console_handler.close()
            self._console_handler = None
        if self._file_handler is not None:
            self._file_handler.flush()
            self._file_handler.close()
            self._file_handler = None
        if self._build_file_handler is not None:
            self._build_file_handler.flush()
            self._build_file_handler.close()
            self._build_file_handler = None


# ─── Standalone Log Pruning & Cleaning Utilities ─────────────────────────────


def prune_project_logs(
    logs_dir: Path,
    *,
    max_days: int | None = 14,
    max_launches: int | None = 10,
) -> int:
    """Enforce log retention policy on a project's logs directory."""
    if not logs_dir.is_dir():
        return 0

    removed_count = 0
    now = time.time()

    # Collect run and build log files
    log_files: list[Path] = [
        f
        for f in logs_dir.iterdir()
        if f.is_file() and not f.is_symlink() and (f.name.startswith("run-") or f.name.startswith("build-"))
    ]

    # 1. Prune by age
    if max_days is not None and max_days > 0:
        cutoff = now - (max_days * 86400)
        remaining: list[Path] = []
        for f in log_files:
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
                    removed_count += 1
                else:
                    remaining.append(f)
            except OSError:
                continue
        log_files = remaining

    # 2. Prune by launch count (separate run logs and build logs)
    if max_launches is not None and max_launches > 0:
        for prefix in ("run-", "build-"):
            matching = sorted(
                [f for f in log_files if f.name.startswith(prefix)],
                key=lambda p: p.stat().st_mtime if p.exists() else 0,
                reverse=True,
            )
            to_remove = matching[max_launches:]
            for f in to_remove:
                try:
                    f.unlink(missing_ok=True)
                    removed_count += 1
                except OSError:
                    continue

    return removed_count


def clean_project_logs(
    project_dir: Path,
    *,
    older_than_seconds: float | None = None,
) -> list[Path]:
    """Delete log files for a specific project.

    Returns:
        List of deleted file paths.
    """
    from project import get_project_logs_dir

    logs_dir = get_project_logs_dir(project_dir)
    if not logs_dir.is_dir():
        return []

    deleted: list[Path] = []
    now = time.time()

    for item in logs_dir.iterdir():
        if item.is_symlink():
            continue
        if not item.is_file() or not (item.name.startswith("run-") or item.name.startswith("build-")):
            continue

        if older_than_seconds is not None:
            try:
                if (now - item.stat().st_mtime) < older_than_seconds:
                    continue
            except OSError:
                continue

        try:
            item.unlink(missing_ok=True)
            deleted.append(item)
        except OSError:
            pass

    return deleted


def clean_all_projects_logs(*, older_than_seconds: float | None = None) -> list[Path]:
    """Delete log files across all workspaces in ~/.local/state/pa-container/projects/."""
    state_home = os.environ.get("XDG_STATE_HOME")
    base_dir = Path(state_home) if state_home else Path.home() / ".local" / "state"
    projects_root = base_dir / "pa-container" / "projects"

    if not projects_root.is_dir():
        return []

    all_deleted: list[Path] = []
    for proj_dir in projects_root.iterdir():
        if proj_dir.is_dir():
            logs_dir = proj_dir / "logs"
            if logs_dir.is_dir():
                now = time.time()
                for item in logs_dir.iterdir():
                    if item.is_symlink() or not item.is_file():
                        continue
                    if older_than_seconds is not None:
                        try:
                            if (now - item.stat().st_mtime) < older_than_seconds:
                                continue
                        except OSError:
                            continue
                    try:
                        item.unlink(missing_ok=True)
                        all_deleted.append(item)
                    except OSError:
                        pass
    return all_deleted


# ─── Singleton Accessor ──────────────────────────────────────────────────────

_DRIVER_INSTANCE: LogDriver | None = None


def init_log_driver(
    project_dir: Path,
    *,
    log_level: str = "INFO",
    verbose: bool = False,
    quiet: bool = False,
    no_color: bool = False,
    log_file: Path | None = None,
    max_days: int | None = 14,
    max_launches: int | None = 10,
) -> LogDriver:
    """Initialize or update the singleton LogDriver instance."""
    global _DRIVER_INSTANCE
    _DRIVER_INSTANCE = LogDriver(
        project_dir,
        log_level=log_level,
        verbose=verbose,
        quiet=quiet,
        no_color=no_color,
        log_file=log_file,
        max_days=max_days,
        max_launches=max_launches,
    )
    return _DRIVER_INSTANCE


def get_log_driver() -> LogDriver | None:
    """Return the active LogDriver singleton if initialized."""
    return _DRIVER_INSTANCE


def render_hard_error(
    category: LogCategory | str,
    title: str,
    message: str,
    hints: Sequence[Any] = (),
    log_path: Path | None = None,
) -> None:
    """Module-level helper to render a hard error card via active driver or fallback console."""
    driver = get_log_driver()
    if driver is not None:
        driver.render_hard_error(category, title, message, hints=hints, log_path=log_path)
    else:
        cat_str = str(category.value if isinstance(category, LogCategory) else category)
        console = Console(stderr=True, highlight=False)
        panel = _render_error_panel(
            title=title,
            cat_str=cat_str,
            message=message,
            hints=hints,
            target_log=log_path,
        )
        console.print(panel)


def fail_and_render(
    category: LogCategory | str,
    title: str,
    message: str,
    hints: Sequence[str] = (),
    log_path: Path | None = None,
    exc: BaseException | None = None,
    source_logger: CategoryLogger | logging.Logger | None = None,
) -> None:
    """Module-level helper to log an error at ERROR level and render diagnostics card."""
    driver = get_log_driver()
    if driver is not None:
        driver.fail_and_render(
            category,
            title,
            message,
            hints=hints,
            log_path=log_path,
            exc=exc,
            source_logger=source_logger,
        )
    else:
        cat_str = str(category.value if isinstance(category, LogCategory) else category)
        logger_to_use = source_logger or get_category_logger("system", category)
        log_msg = f"{title}: {message}" if title and title not in message else message
        logger_to_use.error(log_msg, exc_info=exc or True, extra={"category": cat_str})
        render_hard_error(category, title, message, hints=hints, log_path=log_path)
