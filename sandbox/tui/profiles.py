"""Profiles pane for sandbox-tui."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.coordinate import Coordinate
from textual.widget import Widget
from textual.widgets import DataTable


class ProfilesPane(Widget):
    DEFAULT_CSS = """
    ProfilesPane {
        height: 1fr;
        width: 1fr;
    }
    ProfilesPane DataTable {
        height: 1fr;
    }
    """
    BINDINGS = [
        Binding("n", "new_profile", "New"),
        Binding("c", "clone_profile", "Clone"),
        Binding("d", "delete_profile", "Delete"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._cfg = None
        self._loaded = False

    def compose(self) -> ComposeResult:
        yield DataTable(id="profiles-table", cursor_type="row")

    def load(self, cfg) -> None:
        self._cfg = cfg
        self._loaded = True
        self._reload()
        self.query_one(DataTable).focus()

    def _reload(self) -> None:
        if self._cfg is None:
            return
        from sandbox.profiles import list_profiles
        table = self.query_one(DataTable)
        table.clear(columns=True)
        table.add_columns("PROFILE", "DESCRIPTION")
        try:
            for p in list_profiles(self._cfg.project_root / "profiles"):
                table.add_row(p["name"], p["description"] or "")
        except Exception as e:
            self.notify(f"Failed to load profiles: {e}", severity="error")

    def _selected_profile_name(self) -> str | None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return None
        return str(table.get_cell_at(Coordinate(table.cursor_row, 0)))

    def on_data_table_row_selected(self, _event: DataTable.RowSelected) -> None:
        self.action_inspect()

    def action_inspect(self) -> None:
        name = self._selected_profile_name()
        if not name:
            self.notify("No profile selected", severity="warning")
            return
        from sandbox.profiles import load_profile
        from sandbox.tui.modals import OutputScreen
        try:
            p = load_profile(self._cfg.project_root / "profiles", name)
        except Exception as e:
            self.notify(f"Failed to load profile: {e}", severity="error")
            return

        u = p.user
        lines = [f"Profile: {name}"]
        if p.description:
            lines.append(f"  Description: {p.description}")
        lines.append(f"  Network:     {u.network or 'full'}")
        if p.hostname:
            lines.append(f"  Hostname:    {p.hostname}")
        lines.append(f"  No /usr:     {'yes' if u.no_usr else 'no'}")
        lines.append(f"  Sys dirs:    {'yes' if u.sys_dirs else 'no'}")
        lines.append(f"  Fake sudo:   {'yes' if u.fake_sudo else 'no'}")
        if u.extra_groups:
            lines.append(f"  Extra groups: {', '.join(u.extra_groups)}")
        for label, val in [("Max procs", u.max_procs), ("Max fsize", u.max_fsize),
                           ("Max nofile", u.max_nofile), ("Cgroup mem", u.cgroup_mem),
                           ("Cgroup cpu", u.cgroup_cpu)]:
            if val:
                lines.append(f"  {label}:  {val}")
        if u.comment:
            lines.append(f"  Comment:     {u.comment}")

        if p.bind_entries:
            lines.append("")
            lines.append("Binds:")
            for m in p.bind_entries:
                lines.append(f"  {m.kind} {m.source} → {m.dest}")

        if p.shadow_paths:
            lines.append("")
            lines.append("Shadow:")
            for s in p.shadow_paths:
                lines.append(f"  {s}")

        if p.install_entries:
            lines.append("")
            lines.append("Install:")
            for e in p.install_entries:
                lines.append(f"  {e}")

        if p.dotfiles:
            lines.append("")
            lines.append("Dotfiles:")
            for d in p.dotfiles:
                lines.append(f"  {d}")

        scripts = []
        if p.post_setup:
            scripts.append("post_setup.sh")
        if p.on_enter:
            scripts.append("on_enter.sh")
        if scripts:
            lines.append("")
            lines.append(f"Scripts:  {', '.join(scripts)}")

        self.app.push_screen(OutputScreen("\n".join(lines)))

    def action_new_profile(self) -> None:
        from sandbox.tui.modals import CreateProfileScreen
        self.app.push_screen(CreateProfileScreen(self._cfg), self._on_mutate)

    def action_clone_profile(self) -> None:
        name = self._selected_profile_name()
        if not name:
            self.notify("No profile selected", severity="warning")
            return
        from sandbox.profiles import load_profile
        from sandbox.tui.modals import CreateProfileScreen
        try:
            source = load_profile(self._cfg.project_root / "profiles", name)
        except Exception as e:
            self.notify(f"Failed to load profile: {e}", severity="error")
            return
        self.app.push_screen(CreateProfileScreen(self._cfg, source_profile=source), self._on_mutate)

    def action_delete_profile(self) -> None:
        name = self._selected_profile_name()
        if not name:
            self.notify("No profile selected", severity="warning")
            return
        from sandbox.tui.modals import ConfirmDeleteProfileScreen
        self.app.push_screen(
            ConfirmDeleteProfileScreen(self._cfg.project_root / "profiles", name),
            self._on_mutate,
        )

    def _on_mutate(self, result: bool) -> None:
        if result:
            self._reload()
