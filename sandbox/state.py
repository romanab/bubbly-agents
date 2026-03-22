from pathlib import Path
from sandbox.models import UserConfig, MountEntry


def _user_dir(state_dir: Path, username: str) -> Path:
    return state_dir / username


def _ensure_user_dir(state_dir: Path, username: str) -> Path:
    d = _user_dir(state_dir, username)
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    return d


def _write_secure(path: Path, content: str, mode: int = 0o600, dry_run: bool = False):
    """Write content to path atomically via a .tmp sibling, then set permissions."""
    if dry_run:
        print(f"[dry-run] would write {path}")
        return
    tmp = path.parent / (path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.chmod(mode)
    tmp.rename(path)


# ---------------------------------------------------------------------------
# base
# ---------------------------------------------------------------------------

def read_base(state_dir: Path, username: str) -> dict[str, str]:
    """Read KEY=VALUE base file, return dict. Empty dict if missing."""
    path = _user_dir(state_dir, username) / "base"
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def write_ids(state_dir: Path, username: str, uid: int, gid: int, dry_run: bool = False) -> None:
    """Write internal UID and GID to state/{username}/ids file."""
    path = _user_dir(state_dir, username) / "ids"
    if not dry_run:
        _ensure_user_dir(state_dir, username)
    content = f"{uid}\n{gid}\n"
    _write_secure(path, content, mode=0o600, dry_run=dry_run)


def read_ids(state_dir: Path, username: str) -> tuple[int, int] | None:
    """Read internal UID and GID from state/{username}/ids.
    Returns (uid, gid) or None if file missing or malformed."""
    path = _user_dir(state_dir, username) / "ids"
    if not path.exists():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        return (int(lines[0]), int(lines[1]))
    except (IndexError, ValueError):
        return None


def write_base(state_dir: Path, username: str, cfg: UserConfig, home: Path, dry_run: bool = False):
    """Write base state file from UserConfig. Creates dir if needed."""
    path = _user_dir(state_dir, username) / "base"
    if not dry_run:
        _ensure_user_dir(state_dir, username)
    hostname = cfg.hostname if cfg.hostname else f"sandbox-{username}"
    content = (
        f"NO_USR={1 if cfg.no_usr else 0}\n"
        f"SYS_DIRS={1 if cfg.sys_dirs else 0}\n"
        f"USER_HOME={home}\n"
        f"HOSTNAME={hostname}\n"
        f"NETWORK={cfg.network}\n"
        f"MAX_PROCS={cfg.max_procs}\n"
        f"MAX_FSIZE={cfg.max_fsize}\n"
        f"MAX_NOFILE={cfg.max_nofile}\n"
        f"CGROUP_MEM={cfg.cgroup_mem}\n"
        f"CGROUP_CPU={cfg.cgroup_cpu}\n"
        f"FAKE_SUDO={1 if cfg.fake_sudo else 0}\n"
    )
    _write_secure(path, content, mode=0o600, dry_run=dry_run)


# ---------------------------------------------------------------------------
# extra-mounts
# ---------------------------------------------------------------------------

def read_extra_mounts(state_dir: Path, username: str) -> list[MountEntry]:
    """Read extra-mounts file, parse into list of MountEntry. Empty list if missing."""
    path = _user_dir(state_dir, username) / "extra-mounts"
    if not path.exists():
        return []
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    entries: list[MountEntry] = []
    for i in range(0, len(lines) - (len(lines) % 3), 3):
        entries.append(MountEntry(kind=lines[i], source=lines[i + 1], dest=lines[i + 2]))
    return entries


def write_extra_mounts(state_dir: Path, username: str, mounts: list[MountEntry], dry_run: bool = False):
    """Write extra-mounts file from list of MountEntry."""
    path = _user_dir(state_dir, username) / "extra-mounts"
    if not dry_run:
        _ensure_user_dir(state_dir, username)
    content = ""
    for m in mounts:
        content += f"{m.kind}\n{m.source}\n{m.dest}\n"
    _write_secure(path, content, mode=0o600, dry_run=dry_run)


# ---------------------------------------------------------------------------
# profile
# ---------------------------------------------------------------------------

def read_profile_name(state_dir: Path, username: str) -> str:
    """Read profile name. Empty string if missing."""
    path = _user_dir(state_dir, username) / "profile"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def write_profile_name(state_dir: Path, username: str, name: str, dry_run: bool = False):
    """Write profile name file."""
    path = _user_dir(state_dir, username) / "profile"
    if not dry_run:
        _ensure_user_dir(state_dir, username)
    _write_secure(path, name + "\n", mode=0o644, dry_run=dry_run)


# ---------------------------------------------------------------------------
# group bind-mount helpers
# ---------------------------------------------------------------------------

def add_group_bind_mount(state_dir: Path, username: str, group_dir: Path, dry_run=False):
    em_file = state_dir / username / "extra-mounts"
    group_str = str(group_dir)

    if dry_run:
        print(f"[dry-run] would add --bind {group_str} {group_str} to {em_file}")
        return

    # Ensure file exists
    if not em_file.exists():
        _ensure_user_dir(state_dir, username)
        _write_secure(em_file, "", mode=0o600)

    existing = read_extra_mounts(state_dir, username)
    for m in existing:
        if m.kind == "--bind" and m.source == group_str and m.dest == group_str:
            return  # already present

    existing.append(MountEntry("--bind", group_str, group_str))
    write_extra_mounts(state_dir, username, existing)


def remove_group_bind_mount(state_dir: Path, username: str, group_dir: Path, dry_run: bool = False):
    """Remove the --bind block for group_dir from extra-mounts."""
    path = _user_dir(state_dir, username) / "extra-mounts"
    group_str = str(group_dir)

    if dry_run:
        print(f"[dry-run] would remove bind mount {group_str} for {username}")
        return

    if not path.exists():
        return

    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    # Rebuild triples, skipping any that reference group_str
    kept: list[str] = []
    i = 0
    while i + 2 < len(lines):
        kind, src, dst = lines[i], lines[i + 1], lines[i + 2]
        if src == group_str or dst == group_str:
            i += 3
            continue
        kept.extend([kind, src, dst])
        i += 3

    content = "".join(ln + "\n" for ln in kept)
    _write_secure(path, content, mode=0o600)
