"""Activation screen — justification form and per-role activation progress."""

from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.coordinate import Coordinate
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label

from fzf_pim import azure

# Status column index in the DataTable
_COL_STATUS = 3


class ActivationScreen(Screen):
    """Fill in justification + duration, then activate selected roles."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=True),
    ]

    def __init__(self, roles: list[azure.EligibleRole]) -> None:
        super().__init__()
        self.roles = roles
        self._activating = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="main"):
            yield Label(
                f"Activating [bold]{len(self.roles)}[/bold] role(s):",
                id="title",
            )
            yield DataTable(id="roles-table", show_cursor=False)
            with Vertical(id="form"):
                yield Label("Justification  [dim](required, shared across all roles)[/dim]")
                yield Input(
                    placeholder="Reason for activation",
                    id="justification",
                )
                yield Label(
                    "Duration  [dim](ISO 8601, e.g. PT8H · PT1H30M · PT30M)[/dim]"
                )
                yield Input(
                    placeholder="PT8H",
                    value="PT8H",
                    id="duration",
                )
            with Horizontal(id="buttons"):
                yield Button("Activate", variant="primary", id="btn-activate")
                yield Button("Back", id="btn-back")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#roles-table", DataTable)
        table.add_columns("Role", "Scope", "Expires", "Status")
        for role in self.roles:
            table.add_row(
                role.role_name,
                role.scope_display_name,
                azure.format_expiry(role.expiry),
                "—",
            )
        self.query_one("#justification").focus()

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

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
        duration = self.query_one("#duration", Input).value.strip() or "PT8H"
        if not azure.validate_duration(duration):
            self.notify(
                f"Invalid duration '{duration}'. Use ISO 8601 format, e.g. PT8H.",
                severity="warning",
            )
            self.query_one("#duration").focus()
            return

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
                result = azure.activate_role(
                    role,
                    justification,
                    duration,
                    dry_run=self.app.dry_run,  # type: ignore[attr-defined]
                )
                status: str = result.get("properties", {}).get("status", "Submitted")
                label = self._format_status(status)
            except Exception as exc:
                label = f"Error: {str(exc)[:60]}"
            self.app.call_from_thread(self._set_status, i, label)
        self.app.call_from_thread(self._on_activation_done)

    # ------------------------------------------------------------------
    # UI update helpers (called from main thread via call_from_thread)
    # ------------------------------------------------------------------

    def _set_status(self, row: int, text: str) -> None:
        table = self.query_one("#roles-table", DataTable)
        table.update_cell_at(Coordinate(row, _COL_STATUS), text)

    def _on_activation_done(self) -> None:
        self.query_one("#btn-back", Button).disabled = False
        self.query_one("#btn-back", Button).label = "Done"
        self.notify("Activation requests submitted.", severity="information")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
