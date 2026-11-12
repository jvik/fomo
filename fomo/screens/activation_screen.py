"""Activation screen — justification form and per-role activation progress."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header, Input, Label

from fomo import azure
from fomo.screens._activation_base import ActivationScreenBase

log = logging.getLogger(__name__)


class ActivationScreen(ActivationScreenBase[azure.EligibleRole]):
    """Fill in justification + duration, then activate selected roles."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=True),
    ]

    STATUS_COLUMN = 3
    _log = log
    _FAILURE_LOG_MESSAGE = "activation failed for %s: %s"

    def __init__(self, roles: list[azure.EligibleRole]) -> None:
        super().__init__(roles)
        self._sub_roles = [r for r in roles if not r.is_global]
        self._global_roles = [r for r in roles if r.is_global]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="main"):
            yield Label(
                f"Activating [bold]{len(self.roles)}[/bold] role(s):",
                id="title",
            )
            yield DataTable(id="roles-table", show_cursor=False)
            if self._global_roles:
                with Vertical(id="global-roles-box"):
                    yield Label(
                        f"[bold yellow]⚠ Global assignments[/bold yellow]"
                        f"  [dim]({len(self._global_roles)} role(s) — management group scope)[/dim]"
                    )
                    yield DataTable(id="global-roles-table", show_cursor=False)
            yield from self._compose_form()
        yield Footer()

    def on_mount(self) -> None:
        for table_id, roles in self._role_tables():
            table = self.query_one(f"#{table_id}", DataTable)
            table.add_column("Role")
            table.add_column("Scope")
            table.add_column("Expires")
            table.add_column("Status", width=36)
            for role in roles:
                table.add_row(
                    Text(role.role_name),
                    Text(role.scope_display_name),
                    Text(azure.format_expiry(role.expiry)),
                    "—",
                )
        self.query_one("#justification").focus()

    def _role_tables(self) -> Sequence[tuple[str, Sequence[azure.EligibleRole]]]:
        tables: list[tuple[str, Sequence[azure.EligibleRole]]] = [("roles-table", self._sub_roles)]
        if self._global_roles:
            tables.append(("global-roles-table", self._global_roles))
        return tables

    def _activate(self, role: azure.EligibleRole, justification: str, duration: str) -> str:
        result = self.app.backend.activate_role(role, justification, duration)  # type: ignore[attr-defined]
        return result.get("properties", {}).get("status", "Submitted")

    def action_back(self) -> None:
        if isinstance(self.focused, Input):
            # First Esc: blur the input, keep text intact
            self.focused.blur()
            return
        if not self._activating:
            self.app.pop_screen()
