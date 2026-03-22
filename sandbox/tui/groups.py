"""Groups pane for sandbox-tui."""
from __future__ import annotations

from textual.app import ComposeResult


def _mode_symbolic(mode: str) -> str:
    """Convert octal mode string (e.g. '0o750') to symbolic group bits (e.g. 'rwxr-x---')."""
    if not mode:
        return ""
    try:
        bits = int(mode, 8)
    except ValueError:
        return mode
    def _bits(n: int) -> str:
        return (
            ("r" if n & 4 else "-") +
            ("w" if n & 2 else "-") +
            ("x" if n & 1 else "-")
        )
    setgid = bool(bits & 0o2000)
    owner  = (bits >> 6) & 7
    group  = (bits >> 3) & 7
    others = bits & 7
    g_sym = _bits(group)
    if setgid:
        g_sym = g_sym[:2] + ("s" if g_sym[2] == "x" else "S")
    return g_sym

from textual.binding import Binding
from textual.coordinate import Coordinate
from textual.widget import Widget
from textual.widgets import DataTable


class GroupsPane(Widget):
    DEFAULT_CSS = """
    GroupsPane {
        height: 1fr;
        width: 1fr;
    }
    GroupsPane DataTable {
        height: 1fr;
    }
    """
    BINDINGS = [
        Binding("n", "new_group", "New"),
        Binding("d", "delete_group", "Delete"),
        Binding("c", "chmod", "Chmod"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._cfg = None

    def compose(self) -> ComposeResult:
        yield DataTable(id="groups-table", cursor_type="row")

    def load(self, cfg) -> None:
        self._cfg = cfg
        self._reload()
        self.query_one(DataTable).focus()

    def _reload(self) -> None:
        if self._cfg is None:
            return
        from sandbox.groups import list_groups
        table = self.query_one(DataTable)
        table.clear(columns=True)
        table.add_columns("NAME", "MEMBERS", "PERMS", "DIR SIZE")
        try:
            for g in list_groups(self._cfg):
                members = ", ".join(g.get("members", []))
                table.add_row(g["groupname"], members, _mode_symbolic(g.get("dir_mode", "")), g.get("dir_size", ""))
        except Exception as e:
            self.notify(f"Failed to load groups: {e}", severity="error")

    def _selected_groupname(self) -> str | None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return None
        return str(table.get_cell_at(Coordinate(table.cursor_row, 0)))

    def on_data_table_row_selected(self, _event: DataTable.RowSelected) -> None:
        self.action_inspect()

    def action_inspect(self) -> None:
        groupname = self._selected_groupname()
        if not groupname:
            self.notify("No group selected", severity="warning")
            return
        from sandbox.groups import list_groups
        from sandbox.tui.modals import OutputScreen
        groups = list_groups(self._cfg)
        g = next((x for x in groups if x["groupname"] == groupname), None)
        if not g:
            self.notify("Group not found", severity="error")
            return

        group_dir = g["group_dir"]
        present = group_dir.exists()
        mode_sym = _mode_symbolic(g.get("dir_mode", ""))
        mode_raw = g.get("dir_mode", "")
        mode_str = f"{mode_sym} ({mode_raw})" if mode_sym else mode_raw or "—"

        lines = [f"Group: {groupname}"]
        lines.append(f"  GID:     {g['gid']}")
        lines.append(f"  Dir:     {group_dir} ({'present' if present else 'missing'})")
        lines.append(f"  Perms:   {mode_str}")
        lines.append(f"  Size:    {g.get('dir_size') or '—'}")
        members = g.get("members", [])
        lines.append(f"  Members: {', '.join(members) if members else '—'}")

        if present:
            try:
                files = sorted(f.name for f in group_dir.iterdir() if f.is_file())
                if files:
                    lines.append("")
                    lines.append("Installed files:")
                    for name in files:
                        lines.append(f"  {name}")
            except PermissionError:
                lines.append("")
                lines.append("Installed files: (permission denied)")

        self.app.push_screen(OutputScreen("\n".join(lines)))

    def action_new_group(self) -> None:
        from sandbox.tui.modals import CreateGroupScreen
        self.app.push_screen(CreateGroupScreen(self._cfg), self._on_mutate)

    def action_delete_group(self) -> None:
        groupname = self._selected_groupname()
        if not groupname:
            self.notify("No group selected", severity="warning")
            return
        from sandbox.groups import audit_group
        from sandbox.config import SandboxError
        from sandbox.tui.modals import ConfirmDeleteScreen
        try:
            audit = audit_group(self._cfg, groupname)
        except SandboxError as e:
            self.notify(str(e), severity="error")
            return
        lines = [f"Audit for group '{groupname}':"]
        lines.append(f"  GID:       {audit['gid']}")
        lines.append(f"  Directory: {audit['group_dir']} ({'present' if audit['group_dir_present'] else 'missing'})")
        if audit.get("companion_user"):
            lines.append(f"  Companion: {audit.get('companion_user')} (will be deleted)")
        if audit.get("members", []):
            lines.append(f"  Members:   {', '.join(audit.get('members', []))}")

        def on_confirm(result: tuple[bool, bool]) -> None:
            confirmed, _force = result
            if not confirmed:
                return
            from sandbox.groups import delete_group
            from sandbox.config import SandboxError
            from sandbox.tui.users import UsersPane
            try:
                delete_group(self._cfg, groupname)
                self._reload()
                self.app.query_one(UsersPane)._reload()
                self.notify(f"Group '{groupname}' deleted.")
            except SandboxError as e:
                self.notify(str(e), severity="error")

        self.app.push_screen(ConfirmDeleteScreen(groupname, "\n".join(lines)), on_confirm)

    def action_chmod(self) -> None:
        groupname = self._selected_groupname()
        if not groupname:
            self.notify("No group selected", severity="warning")
            return
        from sandbox.groups import list_groups
        from sandbox.tui.modals import ChmodScreen
        groups = list_groups(self._cfg)
        current_mode = next((g["dir_mode"] for g in groups if g["groupname"] == groupname), "")
        self.app.push_screen(ChmodScreen(self._cfg, groupname, current_mode), self._on_mutate)

    def _on_mutate(self, result: bool) -> None:
        if result:
            self._reload()
