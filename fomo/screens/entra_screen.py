"""Entra activation screen — fill in justification + duration, then activate selected Entra roles."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header, Label

from fomo import azure
from fomo.screens._activation_base import ActivationScreenBase

log = logging.getLogger(__name__)


class EntraActivationScreen(ActivationScreenBase[azure.EntraEligibleRole]):
    """Fill in justification + duration, then activate selected Entra roles."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=True, priority=True),
        Binding("q", "back", "Back", show=False),
    ]

    STATUS_COLUMN = 2
    _log = log
    _FAILURE_LOG_MESSAGE = "Entra activation failed for %s: %s"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="main"):
            yield Label(
                f"Activating [bold]{len(self.roles)}[/bold] Entra role(s):",
                id="title",
            )
            yield DataTable(id="roles-table", show_cursor=False)
            yield from self._compose_form()
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#roles-table", DataTable)
        table.add_column("Role")
        table.add_column("Expires")
        table.add_column("Status", width=36)
        for role in self.roles:
            table.add_row(role.role_name, azure.format_expiry(role.expiry), "—")
        self.query_one("#justification").focus()

    def _role_tables(self) -> Sequence[tuple[str, Sequence[azure.EntraEligibleRole]]]:
        return [("roles-table", self.roles)]

    def _activate(self, role: azure.EntraEligibleRole, justification: str, duration: str) -> str:
        result = self.app.backend.activate_entra_role(role, justification, duration)  # type: ignore[attr-defined]
        return result.get("status", "Submitted")

    def action_back(self) -> None:
        if not self._activating:
            self.app.pop_screen()
