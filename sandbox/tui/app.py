"""Main Textual application for sandbox-tui."""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane, Tabs

from sandbox.tui.users import UsersPane
from sandbox.tui.groups import GroupsPane
from sandbox.tui.profiles import ProfilesPane


class SandboxApp(App):
    TITLE = "sandbox-tui"

    CSS = """
    #tab-hint {
        dock: right;
        height: 3;
        width: auto;
        padding: 0 2;
        color: $text-muted;
        content-align: center middle;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self) -> None:
        super().__init__()
        from sandbox.config import load_config
        self._cfg = load_config()

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="users"):
            with TabPane("Users", id="users"):
                yield UsersPane()
            with TabPane("Groups", id="groups"):
                yield GroupsPane()
            with TabPane("Profiles", id="profiles"):
                yield ProfilesPane()
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(UsersPane).load(self._cfg)
        self.call_after_refresh(self._inject_tab_hint)

    def _inject_tab_hint(self) -> None:
        hint = Static("Tab: switch focus between table and tabs  •  also mouse clickable", id="tab-hint")
        self.query_one(Tabs).mount(hint)

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        tab_id = event.tab.id if event.tab else ""
        if "users" in tab_id:
            self.query_one(UsersPane).query_one("DataTable").focus()
        elif "groups" in tab_id:
            pane = self.query_one(GroupsPane)
            if pane._cfg is None:
                pane.load(self._cfg)
            else:
                pane._reload()
            pane.query_one("DataTable").focus()
        elif "profiles" in tab_id:
            pane = self.query_one(ProfilesPane)
            if not pane._loaded:
                pane.load(self._cfg)
            else:
                pane._reload()
            pane.query_one("DataTable").focus()

    def action_refresh(self) -> None:
        tabbed = self.query_one(TabbedContent)
        active = tabbed.active
        if active == "users":
            self.query_one(UsersPane)._reload()
        elif active == "groups":
            self.query_one(GroupsPane)._reload()
        elif active == "profiles":
            self.query_one(ProfilesPane)._reload()


def main() -> None:
    app = SandboxApp()
    app.run()


if __name__ == "__main__":
    main()
