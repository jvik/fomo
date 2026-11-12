"""Entra activation screen — fill in justification + duration, then activate selected Entra roles."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from rich.text import Text
from textual.app import ComposeResult

from fomo import azure, state, tiering
from fomo.screens._activation_base import ActivationScreenBase, RoleTable, table_cell, tier_cell, title_markup

log = logging.getLogger(__name__)


class EntraActivationScreen(ActivationScreenBase[azure.EntraEligibleRole]):
    """Fill in justification + duration, then activate selected Entra roles."""

    COLUMNS = ("Role", "Tier")
    _log = log
    _FAILURE_LOG_MESSAGE = "Entra activation failed for %s: %s"

    def _title(self) -> str:
        return title_markup(len(self.roles), "Entra role")

    def _compose_tables(self) -> ComposeResult:
        # At narrow widths the role name gives up room before Status does.
        yield RoleTable(id="roles-table", shrink=((0, 16),))

    def _role_tables(self) -> Sequence[tuple[str, Sequence[azure.EntraEligibleRole]]]:
        return [("roles-table", self.roles)]

    def _row_cells(self, role: azure.EntraEligibleRole) -> Sequence[Text]:
        return (table_cell(role.role_name), tier_cell(tiering.get_entra_tier(role.role_definition_id)))

    def _activate(self, role: azure.EntraEligibleRole, justification: str, duration: str) -> str:
        result = self.app.backend.activate_entra_role(role, justification, duration)  # type: ignore[attr-defined]
        return result.get("status", "Submitted")

    def _recent_entry(
        self, roles: Sequence[azure.EntraEligibleRole], justification: str, duration: str
    ) -> state.Recent | None:
        return state.entra_recent(roles, justification, duration)
