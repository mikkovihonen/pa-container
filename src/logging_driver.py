from __future__ import annotations

import atexit
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
    from collections.abc import Sequence

sys.dont_write_bytecode = True

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
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


# ─── Category Status Item ────────────────────────────────────────────────────


class CategoryStatus:
    """Tracks state and live rendering text for a single category step."""

    def __init__(self, category: LogCategory | str, label: str) -> None:
        self.category: str = str(category.value if isinstance(category, LogCategory) else category)
        self.label: str = label
        self.detail: str = ""
        self.start_time: float = time.monotonic()
        self.completed: bool = False
        self.failed: bool = False
        self.spinner: Spinner = Spinner("dots")

    def render(self) -> Text:
        elapsed = time.monotonic() - self.start_time
        text = Text()
        if self.failed:
            text.append("  ✗ ", style="bold red")
            text.append(f"[{self.category}] ", style="dim")
            text.append(self.label, style="bold red")
            if self.detail:
                text.append(f" ({self.detail})", style="red")
        elif self.completed:
            text.append("  ✔ ", style="bold green")
            text.append(f"[{self.category}] ", style="dim")
            text.append(self.label, style="bold")
            text.append(f" ({elapsed:.1f}s)", style="dim")
            if self.detail:
                text.append(f" - {self.detail}", style="dim")
        else:
            text.append("  ")
            spin_render = self.spinner.render(time.monotonic())
            if isinstance(spin_render, Text):
                text.append_text(spin_render)
            else:
                text.append(str(spin_render))
            text.append(" ")
            text.append(f"[{self.category}] ", style="dim cyan")
            text.append(self.label, style="bold cyan")
            if self.detail:
                text.append(f": {self.detail}", style="yellow")
            else:
                text.append(f" ({elapsed:.1f}s)", style="dim")
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
        self._statuses: dict[str, CategoryStatus] = {}
        self._lock: threading.Lock = threading.Lock()
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

        # 3. Standard live terminal mode
        if record.levelno >= logging.ERROR:
            if cat_str and cat_str in self._statuses:
                self.step_fail(cat_str, msg)
            else:
                tag = f"[{cat_str}]" if cat_str else "[system]"
                self._print(f"[bold red]✗ {tag} {msg}[/bold red]")
            return

        if record.levelno >= logging.WARNING:
            tag = f"[{cat_str}]" if cat_str else f"[{record.name}]"
            self._print(f"[bold yellow]⚠ {tag} {msg}[/bold yellow]")
            return

        if record.levelno == logging.INFO and cat_str:
            if cat_str in self._statuses and not self._statuses[cat_str].completed:
                self.step_update(cat_str, msg)
            elif not self.console.is_terminal:
                self.console.print(f"[{cat_str}] {msg}")
            else:
                self.step(cat_str, msg)

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

    # ─── Live Progress UI ────────────────────────────────────────────────────

    def _refresh_live(self) -> None:
        """Update live console rendering from current statuses."""
        if self.quiet or self.verbose or not self.console.is_terminal:
            return

        with self._lock:
            if not self._statuses:
                return

            text = Text()
            for status in self._statuses.values():
                text.append_text(status.render())
                text.append("\n")

            if self._live is None and not self._interactive_paused:
                self._live = Live(
                    text,
                    console=self.console,
                    refresh_per_second=10,
                    transient=False,
                    auto_refresh=True,
                )
                self._live.start()
            elif self._live is not None:
                self._live.update(text)

    def step(self, category: LogCategory | str, label: str) -> None:
        """Begin a progress milestone for the given category."""
        cat_key = str(category.value if isinstance(category, LogCategory) else category)

        with self._lock:
            status = CategoryStatus(cat_key, label)
            self._statuses[cat_key] = status

        if self.verbose:
            self.console.print(f"[dim]⠋ [{cat_key}][/dim] {label}...")
        elif not self.console.is_terminal and not self.quiet:
            self.console.print(f"[{cat_key}] {label}...")
        else:
            self._refresh_live()

    def step_update(self, category: LogCategory | str, detail: str) -> None:
        """Update in-place detail text for an active category step."""
        cat_key = str(category.value if isinstance(category, LogCategory) else category)

        with self._lock:
            if cat_key in self._statuses:
                self._statuses[cat_key].detail = detail

        if self.verbose:
            self.console.print(f"  [{cat_key}] {detail}")
        else:
            self._refresh_live()

    def step_done(self, category: LogCategory | str, detail: str | None = None) -> None:
        """Mark a category milestone as successfully completed."""
        cat_key = str(category.value if isinstance(category, LogCategory) else category)

        with self._lock:
            if cat_key in self._statuses:
                st = self._statuses[cat_key]
                st.completed = True
                if detail:
                    st.detail = detail

        if self.verbose:
            self.console.print(f"[bold green]✔ [{cat_key}][/bold green] done")
        elif not self.console.is_terminal and not self.quiet:
            self.console.print(f"[{cat_key}] ✔ Done")
        else:
            self._refresh_live()

    def step_fail(self, category: LogCategory | str, message: str) -> None:
        """Mark a category milestone as failed."""
        cat_key = str(category.value if isinstance(category, LogCategory) else category)

        with self._lock:
            if cat_key in self._statuses:
                st = self._statuses[cat_key]
                st.failed = True
                st.detail = message

        if self.verbose or not self.console.is_terminal:
            self.console.print(f"[bold red]✗ [{cat_key}][/bold red] {message}")
        else:
            self._refresh_live()

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
        hints: Sequence[str] = (),
        log_path: Path | None = None,
    ) -> None:
        """Render a formatted diagnostics card for fatal errors."""
        cat_str = str(category.value if isinstance(category, LogCategory) else category)

        with self._lock:
            # Mark the specific category step as failed if in flight
            if cat_str in self._statuses and not self._statuses[cat_str].completed:
                self._statuses[cat_str].failed = True
                if not self._statuses[cat_str].detail:
                    self._statuses[cat_str].detail = message
            # Mark any other in-flight steps as failed to clean up spinners
            for st in self._statuses.values():
                if not st.completed and not st.failed:
                    st.failed = True

            # Refresh live view with failed state before pausing
            if self._live is not None and not self._interactive_paused:
                text = Text()
                for status in self._statuses.values():
                    text.append_text(status.render())
                    text.append("\n")
                self._live.update(text)

        self.pause_for_interactive()

        target_log = log_path or self.session_log_path

        body = Text()
        body.append(f"{message}\n", style="bold")

        if hints:
            body.append("\nSuggested remediation:\n", style="yellow")
            for hint in hints:
                body.append(f"  {hint}\n", style="dim yellow")

        body.append(f"\nDiagnostic log:\n  {target_log}", style="dim cyan")

        panel = Panel(
            body,
            title=f"[bold red]Error: {title} [category: {cat_str}][/bold red]",
            border_style="red",
            expand=False,
        )
        self.console.print(panel)

    def fail_and_render(
        self,
        category: LogCategory | str,
        title: str,
        message: str,
        hints: Sequence[str] = (),
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
        """Execute a subprocess, streaming lines to disk logs while updating live step status.

        Args:
            cmd: Command line arguments.
            category: Semantic category tag for logging and step progression.
            label: Display label for the command in error diagnostics.
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
        self.step(category, f"Running {display_label}")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=cwd,
            env=env,
        )

        captured_lines: list[str] = []
        step_regex = re.compile(r"^\s*(STEP\s+\d+/\d+.*)", re.IGNORECASE)

        def _stream() -> None:
            if process.stdout is None:
                return
            for line in process.stdout:
                stripped = line.rstrip()
                captured_lines.append(stripped)
                logger.info(stripped, extra={"category": cat_str})

                match = step_regex.match(stripped)
                if match and not self.verbose:
                    self.step_update(category, match.group(1))

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
            self.step_fail(category, err_msg)
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
            self.step_done(category)

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
    hints: Sequence[str] = (),
    log_path: Path | None = None,
) -> None:
    """Module-level helper to render a hard error card via active driver or fallback console."""
    driver = get_log_driver()
    if driver is not None:
        driver.render_hard_error(category, title, message, hints=hints, log_path=log_path)
    else:
        cat_str = str(category.value if isinstance(category, LogCategory) else category)
        console = Console(stderr=True, highlight=False)
        body = Text()
        body.append(f"{message}\n", style="bold")
        if hints:
            body.append("\nSuggested remediation:\n", style="yellow")
            for hint in hints:
                body.append(f"  {hint}\n", style="dim yellow")
        panel = Panel(
            body,
            title=f"[bold red]Error: {title} [category: {cat_str}][/bold red]",
            border_style="red",
            expand=False,
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
