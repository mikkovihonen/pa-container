from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import contextlib
import errno
import json
import logging
import os
import shutil
import signal
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from config_types import ClientInfo

from logging_driver import LogCategory, get_category_logger

_LOG = get_category_logger(__name__, LogCategory.PREFLIGHT)

AnyLogger = logging.Logger | logging.LoggerAdapter[Any]


def run_quiet(
    cmd: list[str],
    *,
    check: bool = True,
    label: str | None = None,
    logger: AnyLogger | None = None,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """Execute a subprocess command, capturing output and logging failures.

    Args:
        cmd: Command argv to execute.
        check: If True (default), log failure and raise CalledProcessError on non-zero exit.
        label: Display name for the command in error logs (hides raw command secrets).
        logger: Logger to receive failure messages (defaults to module logger).
        **kwargs: Additional keyword arguments passed to subprocess.run.

    Returns:
        CompletedProcess instance with captured stdout and stderr.
    """
    log = logger if logger is not None else _LOG
    name = label or (cmd[0] if cmd else "command")
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        msg = f"{name} failed (exit {result.returncode})"
        if detail:
            msg += f": {detail}"
        if check:
            log.error(msg)
            # Raise with ``name`` (not the raw argv) so command-line secrets
            # are not embedded in the exception string.
            raise subprocess.CalledProcessError(result.returncode, name, output=result.stdout, stderr=result.stderr)
        log.warning(msg)
    return result


class EnvironmentError(Exception):
    """Raised when the environment does not meet requirements."""


def validate_environment(llama_bin: str | None) -> str:
    """Validate host prerequisites (llama-server, hf CLI, podman) and return the runtime name."""
    if llama_bin is None or not Path(llama_bin).exists():
        raise EnvironmentError(
            "llama-server not found. Build an optimized minimal server for pa-container with:\n"
            "    pa build --llama\n"
            "Or configure the binary path in ~/.config/pa-container/config.yaml under llama.bin."
        )

    if shutil.which("hf") is None:
        raise EnvironmentError("hf not found. Install via: pip install huggingface_hub[cli]")

    runtime = "podman"
    if shutil.which("podman") is None:
        raise EnvironmentError("podman not found. Install it (macOS: brew install podman).")

    try:
        result = subprocess.run(
            [runtime, "info"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired as e:
        raise EnvironmentError(
            "Podman did not respond within 15 seconds. Please check if Podman is running properly (e.g. 'podman machine start')."
        ) from e
    except Exception as e:
        raise EnvironmentError(
            f"Failed to communicate with Podman: {e}. Please check if Podman is running properly."
        ) from e

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        msg = "Podman is not running or not responsive."
        if detail:
            msg += f"\n{detail}"
        msg += "\nPlease check if Podman is running properly (e.g. 'podman machine start' on macOS or check the podman service on Linux)."
        raise EnvironmentError(msg)

    return runtime


_allocated_ports_lock = threading.Lock()
_allocated_ports: set[int] = set()


def get_free_port() -> int:
    """Bind to an ephemeral port on 127.0.0.1, close the socket, and return a free port number.

    Thread-safe against concurrent allocations within the same process.
    """
    with _allocated_ports_lock:
        for _ in range(50):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("", 0))
                port: int = int(s.getsockname()[1])
                if port not in _allocated_ports:
                    _allocated_ports.add(port)
                    return port
        return port


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a TCP port is available on the given host interface."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True
    except OSError as e:
        _LOG.debug(f"Port {port} on {host} is unavailable: {e}")
        return False


def is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is running on the host.

    Returns False if pid <= 0 or if no such process exists.
    Returns True if the process exists (even if we lack permission to signal it).
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError as e:
        if e.errno == errno.ESRCH:
            return False
        return e.errno == errno.EPERM


@contextmanager
def file_lock(
    lock_file: Path,
    *,
    timeout: float = 30.0,
    poll_interval: float = 0.05,
    logger: AnyLogger | None = None,
    label: str = "resource",
) -> Generator[TextIO]:
    """Context manager for acquiring an exclusive file lock with timeout and contention logging."""
    import fcntl

    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with lock_file.open("a") as f:
        start_time = time.time()
        acquired = False
        logged_waiting = False
        while not acquired:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except (BlockingIOError, OSError) as e:
                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    raise TimeoutError(
                        f"Timed out after {timeout}s waiting for file lock on {lock_file} ({label})"
                    ) from e
                if not logged_waiting and elapsed >= 1.0:
                    if logger:
                        logger.info(f"Waiting for lock on {lock_file.name} ({label})...")
                    logged_waiting = True
                time.sleep(poll_interval)
        try:
            yield f
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(f, fcntl.LOCK_UN)


def read_live_clients(clients_file: Path) -> list[ClientInfo]:
    """Read a JSON client manifest and return only clients whose PIDs are alive.

    The manifest is expected to be a JSON array of dicts, each with at least a
    'pid' key (int). Dead clients are automatically filtered out.
    """
    if not clients_file.exists():
        return []
    try:
        data = json.loads(clients_file.read_text())
        if not isinstance(data, list):
            return []
        live: list[ClientInfo] = []
        for entry in data:
            if isinstance(entry, dict) and "pid" in entry:
                pid = entry["pid"]
                if isinstance(pid, int) and is_pid_alive(pid):
                    live.append(cast("ClientInfo", entry))
        return live
    except OSError, json.JSONDecodeError:
        return []


def write_clients(clients_file: Path, clients: list[ClientInfo]) -> None:
    """Write the client list as JSON to clients_file atomically."""
    clients_file.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(clients, indent=2) + "\n"
    temp_file = clients_file.with_name(f"{clients_file.name}.tmp.{os.getpid()}.{time.time_ns()}")
    try:
        temp_file.write_text(content)
        temp_file.replace(clients_file)
    except Exception:
        temp_file.unlink(missing_ok=True)
        raise


def register_client(clients_file: Path, client_info: ClientInfo) -> list[ClientInfo]:
    """Prune dead clients, add `client_info` to clients_file, and return the live list."""
    live = read_live_clients(clients_file)
    pid = client_info.get("pid")
    run_id = client_info.get("run_id")
    live = [c for c in live if not (c.get("pid") == pid and (run_id is None or c.get("run_id") == run_id))]
    live.append(client_info)
    write_clients(clients_file, live)
    return live


def deregister_client(clients_file: Path, pid: int, run_id: str | None = None) -> list[ClientInfo]:
    """Remove client matching pid (and optionally run_id), prune dead clients, and update file."""
    live = read_live_clients(clients_file)
    remaining = [c for c in live if not (c.get("pid") == pid and (run_id is None or c.get("run_id") == run_id))]
    if remaining:
        write_clients(clients_file, remaining)
    else:
        clients_file.unlink(missing_ok=True)
    return remaining


def get_ref_count(clients_file: Path) -> int:
    """Return active client count from clients_file."""
    return len(read_live_clients(clients_file))


def start_refcounted_resource(
    *,
    lock_file: Path,
    clients_file: Path,
    client_info: ClientInfo,
    is_healthy_fn: Callable[[], bool],
    start_fn: Callable[[], None],
    stop_fn: Callable[[], None],
    cleanup_stale_fn: Callable[[], None] | None = None,
    on_attach_fn: Callable[[int], None] | None = None,
    on_adopt_fn: Callable[[], None] | None = None,
    logger: AnyLogger | None = None,
    label: str = "resource",
) -> None:
    """Acquire lock, check resource health, and attach/adopt/restart the refcounted resource."""
    with file_lock(lock_file, logger=logger, label=label):
        live_clients = read_live_clients(clients_file)
        healthy = is_healthy_fn()

        if live_clients:
            if healthy:
                register_client(clients_file, client_info)
                if on_attach_fn:
                    on_attach_fn(len(live_clients) + 1)
            else:
                if logger:
                    logger.warning(f"Existing {label} clients > 0 but resource is unhealthy or stale; restarting.")
                stop_fn()
                if cleanup_stale_fn:
                    cleanup_stale_fn()
                start_fn()
                write_clients(clients_file, [client_info])
        else:
            if healthy:
                if on_adopt_fn:
                    on_adopt_fn()
                elif logger:
                    logger.info(f"Adopting existing healthy {label}")
                write_clients(clients_file, [client_info])
            else:
                if clients_file.exists():
                    stop_fn()
                    if cleanup_stale_fn:
                        cleanup_stale_fn()
                start_fn()
                write_clients(clients_file, [client_info])


def stop_refcounted_resource(
    *,
    lock_file: Path,
    clients_file: Path,
    pid: int,
    stop_fn: Callable[[], None],
    full_cleanup_fn: Callable[[], None] | None = None,
    run_id: str | None = None,
    logger: AnyLogger | None = None,
    label: str = "resource",
) -> bool:
    """Deregister client from resource under lock. If last client, trigger full stop and cleanup."""
    if not lock_file.exists() and not clients_file.exists():
        return False

    should_full_cleanup = False
    with file_lock(lock_file, logger=logger, label=label):
        remaining = deregister_client(clients_file, pid, run_id)
        if not remaining:
            stop_fn()
            should_full_cleanup = True

    if should_full_cleanup:
        clients_file.unlink(missing_ok=True)
        lock_file.unlink(missing_ok=True)
        if full_cleanup_fn:
            full_cleanup_fn()
        return True

    return False


def handle_signal(signum: int, frame: object | None = None, logger: AnyLogger | None = None) -> None:
    """Handle termination signals (SIGINT, SIGTERM, SIGHUP, SIGQUIT).

    Compatible with Python signal handler callbacks ``(signum, frame)`` as well
    as explicit logger injections in tests.
    """
    try:
        signame: str = signal.Signals(signum).name
    except ValueError:
        signame = f"signal {signum}"
    msg = f"Received {signame}. Initiating clean shutdown..."
    if logger is not None:
        logger.info(msg)
    elif frame is not None and hasattr(frame, "info") and callable(getattr(frame, "info", None)):
        frame.info(msg)
    else:
        _LOG.info(msg)
    raise SystemExit(128 + signum)


def stop_process_group(pid: int, name: str, logger: AnyLogger) -> None:
    """Stops a process group to ensure all child processes are killed."""
    logger.info(f"Stopping process group for {name} (pid: {pid})...")
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)

        for _ in range(10):
            try:
                os.killpg(pgid, 0)
                time.sleep(0.5)
            except OSError as e:
                if e.errno in (errno.ESRCH, errno.EPERM):
                    break
                raise
        else:
            os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError as e:
        if e.errno != errno.ESRCH:
            logger.error(f"Error stopping process group for {name}: {e}")


def extract_ipv4_from_ip_addr(output: str) -> str | None:
    """Extract the first IPv4 address from ``ip addr show`` output.

    Matches ``inet 1.2.3.4/n`` — the standard format for both ``ip addr`` and
    ``ifconfig`` output on Linux. Returns None if no match is found.
    """
    import re as _re

    match = _re.search(r"inet\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})/\d+", output)
    return match.group(1) if match else None


def get_host_external_ip() -> str:
    """Detect the host machine's primary outbound IPv4 address on the local network.

    Uses a UDP routing probe to a public address (no network packets are sent).
    Falls back to hostname resolution, and finally to '127.0.0.1' if offline.
    """
    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("1.1.1.1", 80))
            ip: str = str(s.getsockname()[0])
            if ip and not ip.startswith("127."):
                return ip
        finally:
            s.close()
    except Exception as e:
        _LOG.debug(f"External IP resolution via UDP socket probe failed: {e}")

    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except Exception as e:
        _LOG.debug(f"External IP resolution via gethostbyname failed: {e}")

    return "127.0.0.1"
