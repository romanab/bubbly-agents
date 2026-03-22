import os
import re
import shutil
import subprocess
from pathlib import Path

from sandbox.config import SandboxConfig, SandboxError, UserExistsError, UserNotFoundError
from sandbox.ids import allocate_id
from sandbox.launcher import generate_launcher
from sandbox.models import UserConfig, MountEntry
from sandbox.state import write_base, write_extra_mounts, read_profile_name, add_group_bind_mount, write_ids


def validate_username(name: str) -> None:
    """Validate against ^[a-z_][a-z0-9_-]{0,31}$. Raises ValueError."""
    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', name):
        raise ValueError(f'Invalid username "{name}": must match ^[a-z_][a-z0-9_-]{{0,31}}$')


def is_managed_user(cfg: SandboxConfig, name: str) -> bool:
    """Returns True if home dir exists AND state/{name}/ids file exists."""
    return (cfg.homes_dir / name).is_dir() and (cfg.state_dir / name / "ids").is_file()


def ensure_data_dirs(cfg: SandboxConfig, dry_run: bool = False) -> None:
    """Idempotently create launchers/, state/, homes/, groups/ as 755."""
    dirs = [
        cfg.data_dir,
        cfg.launcher_dir,
        cfg.state_dir,
        cfg.homes_dir,
        cfg.groups_dir,
    ]
    for d in dirs:
        if dry_run:
            if not d.exists():
                print(f"[dry-run] would create directory {d}")
        else:
            os.makedirs(d, exist_ok=True)
            os.chmod(d, 0o755)


def create_user(cfg: SandboxConfig, user_cfg: UserConfig, dry_run: bool = False) -> None:
    """Create a sandboxed user. Raises UserExistsError, ValueError."""
    username = user_cfg.username

    # 1. Validate username
    validate_username(username)

    # 2. Check user doesn't already exist
    if is_managed_user(cfg, username):
        raise UserExistsError(f"User {username!r} already exists")

    user_home = cfg.homes_dir / username

    # 3. Ensure data dirs
    ensure_data_dirs(cfg, dry_run)

    # 4. Allocate uid=gid via allocate_id (one ID for both)
    if not dry_run:
        uid = allocate_id(cfg.data_dir)
    else:
        uid = 0  # placeholder for dry_run

    # 5. Write state files
    write_base(cfg.state_dir, username, user_cfg, user_home, dry_run)
    path_mounts = [MountEntry("--ro-bind", p, p) for p in user_cfg.extra_paths]
    write_extra_mounts(cfg.state_dir, username, path_mounts, dry_run)
    write_ids(cfg.state_dir, username, uid, uid, dry_run)

    # 6. Create home dir (no chown, caller owns it)
    if dry_run:
        print(f"[dry-run] would create home dir {user_home} mode=0o700")
    else:
        os.makedirs(user_home, mode=0o700, exist_ok=True)

    # 7. Generate launcher
    launcher_path = cfg.launcher_dir / f"bwrap-shell-{username}"
    if dry_run:
        print(f"[dry-run] would generate launcher {launcher_path}")
    else:
        generate_launcher(cfg.launcher_dir, cfg.state_dir, username, dry_run)

    # 8. Handle extra_groups: add bind mounts and regen launcher
    for group in user_cfg.extra_groups:
        group_dir = cfg.groups_dir / group / f"{group}.group-dir"
        add_group_bind_mount(cfg.state_dir, username, group_dir, dry_run)
        if dry_run:
            print(f"[dry-run] would regenerate launcher {launcher_path} (after adding group {group})")
        else:
            generate_launcher(cfg.launcher_dir, cfg.state_dir, username, dry_run)


def audit_user(cfg: SandboxConfig, username: str) -> dict:
    """Inspect user without modifying. Reads from local files."""
    if not is_managed_user(cfg, username):
        raise UserNotFoundError(f"User {username!r} does not exist")

    launcher = cfg.launcher_dir / f"bwrap-shell-{username}"
    state_dir = cfg.state_dir / username
    actual_home = cfg.homes_dir / username

    # Home size
    home_size = ""
    if actual_home.exists():
        du_result = subprocess.run(
            ["du", "-sh", str(actual_home)],
            capture_output=True,
            text=True,
            check=False,
        )
        if du_result.returncode == 0:
            parts = du_result.stdout.split()
            if parts:
                home_size = parts[0]

    # Detect running bwrap PIDs for this user
    running_pids = []
    home_str = str(actual_home)
    proc = Path("/proc")
    try:
        for pid_path in proc.iterdir():
            if not pid_path.name.isdigit():
                continue
            try:
                if (pid_path / "exe").resolve().name != "bwrap":
                    continue
                raw = (pid_path / "cmdline").read_bytes()
                if home_str.encode() in raw:
                    running_pids.append(int(pid_path.name))
            except OSError:
                continue
    except OSError:
        pass

    return {
        "username": username,
        "home": actual_home,
        "launcher": launcher,
        "state_dir": state_dir,
        "running_pids": running_pids,
        "launcher_present": launcher.exists(),
        "shells_present": False,
        "state_dir_present": state_dir.exists(),
        "home_present": actual_home.exists(),
        "home_size": home_size,
        "private_group": None,
        "supp_groups": [],
        "actual_home": actual_home,
    }


def delete_user(
    cfg: SandboxConfig,
    username: str,
    keep_home: bool = False,
    force: bool = False,
    dry_run: bool = False,
) -> None:
    """Delete a managed sandboxed user. No confirmation prompt — caller handles that."""
    # 1. Check user exists
    if not is_managed_user(cfg, username):
        raise UserNotFoundError(f"User {username!r} does not exist")

    # 2. Audit
    audit = audit_user(cfg, username)

    # 3. Kill running bwrap processes
    if audit["running_pids"]:
        if not force:
            raise SandboxError(
                f"User {username!r} has running processes {audit['running_pids']}; use force=True to override"
            )
        import signal
        for pid in audit["running_pids"]:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

    launcher = audit["launcher"]
    actual_home = audit["actual_home"]

    # Remove launcher
    if dry_run:
        print(f"[dry-run] would remove launcher {launcher}")
    else:
        launcher.unlink(missing_ok=True)

    # Remove state dir
    if dry_run:
        print(f"[dry-run] would remove state dir {audit['state_dir']}")
    else:
        shutil.rmtree(audit["state_dir"], ignore_errors=True)

    # Remove home if requested
    canonical_home = cfg.homes_dir / username
    if not keep_home:
        if not actual_home.resolve().is_relative_to(cfg.homes_dir.resolve()):
            raise SandboxError(
                f"Refusing to delete home {actual_home}: not under {cfg.homes_dir}"
            )
        if dry_run:
            print(f"[dry-run] would remove home {actual_home}")
            if actual_home != canonical_home:
                print(f"[dry-run] would remove canonical home {canonical_home}")
        else:
            shutil.rmtree(actual_home, ignore_errors=True)
            if actual_home != canonical_home:
                shutil.rmtree(canonical_home, ignore_errors=True)


def list_users(cfg: SandboxConfig) -> list[dict]:
    """List managed users by scanning state_dir."""
    from sandbox.groups import read_group_members

    users: list[dict] = []

    if not cfg.state_dir.is_dir():
        return users

    # Build reverse map: username → list of group names they belong to
    supp_map: dict[str, list[str]] = {}
    if cfg.groups_dir.is_dir():
        for gentry in cfg.groups_dir.iterdir():
            if not gentry.is_dir():
                continue
            for member in read_group_members(cfg.groups_dir, gentry.name):
                supp_map.setdefault(member, []).append(gentry.name)

    for entry in cfg.state_dir.iterdir():
        if not entry.is_dir():
            continue
        name = entry.name

        if not (entry / "ids").is_file():
            continue

        profile = read_profile_name(cfg.state_dir, name)

        users.append({
            "username": name,
            "home": cfg.homes_dir / name,
            "profile": profile,
            "supp_groups": sorted(supp_map.get(name, [])),
        })

    return users


def list_running_usernames(cfg: SandboxConfig) -> set[str]:
    """Return the set of usernames that have a running bwrap process.

    Scans /proc once and checks each process's cmdline for the user's
    home directory path, which bwrap receives as a --bind argument.
    """
    managed = {u["username"] for u in list_users(cfg)}
    if not managed:
        return set()

    running: set[str] = set()
    proc = Path("/proc")
    try:
        pids = [p for p in proc.iterdir() if p.name.isdigit()]
    except OSError:
        return set()

    for pid_path in pids:
        try:
            exe_name = (pid_path / "exe").resolve().name
        except OSError:
            continue
        if exe_name != "bwrap":
            continue
        try:
            raw = (pid_path / "cmdline").read_bytes()
        except OSError:
            continue
        cmdline = raw.replace(b"\x00", b" ").decode(errors="replace")
        for username in managed - running:
            if str(cfg.homes_dir / username) in cmdline:
                running.add(username)

    return running
