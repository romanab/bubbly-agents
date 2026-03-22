import os
import subprocess
import shutil
import re
from pathlib import Path

from sandbox.config import SandboxConfig, SandboxError
from sandbox.models import MountEntry
from sandbox.state import read_extra_mounts, write_extra_mounts
from sandbox.launcher import generate_launcher


def collect_ldd_deps(binary: Path) -> list[Path]:
    """
    Run ldd on binary, parse output, return list of resolved library paths.
    Skip 'linux-vdso', 'not found', and lines without '=>'.
    """
    result = subprocess.run(
        ["ldd", str(binary)],
        capture_output=True,
        text=True,
        check=True,
    )

    deps: list[Path] = []
    for line in result.stdout.splitlines():
        # Skip the vDSO (virtual dynamic shared object — kernel-injected, no real path)
        if "linux-vdso" in line:
            continue

        if "=>" in line:
            # e.g. "    libfoo.so => /lib/libfoo.so (0x...)"
            # or   "    libfoo.so => not found"
            after_arrow = line.split("=>", 1)[1].strip()
            if "not found" in after_arrow:
                continue
            # strip trailing address "(0x...)"
            path_str = re.sub(r"\s*\(0x[0-9a-fA-F]+\)\s*$", "", after_arrow).strip()
            if path_str:
                p = Path(path_str).resolve()
                if p.exists():
                    deps.append(p)
        else:
            # Direct path line with no '=>':
            # e.g. "    /lib64/ld-linux-x86-64.so.2 (0x...)"
            stripped = line.strip()
            if not stripped:
                continue
            path_str = re.sub(r"\s*\(0x[0-9a-fA-F]+\)\s*$", "", stripped).strip()
            if path_str:
                p = Path(path_str).resolve()
                if p.exists():
                    deps.append(p)

    return deps


def install_binary(
    cfg: SandboxConfig,
    username: str,
    binary: Path,
    dest: str = "",
    dry_run: bool = False,
) -> None:
    """
    Copy binary + ldd dependencies into homes/<user>/sandbox-root/.
    Register --bind mounts in extra-mounts. Regenerate launcher.

    dest: optional destination path inside sandbox (default: same as binary path)
    """
    # 1. Validate binary
    if not binary.exists():
        raise SandboxError(f"binary not found: {binary}")
    if not binary.is_file():
        raise SandboxError(f"not a file: {binary}")
    if not os.access(binary, os.X_OK):
        raise SandboxError(f"binary is not executable: {binary}")

    # 2. Determine sandbox-root
    sandbox_root = cfg.user_home(username) / "sandbox-root"

    # 3. Collect ldd deps
    deps = collect_ldd_deps(binary)

    # 4. Determine dest path
    dest_path = dest if dest else str(binary)

    # Helper: copy one file into sandbox_root and return the MountEntry
    def _stage(abs_path: Path, dest_abs: str) -> MountEntry:
        rel = dest_abs.lstrip("/")
        target = (sandbox_root / rel).resolve()
        if not target.is_relative_to(sandbox_root.resolve()):
            raise SandboxError(f"dest {dest_abs!r} would escape sandbox root — refusing")
        if dry_run:
            print(f"[dry-run] would copy {abs_path} -> {target}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(abs_path, target)
        return MountEntry(
            kind="--bind",
            source=str(target),
            dest=dest_abs if dest_abs.startswith("/") else "/" + dest_abs,
        )

    new_mounts: list[MountEntry] = []

    # 5. Stage the binary
    new_mounts.append(_stage(binary, dest_path))

    # 6. Stage each dependency (preserve original absolute path as dest)
    for dep in deps:
        new_mounts.append(_stage(dep, dep.as_posix()))

    # 7-8. Merge with existing mounts (deduplicate by source+dest) and write back
    existing = read_extra_mounts(cfg.users_dir, username)

    seen: set[tuple[str, str]] = {(m.source, m.dest) for m in existing}
    merged = list(existing)
    for m in new_mounts:
        key = (m.source, m.dest)
        if key not in seen:
            seen.add(key)
            merged.append(m)

    if dry_run:
        for m in new_mounts:
            print(f"[dry-run] would register mount: {m.kind} {m.source} {m.dest}")
        print(f"[dry-run] would regenerate launcher for {username}")
    else:
        write_extra_mounts(cfg.users_dir, username, merged)
        generate_launcher(cfg.launcher_dir, cfg.users_dir, username)

