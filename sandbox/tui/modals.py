"""Reusable modal screens for sandbox-tui."""
from __future__ import annotations

import io
import contextlib
from pathlib import Path

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import (
    Button, Checkbox, DataTable, Input, Label, RadioButton, RadioSet, RichLog, Static, TextArea,
)
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual import on


class OutputScreen(ModalScreen[bool]):
    """Show text output; optionally ask for confirmation."""

    DEFAULT_CSS = """
    OutputScreen {
        align: center middle;
    }
    OutputScreen > Vertical {
        width: 85%;
        height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    OutputScreen RichLog {
        height: 1fr;
    }
    OutputScreen Horizontal {
        height: auto;
        margin-top: 1;
        align: center middle;
    }
    OutputScreen Button {
        margin: 0 1;
    }
    """

    def __init__(self, text: str, confirm: bool = False) -> None:
        super().__init__()
        self._text = text
        self._confirm = confirm

    def compose(self) -> ComposeResult:
        with Vertical():
            yield RichLog(id="log", wrap=True, highlight=True)
            with Horizontal():
                if self._confirm:
                    yield Button("Confirm", variant="success", id="confirm")
                    yield Button("Cancel", variant="error", id="cancel")
                else:
                    yield Button("OK", id="ok")

    def on_mount(self) -> None:
        self.query_one(RichLog).write(self._text)
        self.query_one(Button).focus()

    @on(Button.Pressed, "#ok")
    def ok(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#confirm")
    def confirm(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(False)


class ConfirmDeleteScreen(ModalScreen[tuple[bool, bool]]):
    """Show audit info and require the user to type the name to confirm deletion.

    Dismisses (confirmed, force). force is always False when show_force=False.
    """

    DEFAULT_CSS = """
    ConfirmDeleteScreen {
        align: center middle;
    }
    ConfirmDeleteScreen > Vertical {
        width: 75%;
        height: 70%;
        background: $surface;
        border: thick $error;
        padding: 1 2;
    }
    ConfirmDeleteScreen RichLog {
        height: 1fr;
    }
    ConfirmDeleteScreen Static {
        height: auto;
        margin-top: 1;
    }
    ConfirmDeleteScreen Input {
        margin-top: 1;
    }
    ConfirmDeleteScreen Checkbox {
        margin-top: 1;
    }
    ConfirmDeleteScreen Horizontal {
        height: auto;
        margin-top: 1;
        align: center middle;
    }
    ConfirmDeleteScreen Button {
        margin: 0 1;
    }
    """

    def __init__(self, name: str, audit_text: str, show_force: bool = False) -> None:
        super().__init__()
        self._name = name
        self._audit_text = audit_text
        self._show_force = show_force

    def compose(self) -> ComposeResult:
        with Vertical():
            yield RichLog(id="log", wrap=True)
            yield Static(f"Type [bold]{self._name!r}[/bold] to confirm deletion:")
            yield Input(id="confirm-input", placeholder=self._name)
            if self._show_force:
                yield Checkbox("Force (kill running processes)", id="force")
            with Horizontal():
                yield Button("Delete", variant="error", id="delete")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one(RichLog).write(self._audit_text)
        self.query_one(Input).focus()

    @on(Button.Pressed, "#delete")
    def delete(self) -> None:
        val = self.query_one("#confirm-input", Input).value
        if val == self._name:
            force = self.query_one("#force", Checkbox).value if self._show_force else False
            self.dismiss((True, force))
        else:
            self.notify(f"Type exactly '{self._name}' to confirm", severity="warning")

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss((False, False))

    @on(Input.Submitted, "#confirm-input")
    def on_input_submitted(self) -> None:
        self.delete()


class CreateUserScreen(ModalScreen[bool]):
    """Form to create a new sandboxed user."""

    DEFAULT_CSS = """
    CreateUserScreen {
        align: center middle;
    }
    CreateUserScreen > ScrollableContainer {
        width: 70%;
        max-height: 85%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    CreateUserScreen Label {
        margin-top: 1;
    }
    CreateUserScreen Input {
        margin-top: 0;
    }
    CreateUserScreen Checkbox {
        margin-top: 0;
    }
    CreateUserScreen #profile-list {
        height: auto;
        max-height: 6;
        border: solid $secondary;
        padding: 0 1;
        margin-top: 0;
    }
    CreateUserScreen #groups-list {
        height: auto;
        max-height: 8;
        border: solid $secondary;
        padding: 0 1;
        margin-top: 0;
    }
    CreateUserScreen #paths-table {
        height: auto;
        max-height: 6;
        border: solid $secondary;
        margin-top: 0;
    }
    CreateUserScreen .paths-row {
        height: auto;
        margin-top: 0;
    }
    CreateUserScreen Horizontal {
        height: auto;
        margin-top: 1;
        align: center middle;
    }
    CreateUserScreen Button {
        margin: 0 1;
    }
    """

    def __init__(self, cfg) -> None:
        super().__init__()
        self._cfg = cfg
        from sandbox.groups import list_groups
        from sandbox.profiles import list_profiles
        self._all_groups = [g["groupname"] for g in list_groups(cfg)]
        self._profiles = list_profiles(cfg.project_root / "profiles")
        self._extra_paths: list[str] = []

    def _selected_profile(self) -> str:
        """Return selected profile name, or empty string if none selected."""
        if not self._profiles:
            return ""
        try:
            rs = self.query_one("#profile-radioset", RadioSet)
            btn = rs.pressed_button
            if btn is None:
                return ""
            btn_id = btn.id or ""
            return btn_id[5:] if btn_id.startswith("prof-") else ""
        except Exception:
            return ""

    def compose(self) -> ComposeResult:
        with ScrollableContainer():
            yield Label("[bold]Create User[/bold]")
            yield Input(id="username", placeholder="Username (required)")
            yield Label("Profile (optional):")
            with ScrollableContainer(id="profile-list"):
                if self._profiles:
                    with RadioSet(id="profile-radioset"):
                        for p in self._profiles:
                            label = p["name"] + (f"  — {p['description']}" if p["description"] else "")
                            yield RadioButton(label, id=f"prof-{p['name']}", value=False)
                else:
                    yield Label("(no profiles available)")
            yield Label("Extra groups:")
            with ScrollableContainer(id="groups-list"):
                if self._all_groups:
                    for g in self._all_groups:
                        yield Checkbox(g, id=f"eg-{g}")
                else:
                    yield Label("(no managed groups exist)")
            yield Label("Extra host paths — one path per entry (exposed read-only):")
            yield DataTable(id="paths-table", cursor_type="row")
            with Horizontal(classes="paths-row"):
                yield Input(id="paths-input", placeholder="one path, e.g. /home/linuxbrew/.linuxbrew")
                yield Button("Add", id="paths-add")
                yield Button("Remove", id="paths-remove")
            yield Input(id="comment", placeholder="GECOS comment")
            yield Checkbox("No /usr in sandbox", id="no-usr")
            yield Checkbox("Mount /etc and /run read-only (sys-dirs)", id="sys-dirs")
            yield Checkbox("Fake sudo shim (exec wrapper, no privilege gain)", id="fake-sudo")
            yield Label("Network:")
            with RadioSet(id="network"):
                yield RadioButton("Full", value=True)
                yield RadioButton("Loopback")
                yield RadioButton("None")
            yield Label("Resource limits (leave blank to skip):")
            yield Input(id="max-procs", placeholder="Max processes (ulimit -u)")
            yield Input(id="max-fsize", placeholder="Max file size MB (ulimit -f)")
            yield Input(id="max-nofile", placeholder="Max open FDs (ulimit -n)")
            yield Input(id="cgroup-mem", placeholder="Memory cap (e.g. 512M)")
            yield Input(id="cgroup-cpu", placeholder="CPU quota (e.g. 50%)")
            with Horizontal():
                yield Button("Preview", id="preview")
                yield Button("Create", variant="success", id="create")
                yield Button("Cancel", variant="error", id="cancel")

    def on_mount(self) -> None:
        t = self.query_one("#paths-table", DataTable)
        t.add_column("HOST PATH")
        self.query_one("#username", Input).focus()

    def _paths_add(self) -> None:
        inp = self.query_one("#paths-input", Input)
        value = inp.value.strip()
        if not value:
            return
        self._extra_paths.append(value)
        self.query_one("#paths-table", DataTable).add_row(value)
        inp.value = ""

    def _paths_remove(self) -> None:
        table = self.query_one("#paths-table", DataTable)
        if table.row_count == 0:
            return
        row = table.cursor_row
        cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        table.remove_row(cell_key.row_key)
        if 0 <= row < len(self._extra_paths):
            self._extra_paths.pop(row)

    @on(Button.Pressed, "#paths-add")
    def paths_add(self) -> None:
        self._paths_add()

    @on(Button.Pressed, "#paths-remove")
    def paths_remove(self) -> None:
        self._paths_remove()

    @on(Input.Submitted, "#paths-input")
    def paths_input_submitted(self) -> None:
        self._paths_add()

    def _flush_paths_input(self) -> None:
        """Auto-add any path sitting in the input field (user didn't press Add/Enter)."""
        pending = self.query_one("#paths-input", Input).value.strip()
        if pending and pending not in self._extra_paths:
            self._extra_paths.append(pending)
            self.query_one("#paths-table", DataTable).add_row(pending)
            self.query_one("#paths-input", Input).value = ""

    def _build_user_cfg(self):
        from sandbox.models import UserConfig
        self._flush_paths_input()
        network_labels = {"Full": "full", "Loopback": "loopback", "None": "none"}
        radio = self.query_one("#network", RadioSet)
        net_label = str(radio.pressed_button.label) if radio.pressed_button else "Full"
        extra_groups = [
            g for g in self._all_groups
            if self.query_one(f"#eg-{g}", Checkbox).value
        ]
        return UserConfig(
            username=self.query_one("#username", Input).value.strip(),
            no_usr=self.query_one("#no-usr", Checkbox).value,
            sys_dirs=self.query_one("#sys-dirs", Checkbox).value,
            network=network_labels.get(net_label, "full"),
            max_procs=self.query_one("#max-procs", Input).value.strip(),
            max_fsize=self.query_one("#max-fsize", Input).value.strip(),
            max_nofile=self.query_one("#max-nofile", Input).value.strip(),
            cgroup_mem=self.query_one("#cgroup-mem", Input).value.strip(),
            cgroup_cpu=self.query_one("#cgroup-cpu", Input).value.strip(),
            comment=self.query_one("#comment", Input).value.strip(),
            extra_groups=extra_groups,
            fake_sudo=self.query_one("#fake-sudo", Checkbox).value,
            extra_paths=list(self._extra_paths),
        )

    @on(Button.Pressed, "#preview")
    def preview(self) -> None:
        from sandbox.config import SandboxError
        user_cfg = self._build_user_cfg()
        if not user_cfg.username:
            self.notify("Username is required", severity="error")
            return
        profile_name = self._selected_profile()
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                if profile_name:
                    from sandbox.profiles import apply_profile
                    apply_profile(self._cfg, profile_name, user_cfg.username, dry_run=True)
                else:
                    from sandbox.users import create_user
                    create_user(self._cfg, user_cfg, dry_run=True)
        except (SandboxError, ValueError, FileNotFoundError) as e:
            self.app.push_screen(OutputScreen(f"Error: {e}"))
            return
        self.app.push_screen(OutputScreen(buf.getvalue() or "(no output)"))

    def _apply_extra_paths(self, username: str) -> None:
        """Merge self._extra_paths into the user's extra-mounts and regenerate launcher."""
        if not self._extra_paths:
            return
        from sandbox.state import read_extra_mounts, write_extra_mounts
        from sandbox.models import MountEntry
        from sandbox.launcher import generate_launcher
        existing = read_extra_mounts(self._cfg.users_dir, username)
        seen = {(m.source, m.dest) for m in existing}
        new = [MountEntry("--ro-bind", p, p) for p in self._extra_paths if (p, p) not in seen]
        if new:
            write_extra_mounts(self._cfg.users_dir, username, existing + new)
            generate_launcher(self._cfg.launcher_dir, self._cfg.users_dir, username)

    @on(Button.Pressed, "#create")
    def create(self) -> None:
        from sandbox.config import SandboxError
        user_cfg = self._build_user_cfg()
        if not user_cfg.username:
            self.notify("Username is required", severity="error")
            return
        profile_name = self._selected_profile()
        try:
            if profile_name:
                from sandbox.profiles import apply_profile
                apply_profile(self._cfg, profile_name, user_cfg.username, dry_run=False)
                self._apply_extra_paths(user_cfg.username)
                self.notify(f"Profile '{profile_name}' applied to '{user_cfg.username}'.")
            else:
                from sandbox.users import create_user
                create_user(self._cfg, user_cfg, dry_run=False)
                self.notify(f"User '{user_cfg.username}' created.")
            self.dismiss(True)
        except (SandboxError, ValueError, FileNotFoundError) as e:
            self.app.push_screen(OutputScreen(f"Error: {e}"))

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(False)


class CreateGroupScreen(ModalScreen[bool]):
    """Form to create a new shared group."""

    DEFAULT_CSS = """
    CreateGroupScreen {
        align: center middle;
    }
    CreateGroupScreen > Vertical {
        width: 55%;
        height: auto;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    CreateGroupScreen Label {
        margin-top: 1;
    }
    CreateGroupScreen Horizontal {
        height: auto;
        margin-top: 1;
        align: center middle;
    }
    CreateGroupScreen Button {
        margin: 0 1;
    }
    """

    def __init__(self, cfg) -> None:
        super().__init__()
        self._cfg = cfg

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[bold]Create Group[/bold]")
            yield Input(id="groupname", placeholder="Group name (required)")
            yield Label("Group directory permissions (owner always rwx, others 0):")
            yield Checkbox("group read", id="g-r", value=True)
            yield Checkbox("group write", id="g-w", value=True)
            yield Checkbox("group execute", id="g-x", value=True)
            yield Checkbox("setgid bit", id="g-s")
            with Horizontal():
                yield Button("Create", variant="success", id="create")
                yield Button("Cancel", variant="error", id="cancel")

    def _build_mode(self) -> str:
        bits = ""
        if self.query_one("#g-r", Checkbox).value:
            bits += "r"
        if self.query_one("#g-w", Checkbox).value:
            bits += "w"
        if self.query_one("#g-x", Checkbox).value:
            bits += "x"
        if self.query_one("#g-s", Checkbox).value:
            bits += "s"
        return f"u=rwx,g={bits},o="

    @on(Button.Pressed, "#create")
    def create(self) -> None:
        from sandbox.groups import create_group
        from sandbox.config import SandboxError
        name = self.query_one("#groupname", Input).value.strip()
        if not name:
            self.notify("Group name is required", severity="error")
            return
        mode = self._build_mode()
        try:
            create_group(self._cfg, name, mode, dry_run=False)
            self.notify(f"Group '{name}' created.")
            self.dismiss(True)
        except (SandboxError, ValueError) as e:
            self.app.push_screen(OutputScreen(f"Error: {e}"))

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(False)


class InstallScreen(ModalScreen[bool]):
    """Install a binary into a sandbox user's environment."""

    DEFAULT_CSS = """
    InstallScreen {
        align: center middle;
    }
    InstallScreen > Vertical {
        width: 60%;
        height: auto;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    InstallScreen Label {
        margin-top: 1;
    }
    InstallScreen Horizontal {
        height: auto;
        margin-top: 1;
        align: center middle;
    }
    InstallScreen Button {
        margin: 0 1;
    }
    """

    def __init__(self, cfg, username: str) -> None:
        super().__init__()
        self._cfg = cfg
        self._username = username

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"[bold]Install binary into sandbox '{self._username}'[/bold]")
            yield Input(id="binary", placeholder="Binary path (required)")
            yield Input(id="dest", placeholder="Destination inside sandbox (optional)")
            with Horizontal():
                yield Button("Preview", id="preview")
                yield Button("Install", variant="success", id="install")
                yield Button("Cancel", variant="error", id="cancel")

    @on(Button.Pressed, "#preview")
    def preview(self) -> None:
        from sandbox.installs import install_binary
        from sandbox.config import SandboxError
        binary = self.query_one("#binary", Input).value.strip()
        dest = self.query_one("#dest", Input).value.strip()
        if not binary:
            self.notify("Binary path is required", severity="error")
            return
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                install_binary(self._cfg, self._username, Path(binary), dest, dry_run=True)
        except (SandboxError, ValueError) as e:
            self.app.push_screen(OutputScreen(f"Error: {e}"))
            return
        self.app.push_screen(OutputScreen(buf.getvalue() or "(no output)"))

    @on(Button.Pressed, "#install")
    def install(self) -> None:
        from sandbox.installs import install_binary
        from sandbox.config import SandboxError
        binary = self.query_one("#binary", Input).value.strip()
        dest = self.query_one("#dest", Input).value.strip()
        if not binary:
            self.notify("Binary path is required", severity="error")
            return
        try:
            install_binary(self._cfg, self._username, Path(binary), dest, dry_run=False)
            self.notify(f"Installed {binary} into '{self._username}'.")
            self.dismiss(True)
        except (SandboxError, ValueError) as e:
            self.app.push_screen(OutputScreen(f"Error: {e}"))

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(False)


class MembershipScreen(ModalScreen[bool]):
    """Manage group memberships for a user via checkboxes."""

    DEFAULT_CSS = """
    MembershipScreen {
        align: center middle;
    }
    MembershipScreen > Vertical {
        width: 60%;
        height: 75%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    MembershipScreen Label {
        height: auto;
        margin-bottom: 1;
    }
    MembershipScreen ScrollableContainer {
        height: 1fr;
        border: solid $secondary;
        padding: 0 1;
    }
    MembershipScreen Horizontal {
        height: auto;
        margin-top: 1;
        align: center middle;
    }
    MembershipScreen Button {
        margin: 0 1;
    }
    """

    def __init__(self, cfg, username: str, current_groups: list[str], all_groups: list[str]) -> None:
        super().__init__()
        self._cfg = cfg
        self._username = username
        self._original = set(current_groups)
        self._all_groups = all_groups

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"[bold]Group memberships for '{self._username}'[/bold]")
            with ScrollableContainer():
                if self._all_groups:
                    for g in self._all_groups:
                        yield Checkbox(g, value=(g in self._original), id=f"grp-{g}")
                else:
                    yield Label("(no shared groups exist)")
            with Horizontal():
                yield Button("Apply", variant="success", id="apply")
                yield Button("Cancel", id="cancel")

    @on(Button.Pressed, "#apply")
    def apply(self) -> None:
        from sandbox.membership import add_member, remove_member
        from sandbox.config import SandboxError
        new_groups: set[str] = set()
        for g in self._all_groups:
            if self.query_one(f"#grp-{g}", Checkbox).value:
                new_groups.add(g)
        errors: list[str] = []
        for g in new_groups - self._original:
            try:
                add_member(self._cfg, self._username, g)
            except (SandboxError, Exception) as e:
                errors.append(f"add {g}: {e}")
        for g in self._original - new_groups:
            try:
                remove_member(self._cfg, self._username, g)
            except (SandboxError, Exception) as e:
                errors.append(f"remove {g}: {e}")
        if errors:
            self.app.push_screen(OutputScreen("Errors:\n" + "\n".join(errors)))
        else:
            self.dismiss(True)

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(False)


class ChmodScreen(ModalScreen[bool]):
    """Change group directory permissions via checkboxes (owner=rwx, others=0 fixed)."""

    DEFAULT_CSS = """
    ChmodScreen {
        align: center middle;
    }
    ChmodScreen > Vertical {
        width: 55%;
        height: auto;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    ChmodScreen Label {
        margin-top: 1;
    }
    ChmodScreen Horizontal {
        height: auto;
        margin-top: 1;
        align: center middle;
    }
    ChmodScreen Button {
        margin: 0 1;
    }
    """

    def __init__(self, cfg, groupname: str, current_mode: str = "") -> None:
        super().__init__()
        self._cfg = cfg
        self._groupname = groupname
        # current_mode is an octal string e.g. '0o750'; parse group bits
        try:
            bits = int(current_mode, 8) if current_mode else 0
        except ValueError:
            bits = 0
        self._g_r = bool(bits & 0o040)
        self._g_w = bool(bits & 0o020)
        self._g_x = bool(bits & 0o010)
        self._g_s = bool(bits & 0o2000)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"[bold]Permissions for group '{self._groupname}'[/bold]")
            yield Label("Owner: rwx  |  Others: ---  (fixed)")
            yield Label("Group bits:")
            yield Checkbox("group read", id="g-r", value=self._g_r)
            yield Checkbox("group write", id="g-w", value=self._g_w)
            yield Checkbox("group execute", id="g-x", value=self._g_x)
            yield Checkbox("setgid bit", id="g-s", value=self._g_s)
            with Horizontal():
                yield Button("Apply", variant="success", id="apply")
                yield Button("Cancel", id="cancel")

    def _build_mode(self) -> str:
        bits = ""
        if self.query_one("#g-r", Checkbox).value:
            bits += "r"
        if self.query_one("#g-w", Checkbox).value:
            bits += "w"
        if self.query_one("#g-x", Checkbox).value:
            bits += "x"
        if self.query_one("#g-s", Checkbox).value:
            bits += "s"
        return f"u=rwx,g={bits},o="

    @on(Button.Pressed, "#apply")
    def apply(self) -> None:
        import subprocess
        group_dir = self._cfg.groups_dir / self._groupname / f"{self._groupname}.group-dir"
        if not group_dir.is_dir():
            self.notify(f"Group directory not found: {group_dir}", severity="error")
            return
        mode = self._build_mode()
        try:
            subprocess.run(["chmod", mode, str(group_dir)], check=True)
            self.notify(f"Permissions updated for '{self._groupname}'.")
            self.dismiss(True)
        except subprocess.CalledProcessError as e:
            self.app.push_screen(OutputScreen(f"chmod failed: {e}"))

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(False)


class ConfirmDeleteProfileScreen(ModalScreen[bool]):
    """Confirm deletion of a profile by typing its name."""

    DEFAULT_CSS = """
    ConfirmDeleteProfileScreen {
        align: center middle;
    }
    ConfirmDeleteProfileScreen > Vertical {
        width: 60%;
        height: auto;
        background: $surface;
        border: thick $error;
        padding: 1 2;
    }
    ConfirmDeleteProfileScreen Static {
        height: auto;
        margin-bottom: 1;
    }
    ConfirmDeleteProfileScreen Input {
        margin-top: 1;
    }
    ConfirmDeleteProfileScreen Horizontal {
        height: auto;
        margin-top: 1;
        align: center middle;
    }
    ConfirmDeleteProfileScreen Button {
        margin: 0 1;
    }
    """

    def __init__(self, profiles_dir, name: str) -> None:
        super().__init__()
        self._profiles_dir = profiles_dir
        self._name = name

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"Delete profile [bold]{self._name!r}[/bold]? This cannot be undone.")
            yield Label(f"Type [bold]{self._name!r}[/bold] to confirm:")
            yield Input(id="confirm-input", placeholder=self._name)
            with Horizontal():
                yield Button("Delete", variant="error", id="delete")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    @on(Button.Pressed, "#delete")
    def delete(self) -> None:
        val = self.query_one("#confirm-input", Input).value
        if val != self._name:
            self.notify(f"Type exactly '{self._name}' to confirm", severity="warning")
            return
        from sandbox.profiles import delete_profile
        try:
            delete_profile(self._profiles_dir, self._name)
            self.dismiss(True)
        except Exception as e:
            self.app.push_screen(OutputScreen(f"Error: {e}"))

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(False)

    @on(Input.Submitted, "#confirm-input")
    def on_input_submitted(self) -> None:
        self.delete()


class CreateProfileScreen(ModalScreen[bool]):
    """Create a new profile from scratch or by cloning an existing one."""

    DEFAULT_CSS = """
    CreateProfileScreen {
        align: center middle;
    }
    CreateProfileScreen > ScrollableContainer {
        width: 75%;
        max-height: 90%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    CreateProfileScreen Label {
        margin-top: 1;
    }
    CreateProfileScreen Input {
        margin-top: 0;
    }
    CreateProfileScreen #groups-list {
        height: auto;
        max-height: 8;
        border: solid $secondary;
        padding: 0 1;
        margin-top: 0;
    }
    CreateProfileScreen .list-table {
        height: auto;
        max-height: 6;
        border: solid $secondary;
        margin-top: 0;
    }
    CreateProfileScreen #paths-table {
        height: auto;
        max-height: 6;
        border: solid $secondary;
        margin-top: 0;
    }
    CreateProfileScreen .list-row {
        height: auto;
        margin-top: 0;
    }
    CreateProfileScreen TextArea {
        height: 5;
        margin-top: 0;
        border: solid $secondary;
    }
    CreateProfileScreen Horizontal {
        height: auto;
        margin-top: 1;
        align: center middle;
    }
    CreateProfileScreen Button {
        margin: 0 1;
    }
    """

    def __init__(self, cfg, source_profile=None) -> None:
        super().__init__()
        self._cfg = cfg
        self._source = source_profile
        self._profiles_dir = cfg.project_root / "profiles"
        self._inherited_dotfiles: list[str] = []
        if source_profile is not None:
            src_dotfiles_dir = self._profiles_dir / source_profile.name / "dotfiles"
            if src_dotfiles_dir.is_dir():
                self._inherited_dotfiles = [f.name for f in sorted(src_dotfiles_dir.iterdir()) if f.is_file()]
        from sandbox.groups import list_groups
        self._all_groups = [g["groupname"] for g in list_groups(cfg)]

    def compose(self) -> ComposeResult:
        src = self._source
        title = f"[bold]Clone: {src.name}[/bold]" if src else "[bold]Create Profile[/bold]"
        with ScrollableContainer():
            yield Label(title)

            yield Label("Profile name:")
            yield Input(
                id="prof-name",
                placeholder="e.g. my-profile",
                value=f"{src.name}-copy" if src else "",
            )
            yield Label("Description:")
            yield Input(
                id="prof-desc",
                placeholder="Short description",
                value=src.description if src else "",
            )

            yield Label("[bold]User settings[/bold]")
            yield Checkbox(
                "No /usr in sandbox",
                id="no-usr",
                value=src.user.no_usr if src else False,
            )
            yield Checkbox(
                "Mount /etc and /run read-only (sys-dirs)",
                id="sys-dirs",
                value=src.user.sys_dirs if src else False,
            )
            yield Checkbox(
                "Fake sudo shim (exec wrapper, no privilege gain)",
                id="fake-sudo",
                value=src.user.fake_sudo if src else False,
            )
            yield Label("Network:")
            with RadioSet(id="network"):
                yield RadioButton("Full", value=(src is None or src.user.network == "full"))
                yield RadioButton("Loopback", value=(src is not None and src.user.network == "loopback"))
                yield RadioButton("None", value=(src is not None and src.user.network == "none"))
            yield Label("Hostname:")
            yield Input(
                id="hostname",
                placeholder="Leave blank for default",
                value=src.hostname if src else "",
            )
            yield Label("Resource limits (leave blank to skip):")
            yield Input(id="max-procs", placeholder="Max processes (ulimit -u)", value=src.user.max_procs if src else "")
            yield Input(id="max-fsize", placeholder="Max file size MB (ulimit -f)", value=src.user.max_fsize if src else "")
            yield Input(id="max-nofile", placeholder="Max open FDs (ulimit -n)", value=src.user.max_nofile if src else "")
            yield Input(id="cgroup-mem", placeholder="Memory cap (e.g. 512M)", value=src.user.cgroup_mem if src else "")
            yield Input(id="cgroup-cpu", placeholder="CPU quota (e.g. 50%)", value=src.user.cgroup_cpu if src else "")
            yield Input(id="comment", placeholder="GECOS comment", value=src.user.comment if src else "")

            yield Label("Extra groups:")
            with ScrollableContainer(id="groups-list"):
                if self._all_groups:
                    for g in self._all_groups:
                        checked = src is not None and g in src.user.extra_groups
                        yield Checkbox(g, id=f"eg-{g}", value=checked)
                else:
                    yield Label("(no managed groups exist)")

            yield Label("Shadow paths:")
            yield DataTable(id="shadow-table", cursor_type="row", classes="list-table")
            with Horizontal(classes="list-row"):
                yield Input(id="shadow-input", placeholder="/path/to/shadow")
                yield Button("Add", id="shadow-add")
                yield Button("Remove", id="shadow-remove")

            yield Label("Install entries (host-path[:dest]):")
            yield DataTable(id="install-table", cursor_type="row", classes="list-table")
            with Horizontal(classes="list-row"):
                yield Input(id="install-input", placeholder="/usr/bin/curl or /usr/bin/curl:/usr/local/bin/curl")
                yield Button("Add", id="install-add")
                yield Button("Remove", id="install-remove")

            if src:
                yield Label("Dotfiles (inherited basenames shown; add new as full host paths):")
            else:
                yield Label("Dotfiles (full host paths — copied to profile on save):")
            yield DataTable(id="dotfiles-table", cursor_type="row", classes="list-table")
            with Horizontal(classes="list-row"):
                yield Input(id="dotfiles-input", placeholder="/home/user/.bashrc")
                yield Button("Add", id="dotfiles-add")
                yield Button("Remove", id="dotfiles-remove")

            yield Label("Extra host paths — one path per entry (exposed read-only in sandbox):")
            yield DataTable(id="paths-table", cursor_type="row", classes="list-table")
            with Horizontal(classes="list-row"):
                yield Input(id="paths-input", placeholder="one path, e.g. /home/linuxbrew/.linuxbrew")
                yield Button("Add", id="paths-add")
                yield Button("Remove", id="paths-remove")

            yield Label("[bold]Scripts[/bold]")
            yield Label("Post-setup (runs as root after user creation):")
            yield TextArea(src.post_setup if src else "", id="post-setup")
            yield Label("On-enter (sourced inside sandbox on login):")
            yield TextArea(src.on_enter if src else "", id="on-enter")

            with Horizontal():
                yield Button("Preview", id="preview")
                yield Button("Save", variant="success", id="save")
                yield Button("Cancel", variant="error", id="cancel")

    def on_mount(self) -> None:
        src = self._source

        st = self.query_one("#shadow-table", DataTable)
        st.add_column("PATH")
        if src:
            for p in src.shadow_paths:
                st.add_row(p)

        it = self.query_one("#install-table", DataTable)
        it.add_column("ENTRY")
        if src:
            for e in src.install_entries:
                it.add_row(e)

        dt = self.query_one("#dotfiles-table", DataTable)
        dt.add_column("PATH / BASENAME")
        for basename in self._inherited_dotfiles:
            dt.add_row(basename)

        pt = self.query_one("#paths-table", DataTable)
        pt.add_column("HOST PATH")
        if src:
            for m in src.bind_entries:
                if m.kind == "--ro-bind" and m.source == m.dest:
                    pt.add_row(m.source)

    def _list_add(self, table_id: str, input_id: str) -> None:
        inp = self.query_one(f"#{input_id}", Input)
        value = inp.value.strip()
        if not value:
            return
        table = self.query_one(f"#{table_id}", DataTable)
        table.add_row(value)
        inp.value = ""

    def _list_remove(self, table_id: str) -> None:
        table = self.query_one(f"#{table_id}", DataTable)
        if table.row_count == 0:
            return
        cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        table.remove_row(cell_key.row_key)

    @on(Button.Pressed, "#shadow-add")
    def shadow_add(self) -> None:
        self._list_add("shadow-table", "shadow-input")

    @on(Button.Pressed, "#shadow-remove")
    def shadow_remove(self) -> None:
        self._list_remove("shadow-table")

    @on(Button.Pressed, "#install-add")
    def install_add(self) -> None:
        self._list_add("install-table", "install-input")

    @on(Button.Pressed, "#install-remove")
    def install_remove(self) -> None:
        self._list_remove("install-table")

    @on(Button.Pressed, "#dotfiles-add")
    def dotfiles_add(self) -> None:
        self._list_add("dotfiles-table", "dotfiles-input")

    @on(Button.Pressed, "#dotfiles-remove")
    def dotfiles_remove(self) -> None:
        self._list_remove("dotfiles-table")

    @on(Input.Submitted, "#shadow-input")
    def shadow_input_submitted(self) -> None:
        self._list_add("shadow-table", "shadow-input")

    @on(Input.Submitted, "#install-input")
    def install_input_submitted(self) -> None:
        self._list_add("install-table", "install-input")

    @on(Input.Submitted, "#dotfiles-input")
    def dotfiles_input_submitted(self) -> None:
        self._list_add("dotfiles-table", "dotfiles-input")

    @on(Button.Pressed, "#paths-add")
    def paths_add(self) -> None:
        self._list_add("paths-table", "paths-input")

    @on(Button.Pressed, "#paths-remove")
    def paths_remove(self) -> None:
        self._list_remove("paths-table")

    @on(Input.Submitted, "#paths-input")
    def paths_input_submitted(self) -> None:
        self._list_add("paths-table", "paths-input")

    def _read_table_rows(self, table_id: str) -> list[str]:
        from textual.coordinate import Coordinate
        table = self.query_one(f"#{table_id}", DataTable)
        return [str(table.get_cell_at(Coordinate(i, 0))) for i in range(table.row_count)]

    def _flush_paths_input(self) -> None:
        pending = self.query_one("#paths-input", Input).value.strip()
        if pending:
            self._list_add("paths-table", "paths-input")

    def _build_profile(self, name: str) -> "Profile":
        self._flush_paths_input()
        from sandbox.models import UserConfig, Profile, MountEntry
        network_map = {"Full": "full", "Loopback": "loopback", "None": "none"}
        radio = self.query_one("#network", RadioSet)
        net_label = str(radio.pressed_button.label) if radio.pressed_button else "Full"
        hostname = self.query_one("#hostname", Input).value.strip()
        return Profile(
            name=name,
            description=self.query_one("#prof-desc", Input).value.strip(),
            user=UserConfig(
                username="",
                no_usr=self.query_one("#no-usr", Checkbox).value,
                sys_dirs=self.query_one("#sys-dirs", Checkbox).value,
                network=network_map.get(net_label, "full"),
                max_procs=self.query_one("#max-procs", Input).value.strip(),
                max_fsize=self.query_one("#max-fsize", Input).value.strip(),
                max_nofile=self.query_one("#max-nofile", Input).value.strip(),
                cgroup_mem=self.query_one("#cgroup-mem", Input).value.strip(),
                cgroup_cpu=self.query_one("#cgroup-cpu", Input).value.strip(),
                comment=self.query_one("#comment", Input).value.strip(),
                extra_groups=[g for g in self._all_groups if self.query_one(f"#eg-{g}", Checkbox).value],
                fake_sudo=self.query_one("#fake-sudo", Checkbox).value,
            ),
            hostname=hostname,
            bind_entries=[
                MountEntry("--ro-bind", p, p)
                for p in self._read_table_rows("paths-table")
            ],
            shadow_paths=self._read_table_rows("shadow-table"),
            install_entries=self._read_table_rows("install-table"),
            dotfiles=[],
            post_setup=self.query_one("#post-setup", TextArea).text,
            on_enter=self.query_one("#on-enter", TextArea).text,
        )

    def _validate(self, name: str) -> str | None:
        import re
        if not name:
            return "Profile name is required"
        if not re.fullmatch(r"[a-z0-9_-]+", name):
            return "Profile name must match ^[a-z0-9_-]+$"
        if (self._profiles_dir / name).exists():
            return f"Profile '{name}' already exists"
        dotfile_entries = self._read_table_rows("dotfiles-table")
        seen_basenames: set[str] = set()
        for entry in dotfile_entries:
            basename = Path(entry).name if "/" in entry else entry
            if basename in seen_basenames:
                return f"Duplicate dotfile basename: '{basename}'"
            seen_basenames.add(basename)
            if "/" in entry and not Path(entry).exists():
                return f"Dotfile not found: '{entry}'"
        return None

    @on(Button.Pressed, "#preview")
    def preview(self) -> None:
        name = self.query_one("#prof-name", Input).value.strip()
        profile = self._build_profile(name or "<name>")
        lines = [f"Would write profiles/{name or '<name>'}/profile.conf:\n"]
        lines.append("[meta]")
        if profile.description:
            lines.append(f"  description = {profile.description}")
        lines.append("[user]")
        lines.append(f"  no-usr = {profile.user.no_usr}")
        lines.append(f"  sys-dirs = {profile.user.sys_dirs}")
        lines.append(f"  network = {profile.user.network}")
        if profile.hostname:
            lines.append(f"  hostname = {profile.hostname}")
        for k, v in [
            ("max-procs", profile.user.max_procs),
            ("max-fsize", profile.user.max_fsize),
            ("max-nofile", profile.user.max_nofile),
            ("cgroup-mem", profile.user.cgroup_mem),
            ("cgroup-cpu", profile.user.cgroup_cpu),
            ("comment", profile.user.comment),
        ]:
            if v:
                lines.append(f"  {k} = {v}")
        if profile.user.extra_groups:
            lines.append(f"  extra-groups = {','.join(profile.user.extra_groups)}")
        if profile.shadow_paths:
            lines.append("[shadow]")
            for p in profile.shadow_paths:
                lines.append(f"  {p}")
        if profile.install_entries:
            lines.append("[install]")
            for e in profile.install_entries:
                lines.append(f"  {e}")
        dotfile_entries = self._read_table_rows("dotfiles-table")
        if dotfile_entries:
            lines.append("[dotfiles]")
            for entry in dotfile_entries:
                basename = Path(entry).name if "/" in entry else entry
                lines.append(f"  {basename}")
            lines.append("\nDotfile copy operations:")
            for entry in dotfile_entries:
                if "/" in entry:
                    basename = Path(entry).name
                    lines.append(f"  copy {entry} -> profiles/{name}/dotfiles/{basename}")
                elif self._source:
                    lines.append(f"  copy profiles/{self._source.name}/dotfiles/{entry} -> profiles/{name}/dotfiles/{entry}")
        if profile.post_setup:
            lines.append(f"\n[scripts] post_setup = post_setup.sh")
            lines.append(f"  (content: {len(profile.post_setup)} chars)")
        if profile.on_enter:
            lines.append(f"[scripts] on_enter = on_enter.sh")
            lines.append(f"  (content: {len(profile.on_enter)} chars)")
        self.app.push_screen(OutputScreen("\n".join(lines)))

    @on(Button.Pressed, "#save")
    def save(self) -> None:
        import shutil
        name = self.query_one("#prof-name", Input).value.strip()
        err = self._validate(name)
        if err:
            self.notify(err, severity="error")
            return
        profile = self._build_profile(name)
        profile_dir = self._profiles_dir / name
        dotfiles_dir = profile_dir / "dotfiles"
        try:
            profile_dir.mkdir(parents=True, exist_ok=False)
            dotfiles_dir.mkdir()
        except FileExistsError:
            self.notify(f"Profile '{name}' already exists", severity="error")
            return
        dotfile_entries = self._read_table_rows("dotfiles-table")
        final_basenames: list[str] = []
        new_host_basenames = {Path(e).name for e in dotfile_entries if "/" in e}
        remaining_inherited = {e for e in dotfile_entries if "/" not in e and e not in new_host_basenames}
        if self._source:
            for basename in self._inherited_dotfiles:
                if basename not in remaining_inherited:
                    continue
                src_path = self._profiles_dir / self._source.name / "dotfiles" / basename
                if src_path.exists():
                    shutil.copy2(src_path, dotfiles_dir / basename)
                    final_basenames.append(basename)
        for entry in dotfile_entries:
            if "/" in entry:
                basename = Path(entry).name
                shutil.copy2(entry, dotfiles_dir / basename)
                if basename not in final_basenames:
                    final_basenames.append(basename)
        if profile.post_setup:
            (profile_dir / "post_setup.sh").write_text(profile.post_setup, encoding="utf-8")
        if profile.on_enter:
            (profile_dir / "on_enter.sh").write_text(profile.on_enter, encoding="utf-8")
        profile.dotfiles = final_basenames
        from sandbox.profiles import write_profile
        write_profile(self._profiles_dir, name, profile)
        self.notify(f"Profile '{name}' created.")
        self.dismiss(True)

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(False)
