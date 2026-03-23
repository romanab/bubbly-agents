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
    """Returns True if users/{name}/ids file exists."""
    return (cfg.users_dir / name / "ids").is_file()


def _migrate_old_layout(cfg: SandboxConfig) -> None:
    """Auto-migrate state/<username>/ + homes/<username>/ → users/<username>/<username>.home/"""
    old_state = cfg.data_dir / "state"
    old_homes = cfg.data_dir / "homes"
    if not old_state.is_dir():
        return

    for entry in old_state.iterdir():
        if not entry.is_dir():
            continue
        username = entry.name
        if not (entry / "ids").is_file():
            continue

        new_container = cfg.users_dir / username
        if new_container.exists():
            continue  # already migrated

        # Copy state files into new container
        shutil.copytree(entry, new_container)

        # Move home directory into container as <username>.home
        old_home = old_homes / username
        new_home = new_container / f"{username}.home"
        if old_home.is_dir():
            shutil.move(str(old_home), str(new_home))

        # Update USER_HOME in base file to new path
        base_file = new_container / "base"
        if base_file.is_file():
            lines = base_file.read_text().splitlines()
            updated = []
            for line in lines:
                if line.startswith("USER_HOME="):
                    updated.append(f"USER_HOME={new_home}")
                else:
                    updated.append(line)
            base_file.write_text("\n".join(updated) + "\n")

        # Remove old state entry
        shutil.rmtree(entry)

    # Clean up empty old directories
    try:
        if old_state.is_dir() and not any(old_state.iterdir()):
            old_state.rmdir()
    except OSError:
        pass
    try:
        if old_homes.is_dir() and not any(old_homes.iterdir()):
            old_homes.rmdir()
    except OSError:
        pass


def ensure_data_dirs(cfg: SandboxConfig, dry_run: bool = False) -> None:
    """Idempotently create launchers/, users/, groups/ as 755. Auto-migrates old layout."""
    dirs = [
        cfg.data_dir,
        cfg.launcher_dir,
        cfg.users_dir,
        cfg.groups_dir,
    ]
    for d in dirs:
        if dry_run:
            if not d.exists():
                print(f"[dry-run] would create directory {d}")
        else:
            os.makedirs(d, exist_ok=True)
            os.chmod(d, 0o755)

    if not dry_run:
        _migrate_old_layout(cfg)


def create_user(cfg: SandboxConfig, user_cfg: UserConfig, dry_run: bool = False) -> None:
    """Create a sandboxed user. Raises UserExistsError, ValueError."""
    username = user_cfg.username

    # 1. Validate username
    validate_username(username)

    # 2. Check user doesn't already exist
    if is_managed_user(cfg, username):
        raise UserExistsError(f"User {username!r} already exists")

    user_home = cfg.user_home(username)

    # 3. Ensure data dirs
    ensure_data_dirs(cfg, dry_run)

    # 4. Allocate uid=gid via allocate_id (one ID for both)
    if not dry_run:
        uid = allocate_id(cfg.data_dir)
    else:
        uid = 0  # placeholder for dry_run

    # 5. Write state files
    write_base(cfg.users_dir, username, user_cfg, user_home, dry_run)
    path_mounts = [MountEntry("--ro-bind", p, p) for p in user_cfg.extra_paths]
    write_extra_mounts(cfg.users_dir, username, path_mounts, dry_run)
    write_ids(cfg.users_dir, username, uid, uid, dry_run)

    # 6. Create home dir inside user container (no chown, caller owns it)
    if dry_run:
        print(f"[dry-run] would create home dir {user_home} mode=0o700")
    else:
        os.makedirs(user_home, mode=0o700, exist_ok=True)
        # Write .bash_profile so login shells source .bashrc.
        # bash --login reads .bash_profile, not .bashrc directly.
        bash_profile = user_home / ".bash_profile"
        if not bash_profile.exists():
            bash_profile.write_text(
                "# .bash_profile — sourced by bash login shells\n"
                "[[ -f ~/.bashrc ]] && source ~/.bashrc\n"
            )

    # 7. Generate launcher
    launcher_path = cfg.launcher_dir / f"bwrap-shell-{username}"
    if dry_run:
        print(f"[dry-run] would generate launcher {launcher_path}")
    else:
        generate_launcher(cfg.launcher_dir, cfg.users_dir, username, dry_run)

    # 8. Handle extra_groups: add bind mounts and regen launcher
    for group in user_cfg.extra_groups:
        group_dir = cfg.groups_dir / group / f"{group}.group-dir"
        add_group_bind_mount(cfg.users_dir, username, group_dir, dry_run)
        if dry_run:
            print(f"[dry-run] would regenerate launcher {launcher_path} (after adding group {group})")
        else:
            generate_launcher(cfg.launcher_dir, cfg.users_dir, username, dry_run)


def audit_user(cfg: SandboxConfig, username: str) -> dict:
    """Inspect user without modifying. Reads from local files."""
    if not is_managed_user(cfg, username):
        raise UserNotFoundError(f"User {username!r} does not exist")

    launcher = cfg.launcher_dir / f"bwrap-shell-{username}"
    user_container = cfg.users_dir / username
    actual_home = cfg.user_home(username)

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

    # Detect running PIDs for this user via HOME= in /proc/<pid>/environ
    running_pids = []
    home_marker = f"HOME={actual_home}".encode()
    proc = Path("/proc")
    try:
        for pid_path in proc.iterdir():
            if not pid_path.name.isdigit():
                continue
            try:
                raw = (pid_path / "environ").read_bytes()
                if home_marker in raw:
                    running_pids.append(int(pid_path.name))
            except OSError:
                continue
    except OSError:
        pass

    return {
        "username": username,
        "home": actual_home,
        "launcher": launcher,
        "user_container": user_container,
        "running_pids": running_pids,
        "launcher_present": launcher.exists(),
        "shells_present": False,
        "user_container_present": user_container.exists(),
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

    # 3. Kill running processes
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
    user_container = audit["user_container"]

    # Remove launcher
    if dry_run:
        print(f"[dry-run] would remove launcher {launcher}")
    else:
        launcher.unlink(missing_ok=True)

    if keep_home:
        # Remove state files but keep <username>.home/ in place
        if dry_run:
            print(f"[dry-run] would remove state files in {user_container} (keeping home)")
        else:
            for f in ["base", "ids", "extra-mounts", "profile"]:
                (user_container / f).unlink(missing_ok=True)
    else:
        # Safety check: home must be inside users_dir
        actual_home = audit["actual_home"]
        if not actual_home.resolve().is_relative_to(cfg.users_dir.resolve()):
            raise SandboxError(
                f"Refusing to delete home {actual_home}: not under {cfg.users_dir}"
            )
        # Remove entire user container (includes home)
        if dry_run:
            print(f"[dry-run] would remove user container {user_container}")
        else:
            shutil.rmtree(user_container, ignore_errors=True)


def list_users(cfg: SandboxConfig) -> list[dict]:
    """List managed users by scanning users_dir."""
    from sandbox.groups import read_group_members

    users: list[dict] = []

    if not cfg.users_dir.is_dir():
        return users

    # Build reverse map: username → list of group names they belong to
    supp_map: dict[str, list[str]] = {}
    if cfg.groups_dir.is_dir():
        for gentry in cfg.groups_dir.iterdir():
            if not gentry.is_dir():
                continue
            for member in read_group_members(cfg.groups_dir, gentry.name):
                supp_map.setdefault(member, []).append(gentry.name)

    for entry in cfg.users_dir.iterdir():
        if not entry.is_dir():
            continue
        name = entry.name

        if not (entry / "ids").is_file():
            continue

        profile = read_profile_name(cfg.users_dir, name)

        users.append({
            "username": name,
            "home": cfg.user_home(name),
            "profile": profile,
            "supp_groups": sorted(supp_map.get(name, [])),
        })

    return users


def list_running_pids(cfg: SandboxConfig) -> dict[str, list[int]]:
    """Return a mapping of username → sorted list of running PIDs.

    Scans /proc once and checks each process's environment for
    HOME=<user_home>, which is set by bwrap and inherited by all
    child processes including orphaned background jobs after exit.
    """
    managed = {u["username"] for u in list_users(cfg)}
    if not managed:
        return {}

    result: dict[str, list[int]] = {}
    markers = {username: f"HOME={cfg.user_home(username)}".encode() for username in managed}
    proc = Path("/proc")
    try:
        pids = [p for p in proc.iterdir() if p.name.isdigit()]
    except OSError:
        return {}

    for pid_path in pids:
        try:
            raw = (pid_path / "environ").read_bytes()
        except OSError:
            continue
        for username, marker in markers.items():
            if marker in raw:
                result.setdefault(username, []).append(int(pid_path.name))

    for pids_list in result.values():
        pids_list.sort()

    return result


def list_running_usernames(cfg: SandboxConfig) -> set[str]:
    """Return the set of usernames that have running processes."""
    return set(list_running_pids(cfg).keys())


def write_jobctl_pids(cfg: SandboxConfig, username: str) -> None:
    """Write current PIDs for username to $HOME/.jobctl_pids.

    Called by user_run and the TUI launcher before exec'ing the bwrap
    launcher.  Inside the sandbox, jobctl reads this file — the host
    side can read /proc/<pid>/environ freely; the sandbox cannot.
    """
    pids = list_running_pids(cfg).get(username, [])
    pids_file = cfg.user_home(username) / ".jobctl_pids"
    try:
        pids_file.write_text("".join(f"{p}\n" for p in pids))
    except OSError:
        pass
