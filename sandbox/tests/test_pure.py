"""Unit tests for pure/stateless sandbox functions."""
import pytest
import stat
import tempfile
import os
from pathlib import Path

from sandbox.models import UserConfig, MountEntry, Profile
from sandbox.state import (
    write_base,
    read_base,
    write_extra_mounts,
    read_extra_mounts,
    write_profile_name,
    read_profile_name,
    add_group_bind_mount,
    remove_group_bind_mount,
    write_ids,
    read_ids,
)
from sandbox.launcher import generate_launcher
from sandbox.ids import allocate_id
from sandbox.shells import is_in_shells, add_to_shells, remove_from_shells


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cfg(**kwargs) -> UserConfig:
    defaults = dict(username="testuser")
    defaults.update(kwargs)
    return UserConfig(**defaults)


# ---------------------------------------------------------------------------
# TestState
# ---------------------------------------------------------------------------

class TestState:
    def test_write_read_base_roundtrip(self, tmp_path):
        cfg = _make_cfg(
            no_usr=True,
            sys_dirs=True,
            network="loopback",
            hostname="my-box",
            max_procs="100",
            max_fsize="512",
            max_nofile="1024",
            cgroup_mem="512M",
            cgroup_cpu="50%",
        )
        home = Path("/home/testuser")
        write_base(tmp_path, "testuser", cfg, home)
        data = read_base(tmp_path, "testuser")

        assert data["NO_USR"] == "1"
        assert data["SYS_DIRS"] == "1"
        assert data["USER_HOME"] == "/home/testuser"
        assert data["HOSTNAME"] == "my-box"
        assert data["NETWORK"] == "loopback"
        assert data["MAX_PROCS"] == "100"
        assert data["MAX_FSIZE"] == "512"
        assert data["MAX_NOFILE"] == "1024"
        assert data["CGROUP_MEM"] == "512M"
        assert data["CGROUP_CPU"] == "50%"
    def test_write_base_default_hostname(self, tmp_path):
        cfg = _make_cfg()  # hostname=""
        write_base(tmp_path, "testuser", cfg, Path("/home/testuser"))
        data = read_base(tmp_path, "testuser")
        assert data["HOSTNAME"] == "sandbox-testuser"

    def test_write_base_dry_run_no_file(self, tmp_path):
        cfg = _make_cfg()
        write_base(tmp_path, "testuser", cfg, Path("/home/testuser"), dry_run=True)
        base_file = tmp_path / "testuser" / "base"
        assert not base_file.exists()

    def test_read_base_missing_returns_empty(self, tmp_path):
        assert read_base(tmp_path, "nobody") == {}

    def test_write_read_extra_mounts_empty(self, tmp_path):
        write_extra_mounts(tmp_path, "testuser", [])
        mounts = read_extra_mounts(tmp_path, "testuser")
        assert mounts == []

    def test_write_read_extra_mounts_with_entry(self, tmp_path):
        entries = [
            MountEntry(kind="--bind", source="/opt/myapp", dest="/opt/myapp"),
            MountEntry(kind="--ro-bind", source="/etc/passwd", dest="/etc/passwd"),
        ]
        write_extra_mounts(tmp_path, "testuser", entries)
        result = read_extra_mounts(tmp_path, "testuser")

        assert len(result) == 2
        assert result[0].kind == "--bind"
        assert result[0].source == "/opt/myapp"
        assert result[0].dest == "/opt/myapp"
        assert result[1].kind == "--ro-bind"
        assert result[1].source == "/etc/passwd"
        assert result[1].dest == "/etc/passwd"

    def test_read_extra_mounts_missing_returns_empty(self, tmp_path):
        assert read_extra_mounts(tmp_path, "nobody") == []

    def test_add_group_bind_mount_idempotent(self, tmp_path):
        group_dir = Path("/opt/groups/devteam")
        add_group_bind_mount(tmp_path, "testuser", group_dir)
        add_group_bind_mount(tmp_path, "testuser", group_dir)
        mounts = read_extra_mounts(tmp_path, "testuser")
        bind_mounts = [m for m in mounts if m.source == str(group_dir)]
        assert len(bind_mounts) == 1

    def test_remove_group_bind_mount(self, tmp_path):
        dir_a = Path("/opt/groups/team_a")
        dir_b = Path("/opt/groups/team_b")
        add_group_bind_mount(tmp_path, "testuser", dir_a)
        add_group_bind_mount(tmp_path, "testuser", dir_b)
        remove_group_bind_mount(tmp_path, "testuser", dir_a)
        mounts = read_extra_mounts(tmp_path, "testuser")
        sources = {m.source for m in mounts}
        assert str(dir_a) not in sources
        assert str(dir_b) in sources

    def test_write_read_profile_name_roundtrip(self, tmp_path):
        write_profile_name(tmp_path, "testuser", "minimal")
        assert read_profile_name(tmp_path, "testuser") == "minimal"

    def test_read_profile_name_missing_returns_empty(self, tmp_path):
        assert read_profile_name(tmp_path, "nobody") == ""

    def test_write_profile_name_dry_run_no_file(self, tmp_path):
        write_profile_name(tmp_path, "testuser", "minimal", dry_run=True)
        profile_file = tmp_path / "testuser" / "profile"
        assert not profile_file.exists()

    def test_users_dir_permissions(self, tmp_path):
        cfg = _make_cfg()
        write_base(tmp_path, "testuser", cfg, Path("/home/testuser"))
        user_dir = tmp_path / "testuser"
        mode = stat.S_IMODE(user_dir.stat().st_mode)
        assert mode == 0o700

    def test_base_file_permissions(self, tmp_path):
        cfg = _make_cfg()
        write_base(tmp_path, "testuser", cfg, Path("/home/testuser"))
        base_file = tmp_path / "testuser" / "base"
        mode = stat.S_IMODE(base_file.stat().st_mode)
        assert mode == 0o600

    def test_profile_file_permissions(self, tmp_path):
        write_profile_name(tmp_path, "testuser", "minimal")
        profile_file = tmp_path / "testuser" / "profile"
        mode = stat.S_IMODE(profile_file.stat().st_mode)
        assert mode == 0o644

    def test_write_read_ids_roundtrip(self, tmp_path):
        write_ids(tmp_path, "testuser", 1001, 1001)
        result = read_ids(tmp_path, "testuser")
        assert result == (1001, 1001)

    def test_read_ids_missing_returns_none(self, tmp_path):
        assert read_ids(tmp_path, "nobody") is None

    def test_ids_file_permissions(self, tmp_path):
        write_ids(tmp_path, "testuser", 1001, 1001)
        ids_file = tmp_path / "testuser" / "ids"
        mode = stat.S_IMODE(ids_file.stat().st_mode)
        assert mode == 0o600


# ---------------------------------------------------------------------------
# TestLauncher
# ---------------------------------------------------------------------------

class TestLauncher:
    def _write_state(self, users_dir, username, cfg, home="/home/testuser", mounts=None, uid=1001):
        write_base(users_dir, username, cfg, Path(home))
        write_extra_mounts(users_dir, username, mounts or [])
        write_ids(users_dir, username, uid, uid)

    def test_network_full_no_unshare_net(self, tmp_path):
        users_dir = tmp_path / "users"
        launcher_dir = tmp_path / "launchers"
        launcher_dir.mkdir()
        cfg = _make_cfg(network="full")
        self._write_state(users_dir, "testuser", cfg)
        path = generate_launcher(launcher_dir, users_dir, "testuser")
        content = path.read_text()
        assert "--unshare-net" not in content

    def test_network_loopback_has_unshare_and_ip_link(self, tmp_path):
        users_dir = tmp_path / "users"
        launcher_dir = tmp_path / "launchers"
        launcher_dir.mkdir()
        cfg = _make_cfg(network="loopback")
        self._write_state(users_dir, "testuser", cfg)
        path = generate_launcher(launcher_dir, users_dir, "testuser")
        content = path.read_text()
        assert "--unshare-net" in content
        assert "ip link set lo up" in content

    def test_network_none_has_unshare_no_ip_link(self, tmp_path):
        users_dir = tmp_path / "users"
        launcher_dir = tmp_path / "launchers"
        launcher_dir.mkdir()
        cfg = _make_cfg(network="none")
        self._write_state(users_dir, "testuser", cfg)
        path = generate_launcher(launcher_dir, users_dir, "testuser")
        content = path.read_text()
        assert "--unshare-net" in content
        assert "ip link set lo up" not in content

    def test_no_usr_true_omits_usr_bind(self, tmp_path):
        users_dir = tmp_path / "users"
        launcher_dir = tmp_path / "launchers"
        launcher_dir.mkdir()
        cfg = _make_cfg(no_usr=True)
        self._write_state(users_dir, "testuser", cfg)
        path = generate_launcher(launcher_dir, users_dir, "testuser")
        content = path.read_text()
        assert "--ro-bind /usr /usr" not in content

    def test_no_usr_false_has_usr_bind(self, tmp_path):
        users_dir = tmp_path / "users"
        launcher_dir = tmp_path / "launchers"
        launcher_dir.mkdir()
        cfg = _make_cfg(no_usr=False)
        self._write_state(users_dir, "testuser", cfg)
        path = generate_launcher(launcher_dir, users_dir, "testuser")
        content = path.read_text()
        assert "--ro-bind /usr /usr" in content

    def test_sys_dirs_true_has_etc_and_run(self, tmp_path):
        users_dir = tmp_path / "users"
        launcher_dir = tmp_path / "launchers"
        launcher_dir.mkdir()
        cfg = _make_cfg(sys_dirs=True)
        self._write_state(users_dir, "testuser", cfg)
        path = generate_launcher(launcher_dir, users_dir, "testuser")
        content = path.read_text()
        assert "--ro-bind /etc /etc" in content
        assert "--ro-bind /run /run" in content

    def test_sys_dirs_false_omits_etc_and_run(self, tmp_path):
        users_dir = tmp_path / "users"
        launcher_dir = tmp_path / "launchers"
        launcher_dir.mkdir()
        cfg = _make_cfg(sys_dirs=False)
        self._write_state(users_dir, "testuser", cfg)
        path = generate_launcher(launcher_dir, users_dir, "testuser")
        content = path.read_text()
        assert "--ro-bind /etc /etc" not in content
        assert "--ro-bind /run /run" not in content

    def test_launcher_file_mode_755(self, tmp_path):
        users_dir = tmp_path / "users"
        launcher_dir = tmp_path / "launchers"
        launcher_dir.mkdir()
        cfg = _make_cfg()
        self._write_state(users_dir, "testuser", cfg)
        path = generate_launcher(launcher_dir, users_dir, "testuser")
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o755

    def test_launcher_shebang(self, tmp_path):
        users_dir = tmp_path / "users"
        launcher_dir = tmp_path / "launchers"
        launcher_dir.mkdir()
        cfg = _make_cfg()
        self._write_state(users_dir, "testuser", cfg)
        path = generate_launcher(launcher_dir, users_dir, "testuser")
        first_line = path.read_text().splitlines()[0]
        assert first_line == "#!/usr/bin/env bash"

    def test_launcher_dry_run_no_file(self, tmp_path):
        users_dir = tmp_path / "users"
        launcher_dir = tmp_path / "launchers"
        launcher_dir.mkdir()
        cfg = _make_cfg()
        self._write_state(users_dir, "testuser", cfg)
        path = generate_launcher(launcher_dir, users_dir, "testuser", dry_run=True)
        assert not path.exists()

    def test_launcher_missing_user_home_raises(self, tmp_path):
        users_dir = tmp_path / "users"
        launcher_dir = tmp_path / "launchers"
        launcher_dir.mkdir()
        # Write base with empty USER_HOME by manipulating the file directly
        (users_dir / "testuser").mkdir(parents=True)
        (users_dir / "testuser" / "base").write_text("NO_USR=0\nSYS_DIRS=0\n")
        # Also write ids so the ids check passes and we reach the USER_HOME check
        write_ids(users_dir, "testuser", 1001, 1001)
        with pytest.raises(ValueError, match="USER_HOME"):
            generate_launcher(launcher_dir, users_dir, "testuser")

    def test_launcher_injects_jobctl(self, tmp_path):
        users_dir = tmp_path / "users"
        launcher_dir = tmp_path / "launchers"
        launcher_dir.mkdir()
        cfg = _make_cfg(no_usr=False)
        self._write_state(users_dir, "testuser", cfg)
        content = generate_launcher(launcher_dir, users_dir, "testuser").read_text()
        assert "/usr/local/bin/jobctl" in content
        assert ".jobctl_pids" in content

    def test_launcher_no_jobctl_when_no_usr(self, tmp_path):
        users_dir = tmp_path / "users"
        launcher_dir = tmp_path / "launchers"
        launcher_dir.mkdir()
        cfg = _make_cfg(no_usr=True)
        self._write_state(users_dir, "testuser", cfg)
        content = generate_launcher(launcher_dir, users_dir, "testuser").read_text()
        assert "/usr/local/bin/jobctl" not in content

    def test_launcher_no_unshare_pid(self, tmp_path):
        users_dir = tmp_path / "users"
        launcher_dir = tmp_path / "launchers"
        launcher_dir.mkdir()
        cfg = _make_cfg()
        self._write_state(users_dir, "testuser", cfg)
        content = generate_launcher(launcher_dir, users_dir, "testuser").read_text()
        assert "--unshare-pid" not in content

    def test_launcher_exec_mode_no_die_with_parent(self, tmp_path):
        users_dir = tmp_path / "users"
        launcher_dir = tmp_path / "launchers"
        launcher_dir.mkdir()
        self._write_state(users_dir, "testuser", _make_cfg())
        content = generate_launcher(launcher_dir, users_dir, "testuser").read_text()
        assert "if [ $# -gt 0 ]" in content
        exec_branch = content.split("if [ $# -gt 0 ]")[1].split("else")[0]
        assert "--die-with-parent" not in exec_branch

    def test_launcher_interactive_mode_has_die_with_parent(self, tmp_path):
        users_dir = tmp_path / "users"
        launcher_dir = tmp_path / "launchers"
        launcher_dir.mkdir()
        self._write_state(users_dir, "testuser", _make_cfg())
        content = generate_launcher(launcher_dir, users_dir, "testuser").read_text()
        hash_block = content.split("if [ $# -gt 0 ]")[1]
        interactive_branch = hash_block.split("else\n")[1].split("\nfi\n")[0]
        assert "--die-with-parent" in interactive_branch

    def test_launcher_has_unshare_user(self, tmp_path):
        users_dir = tmp_path / "users"
        launcher_dir = tmp_path / "launchers"
        launcher_dir.mkdir()
        cfg = _make_cfg()
        self._write_state(users_dir, "testuser", cfg, uid=1001)
        path = generate_launcher(launcher_dir, users_dir, "testuser")
        content = path.read_text()
        assert "--unshare-user" in content
        assert "--uid 1001" in content
        assert "--gid 1001" in content

    def test_launcher_has_synthetic_passwd(self, tmp_path):
        users_dir = tmp_path / "users"
        launcher_dir = tmp_path / "launchers"
        launcher_dir.mkdir()
        cfg = _make_cfg()
        self._write_state(users_dir, "testuser", cfg, uid=1001)
        path = generate_launcher(launcher_dir, users_dir, "testuser")
        content = path.read_text()
        assert "/etc/passwd" in content
        assert "testuser" in content

    def test_launcher_no_passwd_in_etc_files(self, tmp_path):
        users_dir = tmp_path / "users"
        launcher_dir = tmp_path / "launchers"
        launcher_dir.mkdir()
        cfg = _make_cfg()
        self._write_state(users_dir, "testuser", cfg)
        path = generate_launcher(launcher_dir, users_dir, "testuser")
        content = path.read_text()
        # ETC_FILES should not contain passwd or group
        for line in content.splitlines():
            if "ETC_FILES" in line or (line.strip().startswith("passwd") or line.strip().startswith("group")):
                assert "passwd group" not in line

    def test_mount_group_script_uses_internal_path(self, tmp_path):
        """mount-group script must use the fixed internal path /run/sandbox-groups/$GROUP."""
        users_dir = tmp_path / "users"
        launcher_dir = tmp_path / "launchers"
        launcher_dir.mkdir()
        groups_dir = tmp_path / "groups"
        grp_container = groups_dir / "mygrp"
        grp_shared = grp_container / "mygrp.group-dir"
        grp_shared.mkdir(parents=True)
        (grp_container / "mygrp.gid").write_text("1002\n")
        cfg = _make_cfg()
        # Write state first, then add group bind mount so it isn't overwritten
        self._write_state(users_dir, "testuser", cfg)
        add_group_bind_mount(users_dir, "testuser", grp_shared)
        path = generate_launcher(launcher_dir, users_dir, "testuser")
        content = path.read_text()
        assert '/run/sandbox-groups/$GROUP' in content
        assert 'group-dir' not in content.split('EXTRA_MOUNT_ARGS')[0]  # not in script body

    def test_launcher_group_gid_extraction_uses_parent_name(self, tmp_path):
        """Synthetic /etc/group must use the group container name, not 'group-dir'."""
        users_dir = tmp_path / "users"
        launcher_dir = tmp_path / "launchers"
        launcher_dir.mkdir()
        groups_dir = tmp_path / "groups"
        grp_container = groups_dir / "mygrp"
        grp_shared = grp_container / "mygrp.group-dir"
        grp_shared.mkdir(parents=True)
        (grp_container / "mygrp.gid").write_text("1042\n")
        cfg = _make_cfg()
        self._write_state(users_dir, "testuser", cfg)
        add_group_bind_mount(users_dir, "testuser", grp_shared)
        path = generate_launcher(launcher_dir, users_dir, "testuser")
        content = path.read_text()
        assert "mygrp:x:1042:" in content


# ---------------------------------------------------------------------------
# TestIds
# ---------------------------------------------------------------------------

class TestIds:
    def test_first_allocation_returns_1001(self, tmp_path):
        data_dir = tmp_path / "ids"
        result = allocate_id(data_dir)
        assert result == 1001

    def test_second_allocation_returns_1002(self, tmp_path):
        data_dir = tmp_path / "ids"
        allocate_id(data_dir)
        result = allocate_id(data_dir)
        assert result == 1002

    def test_works_when_data_dir_does_not_exist(self, tmp_path):
        data_dir = tmp_path / "nonexistent" / "subdir"
        assert not data_dir.exists()
        result = allocate_id(data_dir)
        assert result == 1001
        assert data_dir.exists()

    def test_existing_counter_is_read_and_incremented(self, tmp_path):
        data_dir = tmp_path / "ids"
        data_dir.mkdir()
        (data_dir / "next_id").write_text("2050")
        result = allocate_id(data_dir)
        assert result == 2050
        assert (data_dir / "next_id").read_text().strip() == "2051"

    def test_counter_file_contains_next_value_after_allocation(self, tmp_path):
        data_dir = tmp_path / "ids"
        result = allocate_id(data_dir)
        assert result == 1001
        assert (data_dir / "next_id").read_text().strip() == "1002"

    def test_lock_file_exists_after_allocation(self, tmp_path):
        data_dir = tmp_path / "ids"
        allocate_id(data_dir)
        assert (data_dir / "next_id.lock").exists()


# ---------------------------------------------------------------------------
# TestShells
# ---------------------------------------------------------------------------

class TestShells:
    def test_is_in_shells_always_false(self):
        assert is_in_shells("/bin/bash") is False
        assert is_in_shells("/nonexistent/shell/path/xyz") is False

    def test_add_to_shells_does_not_raise(self):
        add_to_shells("/fake/shell")
        add_to_shells("/fake/shell", dry_run=True)

    def test_remove_from_shells_does_not_raise(self):
        remove_from_shells("/fake/shell")
        remove_from_shells("/fake/shell", dry_run=True)


# ---------------------------------------------------------------------------
# TestModels
# ---------------------------------------------------------------------------

class TestModels:
    def test_userconfig_defaults(self):
        cfg = UserConfig(username="alice")
        assert cfg.username == "alice"
        assert cfg.no_usr is False
        assert cfg.sys_dirs is False
        assert cfg.network == "full"
        assert cfg.hostname == ""
        assert cfg.max_procs == ""
        assert cfg.max_fsize == ""
        assert cfg.max_nofile == ""
        assert cfg.cgroup_mem == ""
        assert cfg.cgroup_cpu == ""
        assert cfg.comment == ""
        assert cfg.extra_groups == []
        assert cfg.fake_sudo is False

    def test_userconfig_extra_groups_independent(self):
        # Ensure default_factory gives independent lists per instance
        cfg1 = UserConfig(username="a")
        cfg2 = UserConfig(username="b")
        cfg1.extra_groups.append("wheel")
        assert cfg2.extra_groups == []

    def test_mount_entry_fields(self):
        m = MountEntry(kind="--bind", source="/src", dest="/dst")
        assert m.kind == "--bind"
        assert m.source == "/src"
        assert m.dest == "/dst"

    def test_profile_construction(self):
        user_cfg = UserConfig(username="alice")
        mounts = [MountEntry("--bind", "/a", "/a")]
        p = Profile(
            name="dev",
            description="Development profile",
            user=user_cfg,
            hostname="dev-box",
            bind_entries=mounts,
            shadow_paths=["/secret"],
            install_entries=["some-pkg"],
            dotfiles=[".bashrc"],
            post_setup="echo done",
            on_enter="echo entered",
        )
        assert p.name == "dev"
        assert p.description == "Development profile"
        assert p.user is user_cfg
        assert p.hostname == "dev-box"
        assert len(p.bind_entries) == 1
        assert p.shadow_paths == ["/secret"]
        assert p.install_entries == ["some-pkg"]
        assert p.dotfiles == [".bashrc"]
        assert p.post_setup == "echo done"
        assert p.on_enter == "echo entered"
