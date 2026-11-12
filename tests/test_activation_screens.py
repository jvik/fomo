"""Characterization tests for the Azure and Entra activation screens.

They pin the behaviour shared through ``ActivationScreenBase`` (failure rows,
error log, error bookkeeping across the sub/global tables) and the Escape
differences that are intentionally kept for now.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from textual.widgets import Button, DataTable, Input, RichLog, Select

from fomo import app as app_module
from fomo.app import PimApp
from fomo.azure import EligibleRole, EntraEligibleRole
from fomo.screens.activation_screen import ActivationScreen
from fomo.screens.entra_screen import EntraActivationScreen
from fomo.screens.scope_screen import ScopeScreen
from tests.test_tui_smoke import SIZE, _status_cells, wait_for

SUB = "/subscriptions/11111111-1111-1111-1111-111111111111"
MG = "/providers/Microsoft.Management/managementGroups/root"


@pytest.fixture
def make_app(monkeypatch: pytest.MonkeyPatch) -> Callable[..., PimApp]:
    """Demo-mode PimApp with theme detection and the dbus watcher stubbed."""
    monkeypatch.setattr(app_module, "_system_is_dark", lambda: True)
    monkeypatch.setattr(PimApp, "_watch_color_scheme", lambda self: None)

    def _make(**kw: Any) -> PimApp:
        return PimApp(demo_mode=True, dry_run=True, **kw)

    return _make


def _arm(name: str, scope: str) -> EligibleRole:
    return EligibleRole(name, f"{scope}/providers/x/roleDefinitions/{name}", scope, "disp", "u", "s", None)


def _entra(name: str) -> EntraEligibleRole:
    return EntraEligibleRole(name, name.lower(), "u", "s", None)


def test_azure_activation_failure_rows_and_error_log(make_app, fake_azure) -> None:
    fake_azure.fail_on = {"Reader", "Owner"}
    roles = [_arm("Reader", SUB), _arm("Contributor", SUB), _arm("Owner", MG)]

    async def scenario() -> None:
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            await wait_for(pilot, lambda: isinstance(app.screen, ScopeScreen))
            app.push_screen(ActivationScreen(roles))
            await wait_for(pilot, lambda: isinstance(app.screen, ActivationScreen))
            screen = app.screen
            assert isinstance(screen, ActivationScreen)
            await pilot.press(*"why")
            await pilot.click("#btn-activate")
            await wait_for(pilot, lambda: str(screen.query_one("#btn-back", Button).label) == "Done")

            sub_cells = _status_cells(screen.query_one("#roles-table", DataTable), 3)
            global_cells = _status_cells(screen.query_one("#global-roles-table", DataTable), 3)
            assert sub_cells == ["✗ ERROR: (Boom) Reader failed", "✓ DryRun"]
            assert global_cells == ["✗ ERROR: (Boom) Owner failed"]
            # Global rows are keyed after the subscription rows.
            assert screen._errors == {0: "ERROR: (Boom) Reader failed", 2: "ERROR: (Boom) Owner failed"}
            error_log = screen.query_one("#error-log", RichLog)
            assert not error_log.has_class("hidden")
            assert len(error_log.lines) > 0

    asyncio.run(scenario())


def test_entra_activation_long_failure_is_truncated(make_app, fake_azure) -> None:
    fake_azure.fail_on = {"Global Reader"}

    async def scenario() -> None:
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            await wait_for(pilot, lambda: isinstance(app.screen, ScopeScreen))
            app.push_screen(EntraActivationScreen([_entra("Global Reader"), _entra("Security Reader")]))
            await wait_for(pilot, lambda: isinstance(app.screen, EntraActivationScreen))
            screen = app.screen
            assert isinstance(screen, EntraActivationScreen)
            await pilot.press(*"why")
            await pilot.click("#btn-activate")
            await wait_for(pilot, lambda: str(screen.query_one("#btn-back", Button).label) == "Done")

            cells = _status_cells(screen.query_one("#roles-table", DataTable), 2)
            assert cells == ["✗ Graph says no", "✓ DryRun"]
            assert screen._errors == {0: "Graph says no"}

    asyncio.run(scenario())


def test_azure_escape_blurs_input_first_entra_escape_pops(make_app) -> None:
    async def scenario() -> None:
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            await wait_for(pilot, lambda: isinstance(app.screen, ScopeScreen))

            app.push_screen(ActivationScreen([_arm("Reader", SUB)]))
            await wait_for(pilot, lambda: isinstance(app.focused, Input))
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, ActivationScreen)
            assert not isinstance(app.focused, Input)
            await pilot.press("escape")
            await wait_for(pilot, lambda: isinstance(app.screen, ScopeScreen))

            app.push_screen(EntraActivationScreen([_entra("Global Reader")]))
            await wait_for(pilot, lambda: isinstance(app.focused, Input))
            await pilot.press("escape")
            await wait_for(pilot, lambda: isinstance(app.screen, ScopeScreen))

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("screen_cls", "roles"),
    [
        (ActivationScreen, [_arm("Reader", SUB)]),
        (EntraActivationScreen, [_entra("Global Reader")]),
    ],
    ids=["azure", "entra"],
)
def test_duration_can_never_be_blank(make_app, fake_azure, screen_cls, roles) -> None:
    async def scenario() -> None:
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            await wait_for(pilot, lambda: isinstance(app.screen, ScopeScreen))
            app.push_screen(screen_cls(roles))
            await wait_for(pilot, lambda: isinstance(app.focused, Input))
            screen = app.screen
            duration = screen.query_one("#duration", Select)

            # No blank row: every option is a real ISO 8601 duration.
            assert duration._allow_blank is False
            assert Select.NULL not in [value for _, value in duration._options]
            assert duration.value == "PT1H"

            # Keyboard: Enter in the justification focuses the duration.  Open
            # the menu and pick its top row, where the blank row used to be.
            await pilot.press(*"why", "enter")
            await wait_for(pilot, lambda: app.focused is duration)
            await pilot.press("enter")
            await wait_for(pilot, lambda: duration.expanded)
            await pilot.press("home", "enter")
            await wait_for(pilot, lambda: not duration.expanded)
            assert duration.value == "PT30M"
            assert not duration.is_blank()

            await pilot.click("#btn-activate")
            await wait_for(pilot, lambda: str(screen.query_one("#btn-back", Button).label) == "Done")
            assert [d for _, _, d, _ in fake_azure.activations] == ["PT30M"]

    asyncio.run(scenario())
