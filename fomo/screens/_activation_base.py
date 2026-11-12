"""Shared logic for the Azure and Entra activation screens.

Both screens show the selected roles in one or more tables with a Status
column, a shared justification + duration form, and an error log.  The
subclasses define their tables, how a role is activated, their bindings and
how Back behaves.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import ClassVar, Generic, TypeVar

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.coordinate import Coordinate
from textual.screen import Screen
from textual.widgets import Button, DataTable, Input, Label, RichLog, Select

from fomo import azure

_DURATION_OPTIONS: list[tuple[str, str]] = [
    ("30 min", "PT30M"),
    ("1 hour", "PT1H"),
    ("2 hours", "PT2H"),
    ("4 hours", "PT4H"),
    ("6 hours", "PT6H"),
    ("8 hours", "PT8H"),
]

RoleT = TypeVar("RoleT", azure.EligibleRole, azure.EntraEligibleRole)


class ActivationScreenBase(Screen, Generic[RoleT]):
    """Justification form plus per-role activation progress."""

    # Index of the Status column in every role table.
    STATUS_COLUMN: ClassVar[int]
    # Logger and message used when an activation fails.
    _log: ClassVar[logging.Logger]
    _FAILURE_LOG_MESSAGE: ClassVar[str]

    def __init__(self, roles: list[RoleT]) -> None:
        super().__init__()
        self.roles: list[RoleT] = roles
        self._activating = False
        self._errors: dict[int, str] = {}  # running row index → full error message

    # ------------------------------------------------------------------
    # Subclass hooks
    # ------------------------------------------------------------------

    def _role_tables(self) -> Sequence[tuple[str, Sequence[RoleT]]]:
        """Return ``(table_id, roles)`` pairs in activation order."""
        raise NotImplementedError

    def _activate(self, role: RoleT, justification: str, duration: str) -> str:
        """Submit one activation and return its status string."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Compose helpers
    # ------------------------------------------------------------------

    def _compose_form(self) -> ComposeResult:
        """Yield the justification/duration form, the buttons and the error log."""
        with Vertical(id="form"):
            yield Label("Justification  [dim](required, shared across all roles)[/dim]")
            yield Input(placeholder="Reason for activation", id="justification")
            yield Label("Duration")
            yield Select(_DURATION_OPTIONS, value="PT1H", id="duration")
        with Horizontal(id="buttons"):
            yield Button("Activate", variant="primary", id="btn-activate")
            yield Button("Back", id="btn-back")
        yield RichLog(id="error-log", highlight=True, markup=True, classes="hidden")

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

    def action_back(self) -> None:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Background activation worker
    # ------------------------------------------------------------------

    @work(thread=True)
    def _run_activation(self, justification: str, duration: str) -> None:
        offset = 0
        for table_id, roles in self._role_tables():
            for i, role in enumerate(roles):
                self._activate_row(table_id, i, offset + i, role, justification, duration)
            offset += len(roles)
        self.app.call_from_thread(self._on_activation_done)

    def _activate_row(
        self,
        table_id: str,
        row: int,
        error_index: int,
        role: RoleT,
        justification: str,
        duration: str,
    ) -> None:
        """Activate *role* and show progress in its table row (worker thread)."""
        self.app.call_from_thread(self._set_status, table_id, row, "Activating…")
        label: str | Text
        try:
            label = self._format_status(self._activate(role, justification, duration))
        except Exception as exc:
            full_error = str(exc)
            self._log.error(self._FAILURE_LOG_MESSAGE, role.role_name, full_error)
            self._errors[error_index] = full_error
            short = full_error[:30] + "…" if len(full_error) > 30 else full_error
            label = f"✗ {short}"
            self.app.call_from_thread(self._append_error, role.role_name, full_error)
        self.app.call_from_thread(self._set_status, table_id, row, label)

    # ------------------------------------------------------------------
    # UI update helpers (called on the main thread via call_from_thread)
    # ------------------------------------------------------------------

    def _set_status(self, table_id: str, row: int, text: str | Text) -> None:
        table = self.query_one(f"#{table_id}", DataTable)
        table.update_cell_at(Coordinate(row, self.STATUS_COLUMN), text)

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
