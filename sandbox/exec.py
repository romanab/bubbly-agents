"""Programmatic API for spawning commands inside sandbox environments."""
import subprocess
from sandbox.config import SandboxConfig, UserNotFoundError
from sandbox.users import is_managed_user, write_jobctl_pids


def spawn_in_sandbox(
    cfg: SandboxConfig,
    username: str,
    argv: list[str],
    *,
    stdin=None,
    stdout=None,
    stderr=None,
) -> subprocess.Popen:
    """Spawn argv inside username's sandbox. Returns Popen (non-blocking).

    The process survives the caller exiting (exec mode omits --die-with-parent).
    Track it later via sandbox.jobctl.get_user_jobs() or list_running_pids().
    """
    if not is_managed_user(cfg, username):
        raise UserNotFoundError(f"User {username!r} does not exist")
    launcher = cfg.launcher_dir / f"bwrap-shell-{username}"
    if not launcher.exists():
        raise FileNotFoundError(f"Launcher not found for {username!r}; run 'user regen'")
    write_jobctl_pids(cfg, username)
    return subprocess.Popen(
        [str(launcher), *argv],
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
    )


def run_in_sandbox(
    cfg: SandboxConfig,
    username: str,
    argv: list[str],
    *,
    capture_output: bool = False,
    input: bytes | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    """Run argv inside username's sandbox and wait for completion."""
    proc = spawn_in_sandbox(
        cfg, username, argv,
        stdin=subprocess.PIPE if input is not None else None,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.PIPE if capture_output else None,
    )
    stdout, stderr = proc.communicate(input=input, timeout=timeout)
    return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)
