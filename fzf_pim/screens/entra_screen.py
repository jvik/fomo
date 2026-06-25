"""Entra screen — load and activate Microsoft Entra PIM roles."""

from __future__ import annotations

import logging
import threading

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.coordinate import Coordinate
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    LoadingIndicator,
    RichLog,
    Select,
    SelectionList,
)
from textual.widgets._selection_list import Selection

from fzf_pim import azure

log = logging.getLogger(__name__)

_DURATION_OPTIONS: list[tuple[str, str]] = [
    ("30 min", "PT30M"),
    ("1 hour", "PT1H"),
    ("2 hours", "PT2H"),
    ("4 hours", "PT4H"),
    ("6 hours", "PT6H"),
    ("8 hours", "PT8H"),
]


class EntraRolesScreen(Screen):
    """Fuzzy-filter and multiselect eligible Microsoft Entra PIM roles."""

    BINDINGS = [
        Binding("enter", "proceed", "Activate selected", show=True, priority=True),
        Binding("escape", "back", "Back", show=True),
        Binding("tab", "focus_list", "Next box", show=True),
        Binding("shift+tab", "focus_filter", "Prev box", show=True),
        Binding("slash", "focus_filter", "Filter", show=False),
        Binding("a", "select_all_visible", "All", show=True),
        Binding("j", "vim_down", "↓", show=False),
        Binding("k", "vim_up", "↑", show=False),
        Binding("g", "vim_top", "Top", show=False),
        Binding("G", "vim_bottom", "Bottom", show=False),
    ]

    def __init__(self, pushed: bool = False) -> None:
        super().__init__()
        self._pushed = pushed
        self.all_roles: list[azure.EntraEligibleRole] = []
        self._selected: set[int] = set()
        self._visible_indices: set[int] = set()
        self._rebuilding = False
        self._stop_event = threading.Event()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="main"):
            yield Label("Loading Entra eligible roles…", id="loading-label")
            yield LoadingIndicator(id="spinner")
            yield Input(placeholder="Filter roles… (type to search)", id="filter")
            yield SelectionList(id="role-list")
            yield Label("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#filter").display = False
        self.query_one("#role-list").display = False
        self.query_one("#status").display = False
        self._load_roles()

    def on_unmount(self) -> None:
        self._stop_event.set()

    @work(thread=True)
    def _load_roles(self) -> None:
        def _on_device_code(message: str) -> None:
            url, _, code = message.partition("\n")
            def _update() -> None:
                self.query_one("#loading-label", Label).update(
                    "[bold]Sign in to Microsoft Graph[/bold]\n\n"
                    f"[dim]1.[/dim] Open:  [link]{url}[/link]\n"
                    f"[dim]2.[/dim] Enter code:  [bold]{code}[/bold]\n\n"
                    "[dim]Waiting for authentication…[/dim]"
                )
            self.app.call_from_thread(_update)

        try:
            roles = azure.list_entra_eligible_roles(
                on_device_code=_on_device_code,
                stop_event=self._stop_event,
            )
            self.app.call_from_thread(self._on_roles_loaded, roles)
        except Exception as exc:
            self.app.call_from_thread(self._on_error, str(exc))

    def _on_roles_loaded(self, roles: list[azure.EntraEligibleRole]) -> None:
        self.all_roles = roles
        self.query_one("#spinner").display = False
        lbl = self.query_one("#loading-label", Label)
        if not roles:
            lbl.update("[dim]No eligible Entra roles found.[/dim]")
            return
        lbl.update(
            f"Entra eligible roles  ({len(roles)} found)"
            "   [dim]j/k[/dim]=nav  [dim]a[/dim]=all  [dim]Enter[/dim]=activate"
        )
        self.query_one("#filter").display = True
        self.query_one("#role-list").display = True
        self.query_one("#status").display = True
        self._rebuild_list("")
        self.query_one("#role-list").focus()
        self._update_status()

    def _on_error(self, msg: str) -> None:
        self.query_one("#spinner").display = False
        if azure.is_auth_error(msg):
            body = (
                "[bold red]Azure session expired.[/bold red]\n\n"
                "Run [bold]az login[/bold] in your terminal, then restart fzf-pim."
            )

        else:
            # Wrap long messages at word boundaries so they don't get clipped.
            wrapped = "\n".join(
                line if len(line) <= 80 else "\n".join(
                    msg[i:i+80] for i in range(0, len(line), 80)
                )
                for line in msg.splitlines()
            )
            body = f"[bold red]Error:[/bold red]\n\n{wrapped}"
        self.query_one("#loading-label", Label).update(body)

    # ------------------------------------------------------------------
    # Filter helpers
    # ------------------------------------------------------------------

    def _rebuild_list(self, query: str) -> None:
        sl = self.query_one("#role-list", SelectionList)
        q = query.strip().lower()
        self._rebuilding = True
        sl.clear_options()
        self._visible_indices = set()
        for idx, role in enumerate(self.all_roles):
            if q and q not in role.role_name.lower():
                continue
            active_tag = " [bold green](active)[/bold green]" if role.is_active else ""
            expiry_tag = f" [dim]- {azure.format_expiry(role.expiry)}[/dim]"
            label = f"{role.role_name}{active_tag}{expiry_tag}"
            sl.add_option(Selection(label, idx, idx in self._selected))
            self._visible_indices.add(idx)
        self._rebuilding = False

    @on(Input.Changed, "#filter")
    def on_filter_changed(self, event: Input.Changed) -> None:
        self._rebuild_list(event.value)

    @on(Input.Submitted, "#filter")
    def on_filter_submitted(self, event: Input.Submitted) -> None:  # noqa: ARG002
        self.action_select_all_visible()
        self.query_one("#role-list").focus()

    @on(SelectionList.SelectedChanged, "#role-list")
    def on_selection_changed(self, event: SelectionList.SelectedChanged) -> None:
        if self._rebuilding:
            return
        visible_selected: set[int] = set(event.selection_list.selected)
        visible_unselected = self._visible_indices - visible_selected
        self._selected |= visible_selected
        self._selected -= visible_unselected
        self._update_status()

    def _update_status(self) -> None:
        n = len(self._selected)
        lbl = self.query_one("#status", Label)
        if n == 0:
            lbl.update("[dim]No roles selected[/dim]")
        else:
            lbl.update(f"[bold]{n}[/bold] role(s) selected")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_focus_list(self) -> None:
        self.query_one("#role-list").focus()

    def action_focus_filter(self) -> None:
        self.query_one("#filter").focus()

    def action_select_all_visible(self) -> None:
        self._selected.update(self._visible_indices)
        sl = self.query_one("#role-list", SelectionList)
        self._rebuilding = True
        sl.select_all()
        self._rebuilding = False
        self._update_status()

    def action_proceed(self) -> None:
        if self.focused is self.query_one("#filter"):
            self.action_focus_list()
            return
        selected_roles = [self.all_roles[i] for i in sorted(self._selected)]
        if not selected_roles:
            self.notify("Select at least one role.", severity="warning")
            return
        self.app.push_screen(EntraActivationScreen(selected_roles))

    def action_vim_down(self) -> None:
        w = self.focused
        if hasattr(w, "action_cursor_down"):
            w.action_cursor_down()

    def action_vim_up(self) -> None:
        w = self.focused
        if hasattr(w, "action_cursor_up"):
            w.action_cursor_up()

    def action_vim_top(self) -> None:
        w = self.focused
        if hasattr(w, "scroll_home"):
            w.scroll_home(animate=False)

    def action_vim_bottom(self) -> None:
        w = self.focused
        if hasattr(w, "scroll_end"):
            w.scroll_end(animate=False)

    def action_back(self) -> None:
        if self._pushed:
            self.app.pop_screen()
        else:
            self.app.exit()


class EntraActivationScreen(Screen):
    """Fill in justification + duration, then activate selected Entra roles."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=True),
    ]

    def __init__(self, roles: list[azure.EntraEligibleRole]) -> None:
        super().__init__()
        self.roles = roles
        self._activating = False
        self._errors: dict[int, str] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="main"):
            yield Label(
                f"Activating [bold]{len(self.roles)}[/bold] Entra role(s):",
                id="title",
            )
            yield DataTable(id="roles-table", show_cursor=False)
            with Vertical(id="form"):
                yield Label("Justification  [dim](required, shared across all roles)[/dim]")
                yield Input(placeholder="Reason for activation", id="justification")
                yield Label("Duration")
                yield Select(_DURATION_OPTIONS, value="PT1H", id="duration")
            with Horizontal(id="buttons"):
                yield Button("Activate", variant="primary", id="btn-activate")
                yield Button("Back", id="btn-back")
            yield RichLog(id="error-log", highlight=True, markup=True, classes="hidden")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#roles-table", DataTable)
        table.add_column("Role")
        table.add_column("Expires")
        table.add_column("Status", width=36)
        for role in self.roles:
            table.add_row(role.role_name, azure.format_expiry(role.expiry), "—")
        self.query_one("#justification").focus()

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    @on(Input.Submitted, "#justification")
    def on_justification_submitted(self, event: Input.Submitted) -> None:  # noqa: ARG002
        self.query_one("#duration").focus()

    @on(Button.Pressed, "#btn-back")
    def on_back_pressed(self) -> None:
        self.action_back()

    @on(Button.Pressed, "#btn-activate")
    def on_activate_pressed(self) -> None:
        if self._activating:
            return
        justification = self.query_one("#justification", Input).value.strip()
        if not justification:
            self.notify("Justification is required.", severity="warning")
            self.query_one("#justification").focus()
            return
        duration = self.query_one("#duration", Select).value or "PT1H"
        self._activating = True
        self.query_one("#btn-activate", Button).disabled = True
        self.query_one("#btn-back", Button).disabled = True
        self._run_activation(justification, duration)

    # ------------------------------------------------------------------
    # Background activation worker
    # ------------------------------------------------------------------

    @work(thread=True)
    def _run_activation(self, justification: str, duration: str) -> None:
        for i, role in enumerate(self.roles):
            self.app.call_from_thread(self._set_status, i, "Activating…")
            try:
                result = azure.activate_entra_role(
                    role,
                    justification,
                    duration,
                    dry_run=self.app.dry_run,  # type: ignore[attr-defined]
                )
                status: str = result.get("status", "Submitted")
                label = self._format_status(status)
            except Exception as exc:
                full_error = str(exc)
                log.error("Entra activation failed for %s: %s", role.role_name, full_error)
                self._errors[i] = full_error
                short = full_error[:30] + "…" if len(full_error) > 30 else full_error
                label = f"✗ {short}"
                self.app.call_from_thread(self._append_error, role.role_name, full_error)
            self.app.call_from_thread(self._set_status, i, label)
        self.app.call_from_thread(self._on_activation_done)

    # ------------------------------------------------------------------
    # UI update helpers
    # ------------------------------------------------------------------

    def _set_status(self, row: int, text: str) -> None:
        self.query_one("#roles-table", DataTable).update_cell_at(Coordinate(row, 2), text)

    def _append_error(self, role_name: str, message: str) -> None:
        error_log = self.query_one("#error-log", RichLog)
        error_log.remove_class("hidden")
        error_log.write(f"[bold red]✗ {role_name}[/bold red]")
        error_log.write(message)
        error_log.write("")

    def _on_activation_done(self) -> None:
        self._activating = False
        btn_back = self.query_one("#btn-back", Button)
        btn_back.disabled = False
        btn_back.label = "Done"
        btn_back.focus()
        if self._errors:
            self.notify(
                f"{len(self._errors)} role(s) failed — see error details below.",
                severity="error",
                timeout=8,
            )
        else:
            self.notify("Activation requests submitted.", severity="information")

    @staticmethod
    def _format_status(status: str) -> str:
        if status in ("Provisioned", "Granted", "DryRun"):
            return f"✓ {status}"
        if "Pending" in status or status in ("Accepted", "ScheduleCreated"):
            return f"⏳ {status}"
        if status in ("Failed", "Denied", "Canceled", "TimedOut"):
            return f"✗ {status}"
        return status

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_back(self) -> None:
        if not self._activating:
            self.app.pop_screen()
