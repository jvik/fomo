"""Activation screen — justification form and per-role activation progress."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label

from fomo import azure, state, tiering
from fomo.screens._activation_base import (
    DEFAULT_DURATION,
    ActivationScreenBase,
    RoleTable,
    table_cell,
    tier_cell,
    title_markup,
)

log = logging.getLogger(__name__)

# At narrow widths Scope gives up room first, then Role.
_SHRINK = ((1, 10), (0, 16))


class ActivationScreen(ActivationScreenBase[azure.EligibleRole]):
    """Fill in justification + duration, then activate selected roles."""

    COLUMNS = ("Role", "Scope", "Tier")
    _log = log
    _FAILURE_LOG_MESSAGE = "activation failed for %s: %s"

    def __init__(
        self,
        roles: list[azure.EligibleRole],
        *,
        subscriptions: Sequence[str] = (),
        justification: str = "",
        duration: str = DEFAULT_DURATION,
    ) -> None:
        """*subscriptions* are those whose roles were listed (remembered to list them again)."""
        super().__init__(roles, justification=justification, duration=duration)
        self._subscriptions = tuple(subscriptions) or _subscriptions_of(roles)
        self._sub_roles = [r for r in roles if not r.is_global]
        self._global_roles = [r for r in roles if r.is_global]

    def _title(self) -> str:
        return title_markup(len(self.roles), "role")

    def _compose_tables(self) -> ComposeResult:
        table = RoleTable(id="roles-table", shrink=_SHRINK)
        table.display = bool(self._sub_roles)  # nothing but global roles: no empty table
        yield table
        if self._global_roles:
            with Vertical(id="global-roles-box"):
                yield Label(
                    f"[bold yellow]⚠ Global assignments[/bold yellow]"
                    f"  [dim]({len(self._global_roles)} role(s) — management group scope)[/dim]"
                )
                yield RoleTable(id="global-roles-table", shrink=_SHRINK)

    def _role_tables(self) -> Sequence[tuple[str, Sequence[azure.EligibleRole]]]:
        tables: list[tuple[str, Sequence[azure.EligibleRole]]] = [("roles-table", self._sub_roles)]
        if self._global_roles:
            tables.append(("global-roles-table", self._global_roles))
        return tables

    def _row_cells(self, role: azure.EligibleRole) -> Sequence[Text]:
        return (
            table_cell(role.role_name),
            table_cell(role.scope_display_name),
            tier_cell(tiering.get_azure_tier(role.role_definition_id)),
        )

    def _activate(self, role: azure.EligibleRole, justification: str, duration: str) -> str:
        result = self.app.backend.activate_role(role, justification, duration)  # type: ignore[attr-defined]
        return result.get("properties", {}).get("status", "Submitted")

    def _recent_entry(
        self, roles: Sequence[azure.EligibleRole], justification: str, duration: str
    ) -> state.Recent | None:
        if not self._subscriptions:
            return None  # nowhere to list the roles again
        return state.azure_recent(roles, self._subscriptions, justification, duration)


def _subscriptions_of(roles: Sequence[azure.EligibleRole]) -> tuple[str, ...]:
    """The subscriptions of the subscription-scoped *roles*, in order."""
    # A subscription-scoped role's scope starts with /subscriptions/<id>.
    ids = (role.scope.split("/")[2] for role in roles if not role.is_global)
    return tuple(dict.fromkeys(sub_id for sub_id in ids if sub_id))
