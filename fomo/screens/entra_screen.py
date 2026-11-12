"""Entra activation screen — fill in justification + duration, then activate selected Entra roles."""

from __future__ import annotations

import logging

from rich.text import Text
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
    RichLog,
    Select,
)

from fomo import azure

log = logging.getLogger(__name__)

_DURATION_OPTIONS: list[tuple[str, str]] = [
    ("30 min", "PT30M"),
    ("1 hour", "PT1H"),
    ("2 hours", "PT2H"),
    ("4 hours", "PT4H"),
    ("6 hours", "PT6H"),
    ("8 hours", "PT8H"),
]


class EntraActivationScreen(Screen):
    """Fill in justification + duration, then activate selected Entra roles."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=True, priority=True),
        Binding("q", "back", "Back", show=False),
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
                result = self.app.backend.activate_entra_role(role, justification, duration)  # type: ignore[attr-defined]
                status: str = result.get("status", "Submitted")
                label: str | Text = self._format_status(status)
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

    def _set_status(self, row: int, text: str | Text) -> None:
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
    def _format_status(status: str) -> Text:
        if status in ("Provisioned", "Granted", "DryRun"):
            return Text.from_markup(f"[bold green]✓ {status}[/bold green]")
        if "Pending" in status or status in ("Accepted", "ScheduleCreated"):
            return Text.from_markup(f"[bold yellow]⏳ {status}[/bold yellow]")
        if status in ("Failed", "Denied", "Canceled", "TimedOut"):
            return Text.from_markup(f"[bold red]✗ {status}[/bold red]")
        return Text(status)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_back(self) -> None:
        if not self._activating:
            self.app.pop_screen()
