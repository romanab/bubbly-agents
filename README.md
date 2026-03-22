# bubbly-agents

### Setup for agents in bubblewrapped environments (coded with Claude Code)

![Bubbly 'Gents logo](images/bubbly-gents-logo.png)

---

Tools for creating and managing **bubblewrap-sandboxed user accounts** on Linux. Each user's sandbox is launched via `sandbox-ctl user run --user <name>` — a generated bwrap launcher script that constructs a private filesystem namespace with controlled access to the host. An optional TUI is available for managing environments via `sandbox-tui`.

Designed for giving untrusted or semi-trusted agents access to a machine without exposing the full system. No root required for management or launch.

---

## How It Works

`sandbox-ctl user create` writes state files and generates a launcher script (`low_priv_user_dirs/launchers/bwrap-shell-<username>`). No OS user accounts are created. When run, the launcher executes `bwrap` to construct a private view of the filesystem:

- `--unshare-user` creates a user namespace: the calling user's UID is mapped to a unique internal UID inside the sandbox, so `id` shows e.g. `uid=1001(alice) gid=1001(alice)`
- Their home directory lives at `low_priv_user_dirs/homes/<username>/` on the host
- Synthetic `/etc/passwd` and `/etc/group` are injected via file descriptors — no real entries in host system files
- `/usr`, `/lib*`, and other system paths can be included or excluded via profile flags
- Additional host directories can be exposed read-only via `--extra-path`
- Shared group directories are bind-mounted into members' sandboxes and accessible via `mount-group <group>` inside the sandbox

Per-user configuration is stored in `low_priv_user_dirs/state/<username>/`. The entire runtime tree lives under `low_priv_user_dirs/` and moves with the project folder.

---

## `sandbox-ctl` — Python CLI

### Installation

#### 1. Create a dedicated Linux account to hold the agents and their environments

Create a separate Linux account with a high UID. Using a dedicated account keeps sandbox state isolated from your personal home directory.

```bash
# As root (or with sudo):
useradd -u 60000 -m -s /bin/bash agents
```

#### 2. Install Homebrew for Linux

Homebrew installs to `/home/linuxbrew/.linuxbrew/`. Follow the instructions at [brew.sh](https://brew.sh). This step requires sudo so run it from your regular account.

#### 3. Install `uv` and `direnv`

```bash
brew install uv direnv
```

#### All subsequent steps run from the `agents` account.

Login to the `agents` account and hook the project's shell config into `~/.bashrc`. After cloning (step 4), run:

```bash
echo 'source ~/bubbly-agents/bubbly-agents-bashrc' >> ~/.bashrc
source ~/.bashrc
```

> If you cloned to a different path, update the `source` line and the `cd` line near the top of `bubbly-agents-bashrc` to match.

`bubbly-agents-bashrc` sets up Homebrew, direnv, a venv prompt indicator, and a tmux session check on every login (offers to attach to an existing session, or start a new one if none are running).

#### 4. Clone the project and install

```bash
git clone https://github.com/romanab/bubbly-agents.git
cd bubbly-agents
uv venv
direnv allow        # auto-activates .venv on every subsequent cd
uv pip install -e .
```

`uv venv` creates `.venv/` inside the project directory. With direnv, `sandbox-ctl` and `sandbox-tui` are available immediately on entering the project directory without manually running `source .venv/bin/activate`.

---

### Quick start

```bash
# Create a shared group
sandbox-ctl group create --group devs

# Create a user in that group
sandbox-ctl user create --user alice --extra-groups devs

# Launch the sandbox
sandbox-ctl user run --user alice

# Inside sandbox: access the shared group directory
mount-group devs
ls ~/devs/

# Back on host: remove user when done
sandbox-ctl user delete --user alice
```

### Command reference

#### `sandbox-ctl user`

```
sandbox-ctl user list
sandbox-ctl user create --user NAME [OPTIONS] [--dry-run]
sandbox-ctl user run    --user NAME
sandbox-ctl user audit  --user NAME
sandbox-ctl user delete --user NAME [--keep-home] [--force] [--dry-run]
sandbox-ctl user profile      --profile NAME --user NAME [--dry-run]
sandbox-ctl user profile-list
sandbox-ctl user install --sandbox NAME --binary PATH [--dest PATH] [--dry-run]
```

`user create` options:

| Option | Description |
|--------|-------------|
| `--user NAME` | **Required.** Username to create. |
| `--extra-groups LIST` | Comma-separated supplementary groups. |
| `--extra-path PATH` | Expose a host directory read-only inside the sandbox (repeatable). |
| `--comment TEXT` | GECOS comment (stored in synthetic /etc/passwd). |
| `--no-usr` | Omit `/usr` from the sandbox. |
| `--sys-dirs` | Mount host `/etc` and `/run` read-only. **Avoid for normal use** — breaks username resolution inside the sandbox because the host `/etc/passwd` has no sandbox users. Use only when full host NSS is required. DNS and basic `/etc` files work without this flag. |
| `--fake-sudo` | Inject a `sudo` shim that execs the command directly (no privilege gain). |
| `--network full\|loopback\|none` | Network mode (default: `full`). |
| `--max-procs N` | Max processes (ulimit -u). |
| `--max-fsize MB` | Max file size in MB (ulimit -f). |
| `--max-nofile N` | Max open file descriptors (ulimit -n). |
| `--cgroup-mem SIZE` | Hard memory cap (e.g. `512M`). |
| `--cgroup-cpu PCT` | CPU quota (e.g. `50%`). |
| `--dry-run` | Print actions only; make no changes. |

#### `sandbox-ctl group`

```
sandbox-ctl group list
sandbox-ctl group create --group NAME [--mode MODE] [--dry-run]
sandbox-ctl group delete --group NAME [--dry-run]
sandbox-ctl group chmod  --group NAME --mode MODE [--dry-run]
```

#### `sandbox-ctl membership`

```
sandbox-ctl membership add    --user NAME --groups csv [--dry-run]
sandbox-ctl membership remove --user NAME --groups csv [--dry-run]
```

### Configuration

`sandbox-ctl` reads path configuration from environment variables:

| Variable | Default |
|----------|---------|
| `SANDBOX_DATA_DIR` | `<project>/low_priv_user_dirs` |
| `SANDBOX_PROJECT_ROOT` | directory containing `pyproject.toml` |

All derived paths (`launchers/`, `state/`, `homes/`, `groups/`) are resolved from `SANDBOX_DATA_DIR`.

---

## Directory Layout

```
<project>/
  pyproject.toml               Python package config (sandbox-ctl entry point)
  sandbox/                     Python package
    config.py                  Path config + exceptions
    models.py                  UserConfig, MountEntry, Profile dataclasses
    state.py                   Per-user state file I/O
    launcher.py                bwrap launcher generation
    ids.py                     UID/GID allocation (local counter, no /etc/login.defs)
    users.py                   User operations
    groups.py                  Group operations
    membership.py              Group membership
    installs.py                Binary install with ldd deps
    profiles.py                Profile support
    cli/                       Click CLI (sandbox-ctl)
    tests/                     Unit tests (pytest)
  profiles/                    Profile templates
  low_priv_user_dirs/          owner: calling user
    launchers/                 bwrap-shell-<username> launcher scripts
    state/                     <username>/{base,extra-mounts,ids,profile}
    homes/                     sandbox home directories
      <username>/              mode 0700
    groups/                    shared group directories
      <groupname>/             container directory
        <groupname>.gid        internal GID
        <groupname>.members    member list (one username per line)
        <groupname>.group-dir/ actual shared directory (bind-mounted into sandboxes)
```

---

## Requirements

- Linux with `bwrap` (bubblewrap) installed and user namespaces enabled
- **Python CLI + TUI**: Python 3.10+, `click`, `textual` (`pip install -e .`)

---

## TUI (Interactive Menu)

`sandbox-tui` is a Python terminal UI (Textual). Launch it with:

```bash
sandbox-tui
```

Three tabs:

- **Users** — list, create (with optional profile), install binaries, manage group membership, delete
- **Groups** — list, create, chmod, delete
- **Profiles** — list, create from scratch or by cloning, delete

Key bindings are shown in the footer. Press `r` to refresh, `q` to quit.

---

## Profiles

Profiles live in `profiles/<name>/` and contain a `profile.conf` plus optional dotfiles.

### `profile.conf` reference

```ini
[meta]
description = Human-readable description

[user]
comment     = GECOS comment for the account
no-usr      = false    # Omit /usr from the sandbox
fake-sudo   = false    # Inject a no-privilege sudo shim
network     = full     # full | loopback | none  (default: full)
# max-procs  =         # Max processes (ulimit -u)
# max-fsize  =         # Max file size in MB (ulimit -f)
# max-nofile =         # Max open file descriptors (ulimit -n)
# cgroup-mem =         # Hard memory cap, e.g. 512M (systemd cgroup)
# cgroup-cpu =         # CPU quota, e.g. 50% (systemd cgroup)

[sandbox]
# bind = /host/path:/sandbox/path
hostname    =          # Custom hostname (default: sandbox-<username>)

[shadow]
# Paths to overlay with a per-user writable layer.
# Reads see host content; writes go to $HOME/shadow<path>/.
# /usr/local

[install]
# Binaries to install with all ldd deps.
# /usr/bin/curl
# /usr/bin/jq:/usr/local/bin/jq

[dotfiles]
# Files from profiles/<name>/dotfiles/ copied to $HOME/.
# .bashrc

[scripts]
# post_setup = post_setup.sh   (run as root after creation)
# on_enter   = on_enter.sh     (sourced inside sandbox on login)
```

### Applying a profile

```bash
# List available profiles
sandbox-ctl user profile-list

# Apply a profile when creating a user
sandbox-ctl user profile --profile devtools --user alice
```

In the TUI, profile selection is available directly in the **New User** form (Users tab → `n`).

---

## Shared Groups

Groups provide a shared directory that is bind-mounted into each member's sandbox.

```bash
# Create a group with default permissions (owner rwx, group rwx, other none)
sandbox-ctl group create --group devs

# Add a user as a member (regenerates their launcher)
sandbox-ctl membership add --user alice --groups devs

# Inside the sandbox, create a symlink to the group directory
mount-group devs       # creates ~/devs -> <group-dir>
ls ~/devs/

# Remove the symlink
unmount-group devs

# Change shared directory permissions
sandbox-ctl group chmod --group devs --mode u=rwx,g=rx,o=
```

Members listed in a group can use `mount-group <name>` to access it. The `mount-group` and `unmount-group` scripts are injected into `/usr/local/bin/` inside the sandbox.

---

## Keeping Sandboxes Alive Across Disconnections

Sandbox processes keep running as long as the bwrap launcher process is alive. The recommended approach is to run a single **host tmux session** under the `agents` account, with one window per sandbox:

```bash
# Start (or name) the host tmux session
tmux new-session -s sandboxes

# Open a window for each sandbox user
sandbox-ctl user run --user alice    # window 1
# Ctrl-B c  (new window)
sandbox-ctl user run --user agent1   # window 2

# Detach: Ctrl-B d
# All sandboxes keep running — bwrap is a child of the tmux server,
# which stays alive after detach.

# Reattach later (or via the auto-attach prompt on login):
tmux attach -t sandboxes
```

The `~/.bashrc` snippet in the Installation section detects running tmux sessions at login and offers to re-attach automatically.

### Surviving full account logout

By default, systemd kills all processes owned by a user when their last session ends. To keep sandboxes running even after a full logout, enable **linger** once:

```bash
# As root:
loginctl enable-linger agents
```

With linger enabled, the host tmux server (and all bwrap sandboxes inside it) survive logout and are available on the next login.

---

## Terminal Behaviour

### "no job control" warning

When entering a sandbox, bash may print:

```
bash: cannot set terminal process group: Inappropriate ioctl for device
bash: no job control in this shell
```

This is expected. The launcher passes `--new-session` to bwrap, which calls `setsid()` to create a new session for security (prevents sandbox escape via `TIOCSTI`). The downside is that bash starts without a controlling terminal, so job control (`Ctrl-Z`, `fg`, `bg`) is unavailable. All other shell functionality works normally.

### tmux works inside the sandbox

tmux creates its own pseudo-terminals via `/dev/ptmx` and manages its own sessions, so it is unaffected by the missing controlling terminal. The launcher already provides everything tmux needs:

- `--dev /dev` — supplies `/dev/ptmx`
- `--tmpfs /tmp` — supplies the tmux socket directory

---

## Typical Workflow

```bash
# 1. Create a shared group
sandbox-ctl group create --group devs

# 2. Create a user in that group
sandbox-ctl user create --user alice --extra-groups devs

# 3. Or from a profile
sandbox-ctl user profile --profile devtools --user alice

# 4. Install additional tools later
sandbox-ctl user install --sandbox alice --binary /usr/bin/jq

# 5. Manage group membership later
sandbox-ctl membership add --user alice --groups devs

# 6. List all sandboxed users and groups
sandbox-ctl user list
sandbox-ctl group list

# 7. Enter the sandbox (inside host tmux for persistence)
sandbox-ctl user run --user alice

# 8. Remove a user when done
sandbox-ctl user delete --user alice

# 9. Remove a group when done
sandbox-ctl group delete --group devs
```
