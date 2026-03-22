"""Users pane for sandbox-tui."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.coordinate import Coordinate
from textual.widget import Widget
from textual.widgets import DataTable


class UsersPane(Widget):
    DEFAULT_CSS = """
    UsersPane {
        height: 1fr;
        width: 1fr;
    }
    UsersPane DataTable {
        height: 1fr;
    }
    """
    BINDINGS = [
        Binding("n", "new_user", "New"),
        Binding("d", "delete_user", "Delete"),
        Binding("i", "install", "Install"),
        Binding("m", "membership", "Member"),
        Binding("l", "login", "Login"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._cfg = None

    def compose(self) -> ComposeResult:
        yield DataTable(id="users-table", cursor_type="row")

    def load(self, cfg) -> None:
        self._cfg = cfg
        self._reload()
        self.query_one(DataTable).focus()

    def _reload(self) -> None:
        if self._cfg is None:
            return
        from sandbox.users import list_users
        table = self.query_one(DataTable)
        table.clear(columns=True)
        table.add_columns("USER", "PROFILE", "SUPP GROUPS")
        try:
            for u in list_users(self._cfg):
                supp = ", ".join(u.get("supp_groups", []))
                table.add_row(u["username"], u.get("profile") or "", supp)
        except Exception as e:
            self.notify(f"Failed to load users: {e}", severity="error")

    def _selected_username(self) -> str | None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return None
        return str(table.get_cell_at(Coordinate(table.cursor_row, 0)))

    def on_data_table_row_selected(self, _event: DataTable.RowSelected) -> None:
        self.action_inspect()

    def action_inspect(self) -> None:
        username = self._selected_username()
        if not username:
            self.notify("No user selected", severity="warning")
            return
        from sandbox.state import read_base, read_extra_mounts, read_profile_name
        from sandbox.tui.modals import OutputScreen
        base = read_base(self._cfg.state_dir, username)
        mounts = read_extra_mounts(self._cfg.state_dir, username)
        profile_name = read_profile_name(self._cfg.state_dir, username)

        # Categorise mounts
        sandbox_root = str(self._cfg.homes_dir / username / "sandbox-root")
        groups_dir = str(self._cfg.groups_dir)
        installed, group_mounts, extra = [], [], []
        for m in mounts:
            if m.source.startswith(sandbox_root):
                installed.append(m)
            elif m.source.startswith(groups_dir):
                group_mounts.append(m)
            else:
                extra.append(m)

        def _val(key, default="—"):
            v = base.get(key, "")
            return v if v else default

        lines = [f"User: {username}"]
        lines.append(f"  Profile:    {profile_name or '—'}")
        lines.append(f"  Home:       {_val('USER_HOME')}")
        lines.append(f"  Hostname:   {_val('HOSTNAME')}")
        lines.append(f"  Network:    {_val('NETWORK')}")
        lines.append(f"  /usr:       {'excluded' if base.get('NO_USR') == '1' else 'included'}")
        lines.append(f"  /etc+/run:  {'full ro-bind' if base.get('SYS_DIRS') == '1' else 'minimal'}")
        lines.append(f"  Fake sudo:  {'yes' if base.get('FAKE_SUDO') == '1' else 'no'}")
        for label, key in [("Max procs", "MAX_PROCS"), ("Max fsize", "MAX_FSIZE"),
                           ("Max nofile", "MAX_NOFILE"), ("Cgroup mem", "CGROUP_MEM"),
                           ("Cgroup cpu", "CGROUP_CPU")]:
            v = base.get(key, "")
            if v:
                lines.append(f"  {label}:  {v}")

        # supplementary groups from users list
        from sandbox.users import list_users
        users = list_users(self._cfg)
        user_data = next((u for u in users if u["username"] == username), None)
        supp = user_data.get("supp_groups", []) if user_data else []
        if supp:
            lines.append(f"  Groups:     {', '.join(supp)}")

        if installed:
            lines.append("")
            lines.append("Installed:")
            for m in installed:
                lines.append(f"  {m.source} → {m.dest}")

        if group_mounts:
            lines.append("")
            lines.append("Group mounts:")
            for m in group_mounts:
                lines.append(f"  {m.source}")

        if extra:
            lines.append("")
            lines.append("Extra mounts:")
            for m in extra:
                lines.append(f"  {m.kind} {m.source} → {m.dest}")

        self.app.push_screen(OutputScreen("\n".join(lines)))

    def action_new_user(self) -> None:
        from sandbox.tui.modals import CreateUserScreen
        self.app.push_screen(CreateUserScreen(self._cfg), self._on_mutate)

    def action_delete_user(self) -> None:
        username = self._selected_username()
        if not username:
            self.notify("No user selected", severity="warning")
            return
        from sandbox.users import audit_user
        from sandbox.config import SandboxError
        from sandbox.tui.modals import ConfirmDeleteScreen
        try:
            audit = audit_user(self._cfg, username)
        except SandboxError as e:
            self.notify(str(e), severity="error")
            return
        lines = [f"Audit for user '{username}':"]
        lines.append(f"  Home:       {audit['actual_home']} ({'present' if audit['home_present'] else 'missing'})")
        lines.append(f"  Launcher:   {audit['launcher']} ({'present' if audit['launcher_present'] else 'missing'})")
        lines.append(f"  State dir:  {audit['state_dir']} ({'present' if audit['state_dir_present'] else 'missing'})")
        if audit["supp_groups"]:
            lines.append(f"  Groups:     {', '.join(audit['supp_groups'])}")
        if audit["private_group"]:
            lines.append(f"  Private group: {audit['private_group']} (will be deleted)")
        if audit["running_pids"]:
            lines.append(f"  WARNING: {len(audit['running_pids'])} process(es) running as {username}")

        def on_confirm(result: tuple[bool, bool]) -> None:
            confirmed, force = result
            if not confirmed:
                return
            from sandbox.users import delete_user
            from sandbox.config import SandboxError
            try:
                delete_user(self._cfg, username, force=force)
                self._reload()
                self.notify(f"User '{username}' deleted.")
            except SandboxError as e:
                self.notify(str(e), severity="error")

        self.app.push_screen(ConfirmDeleteScreen(username, "\n".join(lines), show_force=True), on_confirm)

    def action_install(self) -> None:
        username = self._selected_username()
        if not username:
            self.notify("No user selected", severity="warning")
            return
        from sandbox.tui.modals import InstallScreen
        self.app.push_screen(InstallScreen(self._cfg, username))

    def action_membership(self) -> None:
        username = self._selected_username()
        if not username:
            self.notify("No user selected", severity="warning")
            return
        from sandbox.groups import list_groups
        from sandbox.users import list_users
        from sandbox.tui.modals import MembershipScreen
        try:
            all_groups = [g["groupname"] for g in list_groups(self._cfg)]
            users = list_users(self._cfg)
            user_data = next((u for u in users if u["username"] == username), None)
            current_groups = user_data.get("supp_groups", []) if user_data else []
        except Exception as e:
            self.notify(str(e), severity="error")
            return
        self.app.push_screen(
            MembershipScreen(self._cfg, username, current_groups, all_groups),
            self._on_mutate,
        )

    def action_login(self) -> None:
        username = self._selected_username()
        if not username:
            self.notify("No user selected", severity="warning")
            return
        self.app.exit(username)

    def _on_mutate(self, result: bool) -> None:
        if result:
            self._reload()
