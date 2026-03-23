import shlex
from pathlib import Path

from sandbox.state import read_base, read_extra_mounts, read_ids


def _make_mount_group_script(groups_dir: str) -> str:
    return (
        "#!/bin/sh\n"
        'GROUP="$1"\n'
        'if [ -z "$GROUP" ]; then\n'
        '    echo "Usage: mount-group <group>" >&2\n'
        "    exit 1\n"
        "fi\n"
        f'GROUPS_DIR={shlex.quote(groups_dir)}\n'
        'GROUP_DIR="$GROUPS_DIR/$GROUP/$GROUP.group-dir"\n'
        'if [ ! -d "$GROUP_DIR" ]; then\n'
        '    echo "Error: group \'$GROUP\' not available (not a member or directory not mounted)" >&2\n'
        "    exit 1\n"
        "fi\n"
        'ln -sfn "$GROUP_DIR" "$HOME/$GROUP" && echo "Mounted ~/$GROUP -> $GROUP_DIR"\n'
    )

_JOBCTL_SCRIPT = (
    "#!/bin/sh\n"
    # PIDs written by the host launcher (sandbox-ctl user run / TUI) before exec'ing bwrap.
    # The host can read /proc/<pid>/environ without ptrace restrictions; the sandbox cannot.
    "_PIDS_FILE=$HOME/.jobctl_pids\n"
    "_me=$(grep '^Uid:' /proc/self/status 2>/dev/null | cut -f2)\n"
    # Enumerate alive jobs: file-based (cross-session) first, then current-session
    # children of the calling shell. Calls back with: _job_cb N PID CMD ST
    "_each_job() {\n"
    "  _n=0\n"
    '  if [ -s "$_PIDS_FILE" ]; then\n'
    '    while IFS= read -r _p; do\n'
    '      [ -z "$_p" ] && continue\n'
    '      [ -d "/proc/$_p" ] || continue\n'
    '      _c=$(tr "\\0" " " < "/proc/$_p/cmdline" 2>/dev/null | cut -c1-60)\n'
    '      [ -z "$_c" ] && continue\n'
    '      _t=$(grep "^State:" "/proc/$_p/status" 2>/dev/null | cut -f2 | cut -c1)\n'
    '      _n=$((_n+1)); _job_cb "$_n" "$_p" "$_c" "${_t:-?}"\n'
    '    done < "$_PIDS_FILE"\n'
    '  fi\n'
    '  for _s in /proc/[0-9]*/status; do\n'
    '    _p="${_s%/status}"; _p="${_p##*/proc/}"\n'
    '    [ "$_p" = "$$" ] && continue\n'
    '    grep -qxF "$_p" "$_PIDS_FILE" 2>/dev/null && continue\n'
    '    _pp=$(grep "^PPid:" "$_s" 2>/dev/null | cut -f2)\n'
    '    [ "$_pp" = "$PPID" ] || continue\n'
    '    _c=$(tr "\\0" " " < "/proc/$_p/cmdline" 2>/dev/null | cut -c1-60)\n'
    '    [ -z "$_c" ] && continue\n'
    '    _t=$(grep "^State:" "$_s" 2>/dev/null | cut -f2 | cut -c1)\n'
    '    _n=$((_n+1)); _job_cb "$_n" "$_p" "$_c" "${_t:-?}"\n'
    '  done\n'
    "}\n"
    "_jlist() {\n"
    '  printf "[N]  %-8s %-1s  %s\\n" "PID" "S" "COMMAND"\n'
    '  printf -- "---  --------  -  -------\\n"\n'
    '  _found=0\n'
    '  _job_cb() { printf "[%s]  %-8s %-1s  %s\\n" "$1" "$2" "$4" "$3"; _found=1; }\n'
    '  _each_job\n'
    '  [ "$_found" -eq 0 ] && echo "No background jobs."\n'
    "}\n"
    "_nth_job() {\n"
    '  _target="$1"; _result=""\n'
    '  _job_cb() { [ "$1" = "$_target" ] && _result="$2"; }\n'
    '  _each_job\n'
    '  echo "$_result"\n'
    "}\n"
    "_jkill() {\n"
    '  _sig="TERM"\n'
    '  case "${1:-}" in\n'
    '    -*) _sig="${1#-}"; shift ;;\n'
    '  esac\n'
    '  _arg="${1:-}"\n'
    '  [ -z "$_arg" ] && { echo "Usage: jobctl kill [-sig] <%N|pid>" >&2; return 1; }\n'
    '  case "$_arg" in\n'
    '    %*)\n'
    '      _n="${_arg#%}"\n'
    '      _pid=$(_nth_job "$_n")\n'
    '      [ -z "$_pid" ] && { echo "Error: no job %$_n" >&2; return 1; }\n'
    '      ;;\n'
    '    *) _pid="$_arg" ;;\n'
    '  esac\n'
    '  _uid=$(grep "^Uid:" "/proc/$_pid/status" 2>/dev/null | cut -f2)\n'
    '  [ -n "$_uid" ] && [ "$_uid" = "$_me" ] \\\n'
    '    || { echo "Error: PID $_pid is not your process" >&2; return 1; }\n'
    '  kill -"$_sig" "$_pid" && echo "Sent SIG$_sig to $_pid"\n'
    "}\n"
    "_jkillall() {\n"
    '  _count=0\n'
    '  _job_cb() {\n'
    '    kill -TERM "$2" 2>/dev/null && echo "Sent SIGTERM to $2"\n'
    '    _count=$((_count+1))\n'
    '  }\n'
    '  _each_job\n'
    '  [ "$_count" -eq 0 ] && echo "No background jobs."\n'
    "}\n"
    'case "${1:-list}" in\n'
    '  list)    _jlist ;;\n'
    '  kill)    shift; _jkill "$@" ;;\n'
    '  killall) _jkillall ;;\n'
    '  help|-h|--help)\n'
    '    echo "Usage: jobctl [list|kill <pid> [sig]|killall]"\n'
    '    echo "  list     List background jobs for this sandbox user (default)"\n'
    '    echo "  kill [-sig] %N   Signal job N (e.g. kill -KILL %1)"\n'
    '    echo "  kill [-sig] pid  Signal by PID"\n'
    '    echo "  killall  SIGTERM all listed background jobs"\n'
    "    ;;\n"
    '  *) echo "Unknown command: $1" >&2; exit 1 ;;\n'
    "esac\n"
)

_UNMOUNT_GROUP_SCRIPT = (
    "#!/bin/sh\n"
    'GROUP="$1"\n'
    'if [ -z "$GROUP" ]; then\n'
    '    echo "Usage: unmount-group <group>" >&2\n'
    "    exit 1\n"
    "fi\n"
    'LINK="$HOME/$GROUP"\n'
    'if [ ! -L "$LINK" ]; then\n'
    '    echo "Error: ~/$GROUP is not a symlink (not mounted?)" >&2\n'
    "    exit 1\n"
    "fi\n"
    'rm "$LINK" && echo "Unmounted ~/$GROUP"\n'
)


def generate_launcher(
    launcher_dir: Path,
    state_dir: Path,
    username: str,
    dry_run: bool = False,
) -> Path:
    """
    Read base + extra-mounts state for username, generate bwrap launcher script.
    Returns path to launcher file.
    Raises ValueError if USER_HOME is not set in base state.
    """
    base = read_base(state_dir, username)
    mounts = read_extra_mounts(state_dir, username)
    ids = read_ids(state_dir, username)
    if ids is None:
        raise ValueError(f"INTERNAL_UID/GID not set for user '{username}'")
    internal_uid, internal_gid = ids

    no_usr = base.get("NO_USR", "0") == "1"
    sys_dirs = base.get("SYS_DIRS", "0") == "1"
    fake_sudo = base.get("FAKE_SUDO", "0") == "1"
    user_home = base.get("USER_HOME", "")
    if not user_home:
        raise ValueError(f"USER_HOME is not set in base state for user '{username}'")
    hostname = base.get("HOSTNAME", f"sandbox-{username}")
    network = base.get("NETWORK", "full")
    max_procs = base.get("MAX_PROCS", "")
    max_fsize = base.get("MAX_FSIZE", "")
    max_nofile = base.get("MAX_NOFILE", "")
    cgroup_mem = base.get("CGROUP_MEM", "")
    cgroup_cpu = base.get("CGROUP_CPU", "")

    # Detect group mounts — user has group scripts only when /usr is present
    groups_dir = state_dir.parent / "groups"
    has_groups = not no_usr and any(
        m.source.startswith(str(groups_dir) + "/") for m in mounts
    )

    # Build EXTRA_MOUNT_ARGS block
    if mounts:
        mount_lines = []
        for m in mounts:
            mount_lines.append(f"  {m.kind}\n  {m.source}\n  {m.dest}")
        extra_mount_args = "EXTRA_MOUNT_ARGS=(\n" + "\n".join(mount_lines) + "\n)\n"
    else:
        extra_mount_args = "EXTRA_MOUNT_ARGS=(\n)\n"

    # Build optional sections
    unshare_net_line = "  --unshare-net \\\n" if network != "full" else ""

    usr_bind_line = "  --ro-bind /usr /usr \\\n" if not no_usr else ""

    # --- Dynamic FD assignment ---
    # FD 3: resolv.conf (when not sys_dirs)
    # FD 4: passwd (when not sys_dirs)
    # FD 5: group (when not sys_dirs)
    # FD N: sudo shim (when fake_sudo and not no_usr)
    # FD N, N+1: mount-group / unmount-group scripts (when has_groups)
    # FD N: sandbox-stop script (when persistent and not no_usr)
    next_fd = 3

    if sys_dirs:
        etc_run_lines = (
            "  --ro-bind /etc /etc \\\n"
            "  --ro-bind /run /run \\\n"
        )
        resolv_redir = ""
    else:
        resolv_fd_num = next_fd
        next_fd += 1

        # Allocate FDs for synthetic passwd and group
        passwd_fd_num = next_fd
        next_fd += 1
        group_fd_num = next_fd
        next_fd += 1

        etc_run_lines = (
            "  --dir /etc \\\n"
            f"  --file {resolv_fd_num} /etc/resolv.conf \\\n"
            f"  --file {passwd_fd_num} /etc/passwd \\\n"
            f"  --file {group_fd_num} /etc/group \\\n"
            '  "${ETC_ARGS[@]}" \\\n'
        )
        resolv_redir = f" {resolv_fd_num}< /etc/resolv.conf"

        # Build synthetic passwd content
        passwd_content = (
            f"{username}:x:{internal_uid}:{internal_gid}::{user_home}:/bin/bash\n"
            "root:x:0:0:root:/root:/bin/sh\n"
        )

        # Build synthetic group content
        group_content = f"{username}:x:{internal_gid}:\n"
        for mount in mounts:
            if mount.source.startswith(str(groups_dir) + "/"):
                grp_name = Path(mount.source).parent.name
                gid_file = groups_dir / grp_name / f"{grp_name}.gid"
                if gid_file.exists():
                    gid_val = gid_file.read_text().strip()
                    group_content += f"{grp_name}:x:{gid_val}:\n"

    # /usr/local/bin tmpfs + injected scripts
    # FD redirections all go on the command line; heredoc bodies follow in order,
    # each terminator on its own line (bash requirement).
    local_bin_lines = ""
    fd_redirects = ""   # appended to command line alongside resolv_redir
    heredoc_bodies = "" # appended after command line, one heredoc body per entry

    if not sys_dirs:
        fd_redirects += f" {passwd_fd_num}<<'_PASSWD' {group_fd_num}<<'_GROUP'"
        heredoc_bodies += f"\n{passwd_content}_PASSWD"
        heredoc_bodies += f"\n{group_content}_GROUP"

    need_local_bin = not no_usr
    if need_local_bin:
        local_bin_lines = "  --tmpfs /usr/local/bin \\\n"

        # Always inject jobctl
        jobctl_fd_num = next_fd
        next_fd += 1
        local_bin_lines += f"  --file {jobctl_fd_num} /usr/local/bin/jobctl \\\n"
        local_bin_lines += "  --chmod 0755 /usr/local/bin/jobctl \\\n"
        fd_redirects += f" {jobctl_fd_num}<<'_JOBCTL'"
        heredoc_bodies += f"\n{_JOBCTL_SCRIPT}_JOBCTL"

        if fake_sudo:
            sudo_fd_num = next_fd
            next_fd += 1
            local_bin_lines += f"  --file {sudo_fd_num} /usr/local/bin/sudo \\\n"
            local_bin_lines += "  --chmod 0755 /usr/local/bin/sudo \\\n"
            fd_redirects += f" {sudo_fd_num}<<'_SUDO'"
            heredoc_bodies += f"\n#!/bin/sh\nexec \"$@\"\n_SUDO"

        if has_groups:
            mount_fd_num = next_fd
            next_fd += 1
            unmount_fd_num = next_fd
            next_fd += 1
            local_bin_lines += f"  --file {mount_fd_num} /usr/local/bin/mount-group \\\n"
            local_bin_lines += "  --chmod 0755 /usr/local/bin/mount-group \\\n"
            local_bin_lines += f"  --file {unmount_fd_num} /usr/local/bin/unmount-group \\\n"
            local_bin_lines += "  --chmod 0755 /usr/local/bin/unmount-group \\\n"
            fd_redirects += f" {mount_fd_num}<<'_MOUNT_GROUP' {unmount_fd_num}<<'_UNMOUNT_GROUP'"
            # mount_group_script ends with \n so _MOUNT_GROUP lands on its own line
            mount_group_script = _make_mount_group_script(str(groups_dir))
            heredoc_bodies += f"\n{mount_group_script}_MOUNT_GROUP"
            heredoc_bodies += f"\n{_UNMOUNT_GROUP_SCRIPT}_UNMOUNT_GROUP"


    # Build the bwrap flags block
    session_flag = "  --new-session --die-with-parent \\\n"

    bwrap_flags = (
        "  --unshare-user \\\n"
        f"  --uid {internal_uid} \\\n"
        f"  --gid {internal_gid} \\\n"
        "  --unshare-ipc --unshare-uts --unshare-cgroup \\\n"
        f"{unshare_net_line}"
        "  --proc /proc \\\n"
        "  --dev /dev \\\n"
        "  --tmpfs /tmp \\\n"
        '  --bind "${USER_HOME}" "${USER_HOME}" \\\n'
        '  --setenv HOME "${USER_HOME}" \\\n'
        '  --chdir "${USER_HOME}" \\\n'
        f"  --setenv PS1 '({username}@\\w:\\s-\\v)\\$ ' \\\n"
        f"  --setenv PROMPT_COMMAND '[ -n \"$TMUX\" ] && printf \"\\033k%s\\033\\\\\" \"{username}\"' \\\n"
        '  --hostname "${BWRAP_HOSTNAME}" \\\n'
        f"{session_flag}"
        "  --ro-bind-try /bin /bin \\\n"
        "  --ro-bind-try /sbin /sbin \\\n"
        "  --ro-bind-try /lib /lib \\\n"
        "  --ro-bind-try /lib64 /lib64 \\\n"
        "  --ro-bind-try /lib32 /lib32 \\\n"
        "  --ro-bind-try /libx32 /libx32 \\\n"
        f"{usr_bind_line}"
        f"{local_bin_lines}"
        f"{etc_run_lines}"
        '  "${EXTRA_MOUNT_ARGS[@]+"${EXTRA_MOUNT_ARGS[@]}"}" \\\n'
    )

    # Build final command block
    if network == "loopback":
        bwrap_cmd = f"  /bin/bash -c 'ip link set lo up 2>/dev/null || true; exec /bin/bash --login'"
    else:
        bwrap_cmd = "  /bin/bash --login"
    final_cmd = (
        'exec "${CGROUP_ARGS[@]+"${CGROUP_ARGS[@]}"}" "$BWRAP" \\\n'
        + bwrap_flags
        + f"{bwrap_cmd}{resolv_redir}{fd_redirects}{heredoc_bodies}\n"
    )

    script = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'BWRAP=$(command -v bwrap 2>/dev/null) || { echo "bwrap not found" >&2; exit 1; }\n'
        "\n"
        f"USER_HOME={shlex.quote(user_home)}\n"
        f"BWRAP_HOSTNAME={shlex.quote(hostname)}\n"
        "\n"
        f"{extra_mount_args}"
        "\n"
        f"MAX_PROCS={max_procs}\n"
        f"MAX_FSIZE={max_fsize}\n"
        f"MAX_NOFILE={max_nofile}\n"
        f"CGROUP_MEM={cgroup_mem}\n"
        f"CGROUP_CPU={cgroup_cpu}\n"
        "\n"
        '[[ -n "$MAX_PROCS" ]]  && ulimit -Su "$MAX_PROCS"\n'
        '[[ -n "$MAX_FSIZE" ]]  && ulimit -Sf $(( MAX_FSIZE * 2048 ))\n'
        '[[ -n "$MAX_NOFILE" ]] && ulimit -Sn "$MAX_NOFILE"\n'
        "\n"
        "CGROUP_ARGS=()\n"
        'if [[ -n "$CGROUP_MEM" || -n "$CGROUP_CPU" ]]; then\n'
        "    if ! command -v systemd-run >/dev/null 2>&1 \\\n"
        '        || [[ -z "${XDG_RUNTIME_DIR:-}" && -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then\n'
        '        echo "[WARNING] Cgroup limits are configured (MEM=${CGROUP_MEM} CPU=${CGROUP_CPU})" >&2\n'
        '        echo "          but systemd user session is not available." >&2\n'
        '        echo "          Resource limits will be ulimits-only -- hard memory/CPU caps are NOT active." >&2\n'
        '        printf "          Proceed without cgroup limits? [y/N]: " >&2\n'
        "        read -r _reply\n"
        '        [[ "${_reply,,}" == "y" ]] || exit 1\n'
        "    else\n"
        "        CGROUP_ARGS=(systemd-run --user --scope --quiet)\n"
        '        [[ -n "$CGROUP_MEM" ]] && CGROUP_ARGS+=(--property="MemoryMax=${CGROUP_MEM}")\n'
        '        [[ -n "$CGROUP_CPU" ]] && CGROUP_ARGS+=(--property="CPUQuota=${CGROUP_CPU}")\n'
        "        CGROUP_ARGS+=(---)\n"
        "    fi\n"
        "fi\n"
        "\n"
        + f'[ -n "${{TMUX:-}}" ] && tmux rename-window {shlex.quote(username)} 2>/dev/null || true\n'
        + "\n"
        + (
            "ETC_FILES=(\n"
            "  hosts shells\n"
            "  ssl ca-certificates\n"
            "  localtime timezone\n"
            ")\n"
            "ETC_ARGS=()\n"
            'for f in "${ETC_FILES[@]}"; do\n'
            '  ETC_ARGS+=(--ro-bind-try "/etc/$f" "/etc/$f")\n'
            "done\n"
            "\n"
            if not sys_dirs else ""
        )
        + final_cmd
    )

    launcher_path = launcher_dir / f"bwrap-shell-{username}"

    if dry_run:
        print(f"[dry-run] would generate launcher {launcher_path}")
        return launcher_path

    tmp_path = launcher_path.parent / (launcher_path.name + ".tmp")
    tmp_path.write_text(script, encoding="utf-8")
    tmp_path.chmod(0o755)
    tmp_path.rename(launcher_path)
    return launcher_path
