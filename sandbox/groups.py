import os
import shutil
import stat
import subprocess
from pathlib import Path

from sandbox.config import (
    SandboxConfig,
    SandboxError,
    GroupExistsError,
    GroupNotFoundError,
)
from sandbox.ids import allocate_id
from sandbox.state import remove_group_bind_mount
from sandbox.users import ensure_data_dirs, is_managed_user, validate_username


def _atomic_write(path: Path, content: str) -> None:
    """Write content atomically via a .tmp sibling."""
    tmp = path.parent / (path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.rename(path)


def _parse_mode(mode_str: str) -> int:
    """Parse a symbolic mode string like 'u=rwx,g=rwx,o=' into an integer bitmask."""
    _bit_map = {
        "u": {"r": stat.S_IRUSR, "w": stat.S_IWUSR, "x": stat.S_IXUSR},
        "g": {"r": stat.S_IRGRP, "w": stat.S_IWGRP, "x": stat.S_IXGRP},
        "o": {"r": stat.S_IROTH, "w": stat.S_IWOTH, "x": stat.S_IXOTH},
    }
    result = 0
    for clause in mode_str.split(","):
        clause = clause.strip()
        if not clause or "=" not in clause:
            continue
        who, perms = clause.split("=", 1)
        who = who.strip()
        for perm_char in perms:
            if perm_char in _bit_map.get(who, {}):
                result |= _bit_map[who][perm_char]
    return result


def is_managed_group(cfg: SandboxConfig, name: str) -> bool:
    """Returns True if groups_dir/name/{name}.gid file exists."""
    return (cfg.groups_dir / name / f"{name}.gid").is_file()


def create_group(cfg: SandboxConfig, name: str, mode: str = "u=rwx,g=rwx,o=", dry_run: bool = False) -> None:
    """Create a shared group without system calls."""
    # 1. Validate name
    validate_username(name)

    # 2. Check not already managed
    if is_managed_group(cfg, name):
        raise GroupExistsError(f"Group {name!r} already exists")

    group_container = cfg.groups_dir / name
    shared_dir = group_container / f"{name}.group-dir"

    # 3. Ensure data dirs
    ensure_data_dirs(cfg, dry_run)

    # 4. Allocate GID
    gid = allocate_id(cfg.data_dir)

    if dry_run:
        print(f"[dry-run] would create group container {group_container}")
        print(f"[dry-run] would create shared directory {shared_dir}")
        print(f"[dry-run] would chmod {mode} {shared_dir}")
        print(f"[dry-run] would write gid file {group_container / f'{name}.gid'} with value {gid}")
        print(f"[dry-run] would write empty members file {group_container / f'{name}.members'}")
        return

    # 5. Create container dir (fixed 0o755) and shared dir (user-supplied mode)
    group_container.mkdir(parents=True, exist_ok=True)
    shared_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(str(shared_dir), _parse_mode(mode))

    # 6. Write gid file
    _atomic_write(group_container / f"{name}.gid", str(gid) + "\n")

    # 7. Write empty members file
    _atomic_write(group_container / f"{name}.members", "")


def read_group_members(groups_dir: Path, name: str) -> list[str]:
    """Read members from groups/{name}/{name}.members. Returns [] if missing."""
    members_file = groups_dir / name / f"{name}.members"
    if not members_file.exists():
        return []
    return [line.strip() for line in members_file.read_text().splitlines() if line.strip()]


def write_group_members(groups_dir: Path, name: str, members: list[str]) -> None:
    """Write members list to groups/{name}/{name}.members."""
    members_file = groups_dir / name / f"{name}.members"
    content = ("\n".join(members) + "\n") if members else ""
    _atomic_write(members_file, content)


def read_group_gid(groups_dir: Path, name: str) -> int | None:
    """Read GID from groups/{name}/{name}.gid. Returns None if missing/malformed."""
    gid_file = groups_dir / name / f"{name}.gid"
    if not gid_file.exists():
        return None
    try:
        return int(gid_file.read_text().strip())
    except (ValueError, OSError):
        return None


def audit_group(cfg: SandboxConfig, name: str) -> dict:
    """
    Inspect group without modifying. Reads from local files.
    Returns dict with: groupname, gid, group_dir, members, group_dir_present, group_dir_size
    """
    if not is_managed_group(cfg, name):
        raise GroupNotFoundError(f"Group {name!r} does not exist")

    gid = read_group_gid(cfg.groups_dir, name)
    group_dir = cfg.groups_dir / name / f"{name}.group-dir"
    members = read_group_members(cfg.groups_dir, name)

    # group_dir size
    group_dir_size = ""
    if group_dir.exists():
        du_result = subprocess.run(
            ["du", "-sh", str(group_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        if du_result.returncode == 0:
            parts = du_result.stdout.split()
            if parts:
                group_dir_size = parts[0]

    return {
        "groupname": name,
        "gid": gid,
        "group_dir": group_dir,
        "members": members,
        "group_dir_present": group_dir.exists(),
        "group_dir_size": group_dir_size,
    }


def delete_group(cfg: SandboxConfig, name: str, dry_run: bool = False) -> None:
    """Delete a managed group. Removes gid file, members file, group dir."""
    from sandbox.launcher import generate_launcher

    if not is_managed_group(cfg, name):
        raise GroupNotFoundError(f"Group {name!r} does not exist")

    audit = audit_group(cfg, name)
    group_dir = audit["group_dir"]  # the shared dir (for bind mount removal)
    container_dir = cfg.groups_dir / name

    # Remove bind mounts and regenerate launchers for each member
    for member in audit["members"]:
        if is_managed_user(cfg, member):
            remove_group_bind_mount(cfg.state_dir, member, group_dir, dry_run)
            generate_launcher(cfg.launcher_dir, cfg.state_dir, member, dry_run)

    # Remove entire container (gid, members, shared dir)
    if container_dir.exists():
        if dry_run:
            print(f"[dry-run] would remove group container {container_dir}")
        else:
            shutil.rmtree(container_dir)


def list_groups(cfg: SandboxConfig) -> list[dict]:
    """
    List managed groups. Scans for dirs with gid file.
    Returns list of dicts: groupname, gid, group_dir, members, dir_size, dir_mode
    """
    result: list[dict] = []

    if not cfg.groups_dir.is_dir():
        return result

    for entry in cfg.groups_dir.iterdir():
        if not entry.is_dir():
            continue
        name = entry.name

        if not is_managed_group(cfg, name):
            continue

        gid = read_group_gid(cfg.groups_dir, name)
        members = read_group_members(cfg.groups_dir, name)
        shared_dir = entry / f"{name}.group-dir"

        # dir size (of shared dir)
        dir_size = ""
        if shared_dir.exists():
            du_result = subprocess.run(
                ["du", "-sh", str(shared_dir)],
                capture_output=True,
                text=True,
                check=False,
            )
            if du_result.returncode == 0:
                parts = du_result.stdout.split()
                if parts:
                    dir_size = parts[0]

        # dir mode (of shared dir)
        try:
            st = shared_dir.stat()
            dir_mode = oct(st.st_mode & 0o777)
        except OSError:
            dir_mode = ""

        result.append({
            "groupname": name,
            "gid": gid,
            "group_dir": shared_dir,
            "members": members,
            "dir_size": dir_size,
            "dir_mode": dir_mode,
        })

    return result
