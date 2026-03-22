from pathlib import Path

from sandbox.config import SandboxConfig, NotManagedError
from sandbox.groups import is_managed_group, read_group_members, write_group_members
from sandbox.launcher import generate_launcher
from sandbox.state import add_group_bind_mount, remove_group_bind_mount
from sandbox.users import is_managed_user


def add_member(cfg: SandboxConfig, username: str, groupname: str, dry_run: bool = False) -> None:
    """Add username to groupname."""
    if not is_managed_group(cfg, groupname):
        raise NotManagedError(f"Group {groupname!r} is not managed")
    if not is_managed_user(cfg, username):
        raise NotManagedError(f"User {username!r} is not managed")

    if dry_run:
        print(f"[dry-run] would add {username!r} to members file for group {groupname!r}")
    else:
        members = read_group_members(cfg.groups_dir, groupname)
        if username not in members:
            members.append(username)
            write_group_members(cfg.groups_dir, groupname, members)

    add_group_bind_mount(cfg.state_dir, username, cfg.groups_dir / groupname / f"{groupname}.group-dir", dry_run)
    generate_launcher(cfg.launcher_dir, cfg.state_dir, username, dry_run)


def remove_member(cfg: SandboxConfig, username: str, groupname: str, dry_run: bool = False) -> None:
    """Remove username from groupname."""
    if not is_managed_group(cfg, groupname):
        raise NotManagedError(f"Group {groupname!r} is not managed")
    if not is_managed_user(cfg, username):
        raise NotManagedError(f"User {username!r} is not managed")

    if dry_run:
        print(f"[dry-run] would remove {username!r} from members file for group {groupname!r}")
    else:
        members = read_group_members(cfg.groups_dir, groupname)
        members = [m for m in members if m != username]
        write_group_members(cfg.groups_dir, groupname, members)

    remove_group_bind_mount(cfg.state_dir, username, cfg.groups_dir / groupname / f"{groupname}.group-dir", dry_run)
    generate_launcher(cfg.launcher_dir, cfg.state_dir, username, dry_run)
