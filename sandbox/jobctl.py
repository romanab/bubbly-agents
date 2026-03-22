"""Process management for sandbox users.

Reads /proc directly; no root required.
"""
import os
import signal as _signal
from pathlib import Path


def _parse_elapsed(secs: float) -> str:
    secs = max(0, int(secs))
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return f"{d}-{h:02d}:{m:02d}:{s:02d}"
    return f"{h:02d}:{m:02d}:{s:02d}"


def get_process_info(pid: int) -> dict | None:
    """Read PID, state, elapsed time, and command from /proc/<pid>.

    Returns None if the process has gone away.
    """
    pid_path = Path(f"/proc/{pid}")
    try:
        raw_cmd = (pid_path / "cmdline").read_bytes()
        stat_text = (pid_path / "stat").read_text()
        uptime = float(Path("/proc/uptime").read_text().split()[0])
    except OSError:
        return None

    # stat field 2 is (comm) which may contain spaces/parens; find last ')'
    rp = stat_text.rfind(")")
    if rp == -1:
        return None
    fields = stat_text[rp + 2:].split()
    if len(fields) < 20:
        return None

    state = fields[0]
    try:
        starttime = int(fields[19])
    except (ValueError, IndexError):
        return None

    clk_tck = os.sysconf("SC_CLK_TCK")
    elapsed = uptime - starttime / clk_tck

    cmdline = raw_cmd.replace(b"\x00", b" ").decode(errors="replace").strip()
    command = cmdline[:80] if cmdline else f"[{pid}]"

    return {
        "pid": pid,
        "state": state,
        "elapsed": _parse_elapsed(elapsed),
        "command": command,
    }


def get_user_jobs(cfg, username: str) -> list[dict]:
    """Return process info for all PIDs running under username's HOME."""
    from sandbox.users import audit_user
    audit = audit_user(cfg, username)
    jobs = []
    for pid in audit["running_pids"]:
        info = get_process_info(pid)
        if info:
            info["username"] = username
            jobs.append(info)
    return sorted(jobs, key=lambda x: x["pid"])


def get_all_jobs(cfg) -> list[dict]:
    """Return process info for all PIDs across all managed users."""
    from sandbox.users import list_running_pids
    pid_map = list_running_pids(cfg)
    jobs = []
    for username, pids in sorted(pid_map.items()):
        for pid in pids:
            info = get_process_info(pid)
            if info:
                info["username"] = username
                jobs.append(info)
    return jobs


def send_signal(cfg, username: str, sig: int, pid: int | None = None) -> list[int]:
    """Send signal to one or all jobs for a user.

    If pid is given, verifies it belongs to username first.
    Returns list of PIDs signalled.
    """
    from sandbox.users import audit_user
    audit = audit_user(cfg, username)
    running = set(audit["running_pids"])

    if pid is not None:
        if pid not in running:
            raise ValueError(f"PID {pid} does not belong to user '{username}'")
        targets = [pid]
    else:
        targets = sorted(running)

    sent = []
    for p in targets:
        try:
            os.kill(p, sig)
            sent.append(p)
        except OSError:
            pass
    return sent
