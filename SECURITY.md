# Security notes

## What this system does and does not provide

Sandboxed users are placed into a [bubblewrap](https://github.com/containers/bubblewrap) (bwrap) container launched via `sandbox-ctl user run --user <name>`. bwrap provides **filesystem and namespace isolation** using unprivileged Linux namespaces. It is not a full container runtime and does not provide kernel-level syscall filtering.

No real OS user accounts are created. Isolation is provided entirely by bwrap bind mounts and user namespaces — not by Unix file ownership.

### What is isolated

| Namespace | Flag | Effect |
|-----------|------|--------|
| User | `--unshare-user` | Creates a user namespace; caller's UID maps to internal UID inside sandbox |
| Mount | implicit | User sees only the bwrap-constructed filesystem view |
| IPC | `--unshare-ipc` | Isolated System V IPC and POSIX message queues |
| UTS | `--unshare-uts` | Separate hostname (`sandbox-<user>` by default) |
| Cgroup | `--unshare-cgroup` | Isolated cgroup view |

PID namespace is **not** unshared. The sandbox sees host PIDs via `--proc /proc`. This is intentional: it enables `jobctl` (the in-sandbox background job manager) to identify the user's own processes via `/proc/<pid>/status` (world-readable), and allows the host to write `~/.jobctl_pids` at login for cross-session job tracking. The sandboxed user cannot read `/proc/<pid>/environ` for processes outside their user namespace (ptrace restriction), so they cannot inspect other users' environment variables.

`--new-session` calls `setsid()`, preventing the sandbox from accessing the parent's controlling terminal. `--die-with-parent` ensures the sandbox exits if the managing process dies.

### What is NOT isolated

**Network (configurable).** By default the sandbox does not use `--unshare-net` and sandboxed users have full network access. Two isolation modes can be selected via `--network` when creating a user:

| Mode | Effect |
|------|--------|
| `full` (default) | Unrestricted network access |
| `loopback` | Private network namespace; only `lo` is configured. No external connectivity. |
| `none` | Private network namespace with no interfaces. |

`loopback` and `none` both add `--unshare-net` to the bwrap invocation. In `loopback` mode the sandbox shell runs `ip link set lo up` before exec to enable the loopback interface.

**Syscalls.** There is no seccomp filter applied. Any syscall the kernel permits for an unprivileged process is available inside the sandbox. A kernel exploit or sufficiently privileged syscall abuse can escape the sandbox entirely. bwrap is appropriate for containing trusted-but-limited users, not for isolating actively malicious code.

**Devices.** `/dev` is a bwrap-managed devtmpfs (not the host `/dev`), which limits direct device access. However, no explicit device whitelist is enforced.

---

## User isolation model

Sandbox users do not have real OS accounts. Isolation works as follows:

- Each sandbox user is assigned a unique internal UID/GID (allocated from a local counter starting at 1001, stored in `users/<user>/ids`)
- `--unshare-user --uid N --gid N` maps the calling user's real UID to UID N inside the sandbox; `id` inside shows e.g. `uid=1001(alice) gid=1001(alice)`
- A synthetic `/etc/passwd` and `/etc/group` are injected via file descriptors; the real host `/etc/passwd` is never exposed unless `--sys-dirs` is used
- Sandbox A cannot read sandbox B's home directory because only each user's own `users/<user>/<user>.home/` is bind-mounted into their sandbox — not by Unix permissions, but by what bwrap exposes

Two different sandbox users running as the same real UID on the host (which is normal here — the host admin runs all sandboxes) are separated only by what bwrap bind-mounts. The launcher script controls which paths are visible.

---

## File permission model

### Launcher and state files

```
low_priv_user_dirs/launchers/bwrap-shell-<user>   owner: admin user  755
low_priv_user_dirs/users/<user>/                   owner: admin user  755
low_priv_user_dirs/users/<user>/base               owner: admin user  600
low_priv_user_dirs/users/<user>/extra-mounts       owner: admin user  600
low_priv_user_dirs/users/<user>/ids                owner: admin user  600
low_priv_user_dirs/users/<user>/<user>.home/       owner: admin user  700
```

The `extra-mounts` file is critical: it contains the bwrap bind-mount arguments for the launcher. If a sandboxed user could write to `extra-mounts`, they could inject arbitrary bwrap flags (removing namespace flags, adding bind mounts) and escape the sandbox on next run.

Sandboxed users have no shell on the host (no OS account, no login shell), so they have no path to the project directory. The admin-owned file permissions are defence-in-depth against accidental permission relaxation on the `low_priv_user_dirs/` tree.

### The host admin account and the project directory

`sandbox-ctl` is owned by the host admin and runs without elevated privileges. If the host admin's account is compromised, an attacker can modify the launcher scripts or state files directly. This is inherent to any system where one user manages sandboxes for others.

Sandboxed home directories (`low_priv_user_dirs/users/<user>/<user>.home/`) are owned by the admin account and are not accessible to other sandboxed users.

---

## The `--sys-dirs` flag

By default, `/etc` is not bind-mounted. Instead, `sandbox-ctl` injects:
- A synthetic `/etc/passwd` (only the sandbox user and root)
- A synthetic `/etc/group` (user's primary group and any mounted shared groups)
- `/etc/resolv.conf` from the host (for DNS)
- Selected files from `/etc` that are commonly needed: `hosts`, `shells`, `ssl`, `ca-certificates`, `localtime`, `timezone`

When a user is created with `--sys-dirs`, the real `/etc` and `/run` are bind-mounted read-only instead. This is required for full NSS support and other host-configuration-dependent features.

The trade-off: with `--sys-dirs`, the sandboxed user can read `/etc/passwd` (world-readable by design on Linux), `/etc/hosts`, `/etc/resolv.conf`, and other non-sensitive configuration. Files with restricted permissions — `/etc/shadow` (640 root:shadow), `/etc/sudoers` (440 root:root) — remain inaccessible.

Avoid `--sys-dirs` unless the user's workload genuinely requires it.

---

## Resource limits

### ulimits (`--max-procs`, `--max-fsize`, `--max-nofile`)

Soft limits are applied via `ulimit -S` in the launcher immediately before `exec bwrap`.

| Flag | ulimit | Unit |
|------|--------|------|
| `--max-procs <n>` | `-u` | number of processes |
| `--max-fsize <n>` | `-f` | MB (converted to 512-byte blocks internally) |
| `--max-nofile <n>` | `-n` | open file descriptors |

These are soft limits only. They do not prevent the user from consuming CPU time or memory — use cgroup limits for those.

### cgroup limits (`--cgroup-mem`, `--cgroup-cpu`)

When configured, the launcher wraps the `bwrap` invocation with `systemd-run --user --scope`, setting `MemoryMax` and/or `CPUQuota` on the transient scope unit. These are **hard** limits enforced by the kernel cgroup subsystem and cannot be bypassed by the sandboxed user.

**Requirement:** a systemd user session must be active (`XDG_RUNTIME_DIR` or `DBUS_SESSION_BUS_ADDRESS` must be set and `systemd-run` must be available). If the session is absent and cgroup limits are configured, the launcher prints a warning and prompts before falling back to ulimits-only.

---

## Overlay (shadow) mounts

When a path is shadowed via a profile, an overlay mount is constructed:

- **Lower layer**: the host path (read-only, as seen inside the sandbox)
- **Upper layer**: `$HOME/shadow<path>/` — a directory owned by the sandboxed user

The upper layer lives inside the user's home directory on the host. The admin can read and modify those files directly on the host. This is expected: the shadow mechanism lets users accumulate writes without touching the host, not to hide those writes from the admin.

---

## Kernel exploit risk

Because no seccomp filter is in place, a sandboxed user who can execute a kernel exploit can escape to the host. This is a fundamental limitation of namespace-based sandboxing without syscall filtering.

Mitigations outside the scope of this project:
- Apply a seccomp profile (e.g. via a bwrap `--seccomp` argument with a compiled filter)
- Keep the host kernel patched
- Use `--no-usr` for maximally restrictive sandboxes where the user's workload allows it — this limits the tools available to an attacker inside the sandbox

---

## Summary of trust boundaries

| Actor | Trusts | Does not trust |
|-------|--------|----------------|
| Sandboxed user inside bwrap | Their own home dir; explicitly mounted paths | Host filesystem beyond what bwrap exposes |
| Sandboxed user on host | No path here — no OS account, no login shell | — |
| Host admin | Full project dir and `low_priv_user_dirs/` (owns all of it) | Other host users |

The intended entry path is `sandbox-ctl user run --user <name>`, which execs the bwrap launcher directly. There is no normal path by which a sandboxed user obtains a raw host shell.
