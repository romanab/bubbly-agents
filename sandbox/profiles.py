import configparser
import shutil
import subprocess
from pathlib import Path

from sandbox.config import SandboxConfig, SandboxError
from sandbox.models import UserConfig, MountEntry, Profile


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes")


def load_profile(profiles_dir: Path, name: str) -> Profile:
    """
    Parse profiles_dir/<name>/profile.conf into a Profile dataclass.
    Raises FileNotFoundError if conf not found.
    """
    conf_path = profiles_dir / name / "profile.conf"
    if not conf_path.exists():
        raise FileNotFoundError(f"Profile config not found: {conf_path}")

    # Read raw text so we can handle list-style sections manually
    raw = conf_path.read_text(encoding="utf-8")

    # Split into sections manually to support list-valued sections
    # (shadow, install, dotfiles) where lines are NOT key=value pairs.
    sections: dict[str, list[str]] = {}
    current_section: str | None = None
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped[1:-1].lower()
            sections.setdefault(current_section, [])
        elif current_section is not None and stripped and not stripped.startswith(("#", ";")):
            sections[current_section].append(stripped)

    def kv_section(section_name: str) -> dict[str, str]:
        """Parse a section's lines as key = value pairs."""
        result: dict[str, str] = {}
        for line in sections.get(section_name, []):
            if "=" in line:
                key, _, val = line.partition("=")
                result[key.strip().replace("-", "_")] = val.strip()
        return result

    # [meta]
    meta = kv_section("meta")
    description = meta.get("description", "")

    # [user]
    user_kv = kv_section("user")
    user = UserConfig(
        username="",
        no_usr=_parse_bool(user_kv.get("no_usr", "0")),
        sys_dirs=_parse_bool(user_kv.get("sys_dirs", "0")),
        network=user_kv.get("network", "full"),
        hostname=user_kv.get("hostname", ""),
        max_procs=user_kv.get("max_procs", ""),
        max_fsize=user_kv.get("max_fsize", ""),
        max_nofile=user_kv.get("max_nofile", ""),
        cgroup_mem=user_kv.get("cgroup_mem", ""),
        cgroup_cpu=user_kv.get("cgroup_cpu", ""),
        comment=user_kv.get("comment", ""),
        extra_groups=[g.strip() for g in user_kv.get("extra_groups", "").split(",") if g.strip()],
        fake_sudo=_parse_bool(user_kv.get("fake_sudo", "0")),
    )

    # [sandbox]
    sandbox_kv = kv_section("sandbox")
    bind_entries: list[MountEntry] = []
    sandbox_hostname = ""
    for key, val in sandbox_kv.items():
        if key == "bind":
            # Only the first bind value is captured by kv_section (last wins in dict).
            # We need all bind lines, so re-parse below.
            pass
        elif key == "hostname":
            sandbox_hostname = val

    # Re-parse sandbox section for multiple bind entries
    for line in sections.get("sandbox", []):
        if "=" in line:
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if key in ("bind", "ro-bind"):
                parts = [p.strip() for p in val.split(":")]
                src = parts[0]
                dest = parts[1] if len(parts) >= 2 else src
                if key == "ro-bind" or (len(parts) >= 3 and parts[2] == "ro"):
                    kind = "--ro-bind"
                else:
                    kind = "--bind"
                bind_entries.append(MountEntry(kind, src, dest))

    # Effective hostname: sandbox section overrides user section
    hostname = sandbox_hostname if sandbox_hostname else user.hostname

    # [shadow], [install], [dotfiles] — raw line lists
    shadow_paths = list(sections.get("shadow", []))
    install_entries = list(sections.get("install", []))
    dotfiles = list(sections.get("dotfiles", []))

    # [scripts]
    scripts_kv = kv_section("scripts")
    post_setup_val = scripts_kv.get("post_setup", "")
    if post_setup_val.endswith(".sh"):
        script_path = profiles_dir / name / post_setup_val
        post_setup = script_path.read_text(encoding="utf-8") if script_path.exists() else ""
    else:
        post_setup = post_setup_val
    on_enter_val = scripts_kv.get("on_enter", "")
    if on_enter_val.endswith(".sh"):
        script_path = profiles_dir / name / on_enter_val
        on_enter = script_path.read_text(encoding="utf-8") if script_path.exists() else ""
    else:
        on_enter = on_enter_val

    return Profile(
        name=name,
        description=description,
        user=user,
        hostname=hostname,
        bind_entries=bind_entries,
        shadow_paths=shadow_paths,
        install_entries=install_entries,
        dotfiles=dotfiles,
        post_setup=post_setup,
        on_enter=on_enter,
    )


def list_profiles(profiles_dir: Path) -> list[dict]:
    """Return [{name, description}] for every valid profile directory."""
    if not profiles_dir.is_dir():
        return []
    results = []
    for entry in sorted(profiles_dir.iterdir()):
        if not entry.is_dir():
            continue
        if not (entry / "profile.conf").exists():
            continue
        try:
            profile = load_profile(profiles_dir, entry.name)
            results.append({"name": entry.name, "description": profile.description})
        except Exception:
            results.append({"name": entry.name, "description": ""})
    return results


def write_profile(profiles_dir: Path, profile_name: str, profile: "Profile") -> None:
    """Write a Profile dataclass to profiles_dir/<profile_name>/profile.conf."""
    conf_path = profiles_dir / profile_name / "profile.conf"
    lines: list[str] = []

    # [meta]
    lines.append("[meta]")
    if profile.description:
        lines.append(f"description = {profile.description}")
    lines.append("")

    # [user]
    lines.append("[user]")
    user = profile.user
    if user.no_usr:
        lines.append("no-usr = true")
    if user.sys_dirs:
        lines.append("sys-dirs = true")
    if user.network and user.network != "full":
        lines.append(f"network = {user.network}")
    if user.max_procs:
        lines.append(f"max-procs = {user.max_procs}")
    if user.max_fsize:
        lines.append(f"max-fsize = {user.max_fsize}")
    if user.max_nofile:
        lines.append(f"max-nofile = {user.max_nofile}")
    if user.cgroup_mem:
        lines.append(f"cgroup-mem = {user.cgroup_mem}")
    if user.cgroup_cpu:
        lines.append(f"cgroup-cpu = {user.cgroup_cpu}")
    if user.comment:
        lines.append(f"comment = {user.comment}")
    if user.extra_groups:
        lines.append(f"extra-groups = {','.join(user.extra_groups)}")
    if user.fake_sudo:
        lines.append("fake-sudo = true")
    lines.append("")

    # [sandbox]
    sandbox_lines = []
    if profile.hostname:
        sandbox_lines.append(f"hostname = {profile.hostname}")
    for m in profile.bind_entries:
        path_val = m.source if m.source == m.dest else f"{m.source}:{m.dest}"
        if m.kind == "--ro-bind":
            sandbox_lines.append(f"ro-bind = {path_val}")
        else:
            sandbox_lines.append(f"bind = {path_val}")
    if sandbox_lines:
        lines.append("[sandbox]")
        lines.extend(sandbox_lines)
        lines.append("")

    # [shadow]
    if profile.shadow_paths:
        lines.append("[shadow]")
        for p in profile.shadow_paths:
            lines.append(p)
        lines.append("")

    # [install]
    if profile.install_entries:
        lines.append("[install]")
        for entry in profile.install_entries:
            lines.append(entry)
        lines.append("")

    # [dotfiles]
    if profile.dotfiles:
        lines.append("[dotfiles]")
        for df in profile.dotfiles:
            lines.append(df)
        lines.append("")

    # [scripts]
    if profile.post_setup or profile.on_enter:
        lines.append("[scripts]")
        if profile.post_setup:
            lines.append("post_setup = post_setup.sh")
        if profile.on_enter:
            lines.append("on_enter = on_enter.sh")
        lines.append("")

    conf_path.write_text("\n".join(lines), encoding="utf-8")


def delete_profile(profiles_dir: Path, name: str) -> None:
    """Remove a profile directory entirely."""
    shutil.rmtree(profiles_dir / name)


def apply_profile(cfg: SandboxConfig, profile_name: str, username: str, dry_run: bool = False) -> None:
    """
    Apply a profile to create and configure a new sandbox user.
    """
    profiles_dir = cfg.project_root / "profiles"
    profile = load_profile(profiles_dir, profile_name)

    # Override username
    profile.user.username = username

    # Use profile hostname if set
    if profile.hostname:
        profile.user.hostname = profile.hostname

    # 1. Create user
    from sandbox.users import create_user
    create_user(cfg, profile.user, dry_run)

    # 2. Install binaries
    from sandbox.installs import install_binary
    for entry in profile.install_entries:
        parts = entry.split(":", 1)
        binary = Path(parts[0].strip())
        dest = parts[1].strip() if len(parts) > 1 else ""
        install_binary(cfg, username, binary, dest, dry_run)

    # 3. Bind entries (extra mounts)
    from sandbox.state import read_extra_mounts, write_extra_mounts
    existing = read_extra_mounts(cfg.users_dir, username)
    new_mounts = existing + profile.bind_entries
    seen: set[tuple[str, str, str]] = set()
    deduped: list[MountEntry] = []
    for m in new_mounts:
        key = (m.kind, m.source, m.dest)
        if key not in seen:
            seen.add(key)
            deduped.append(m)
    write_extra_mounts(cfg.users_dir, username, deduped, dry_run)

    # 4. Dotfiles (copy from profiles dir)
    user_home = cfg.user_home(username)
    profile_dir = profiles_dir / profile_name
    for dotfile in profile.dotfiles:
        src = profile_dir / dotfile
        if src.exists():
            dest_path = user_home / dotfile
            if not dest_path.resolve().is_relative_to(user_home.resolve()):
                raise ValueError(f"dotfile {dotfile!r} would escape user home — refusing")
            if dry_run:
                print(f"[dry-run] would copy {src} -> {dest_path}")
            else:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest_path)
        else:
            print(f"[profiles] dotfile not found, skipping: {src}")

    # 5. Post-setup script
    if profile.post_setup:
        cmd = ["bash", "-c", profile.post_setup]
        if dry_run:
            print(f"[dry-run] would run post_setup: {profile.post_setup}")
        else:
            subprocess.run(cmd, check=True)

    # 6. Regenerate launcher
    from sandbox.launcher import generate_launcher
    generate_launcher(cfg.launcher_dir, cfg.users_dir, username, dry_run)

    # 7. Write profile name
    from sandbox.state import write_profile_name
    write_profile_name(cfg.users_dir, username, profile_name, dry_run)
