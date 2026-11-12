"""Pilot smoke tests: one per screen, driven through ``App.run_test()``.

These run in demo mode (or against ``fake_azure``) with dry-run on, system
theme detection and the dbus watcher stubbed, and tiering fetches disabled by
the autouse kill switch.  They use ``asyncio.run`` so no pytest-asyncio is
needed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from textual.coordinate import Coordinate
from textual.pilot import Pilot
from textual.widgets import Button, DataTable, Input, TabbedContent, Tabs

from fomo import app as app_module
from fomo.app import AuthErrorModal, PimApp
from fomo.screens.activation_screen import ActivationScreen
from fomo.screens.assignments_screen import AssignmentsScreen
from fomo.screens.entra_screen import EntraActivationScreen
from fomo.screens.roles_screen import RolesScreen
from fomo.screens.scope_screen import ScopeScreen
from fomo.widgets import FomoSelectionList

SIZE = (120, 40)


@pytest.fixture
def make_app(monkeypatch: pytest.MonkeyPatch) -> Callable[..., PimApp]:
    """Build a PimApp with theme detection and the dbus watcher stubbed.

    Animations are off, so tab switches and scrolls don't wait for them.
    """
    monkeypatch.setattr(app_module, "_system_is_dark", lambda: True)
    monkeypatch.setattr(PimApp, "_watch_color_scheme", lambda self: None)

    def _make(**kw: Any) -> PimApp:
        kw.setdefault("demo_mode", True)
        kw.setdefault("dry_run", True)
        app = PimApp(**kw)
        app.animation_level = "none"
        return app

    return _make


async def wait_for(pilot: Pilot, cond: Callable[[], Any], timeout: float = 3) -> None:
    """Poll *cond* until it is truthy, letting the app process messages."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        try:
            if cond():
                return
        except Exception:  # widget not mounted yet, etc.
            pass
        if loop.time() > deadline:
            raise AssertionError(f"timed out after {timeout}s waiting for condition")
        await pilot.pause(0.02)


def _list(app: PimApp, selector: str) -> FomoSelectionList:
    return app.screen.query_one(selector, FomoSelectionList)


def _prompts(sl: FomoSelectionList) -> list[str]:
    return [str(sl.get_option_at_index(i).prompt) for i in range(sl.option_count)]


async def _subs_loaded(pilot: Pilot) -> FomoSelectionList:
    app = pilot.app
    await wait_for(pilot, lambda: isinstance(app.screen, ScopeScreen))
    await wait_for(pilot, lambda: _list(app, "#sub-list").option_count == 5)
    return _list(app, "#sub-list")


async def _switch_to_entra(pilot: Pilot) -> FomoSelectionList:
    app = pilot.app
    await _subs_loaded(pilot)
    app.screen.query_one("#scope-tabs", TabbedContent).query_one(Tabs).focus()
    await pilot.pause()
    assert isinstance(app.focused, Tabs)
    await pilot.press("l")
    await wait_for(pilot, lambda: app.screen.query_one("#scope-tabs", TabbedContent).active == "tab-entra")
    await wait_for(pilot, lambda: _list(app, "#entra-role-list").option_count == 5)
    return _list(app, "#entra-role-list")


async def _open_roles(pilot: Pilot) -> FomoSelectionList:
    """Select subscriptions 0-2 on the scope screen and open the roles screen."""
    app = pilot.app
    subs = await _subs_loaded(pilot)
    subs.focus()
    subs.highlighted = 0
    await pilot.pause()
    await pilot.press("x", "down", "x", "down", "x")
    await wait_for(pilot, lambda: len(subs.selected) == 3)
    await pilot.pause()
    await pilot.press("enter")
    await wait_for(pilot, lambda: isinstance(app.screen, RolesScreen))
    await wait_for(pilot, lambda: _list(app, "#role-list").option_count > 0)
    return _list(app, "#role-list")


async def _activate_and_wait(pilot: Pilot) -> None:
    app = pilot.app
    # Set, not typed: typing into the reason field is covered in
    # test_activation_screens.py, and each key press costs Pilot an idle wait.
    app.screen.query_one("#justification", Input).value = "smoketest"
    await pilot.click("#btn-activate")
    await wait_for(pilot, lambda: str(app.screen.query_one("#btn-back", Button).label) == "Done")


def _status_cells(table: DataTable, col: int) -> list[str]:
    return [str(table.get_cell_at(Coordinate(r, col))) for r in range(table.row_count)]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_scope_screen_loads_subs_and_lazy_loads_entra(make_app) -> None:
    async def scenario() -> None:
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            subs = await _subs_loaded(pilot)
            assert subs.option_count == 5
            # Entra tab has not loaded yet.
            assert _list(app, "#entra-role-list").option_count == 0
            entra = await _switch_to_entra(pilot)
            assert entra.option_count == 5

    asyncio.run(scenario())


def test_roles_screen_disables_active_role_and_cycles_sort(make_app, tiering_fixture) -> None:
    async def scenario() -> None:
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            roles = await _open_roles(pilot)
            screen = app.screen
            assert isinstance(screen, RolesScreen)

            contributor = [
                roles.get_option_at_index(i)
                for i, prompt in enumerate(_prompts(roles))
                if prompt.startswith("Contributor") and "(active)" in prompt
            ]
            assert contributor, _prompts(roles)
            assert all(opt.disabled for opt in contributor)

            seen = [screen._sort_mode]
            for _ in range(4):
                await pilot.press("ctrl+s")
                await pilot.pause()
                seen.append(screen._sort_mode)
            assert seen == ["name", "scope", "tier", "expiry", "name"]

    asyncio.run(scenario())


def test_activation_screen_dry_run(make_app, fake_azure) -> None:
    async def scenario() -> None:
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            roles = await _open_roles(pilot)
            idx = next(i for i in range(roles.option_count) if not roles.get_option_at_index(i).disabled)
            roles.focus()
            roles.highlighted = idx
            await pilot.pause()
            await pilot.press("x")
            await wait_for(pilot, lambda: len(roles.selected) == 1)
            await pilot.press("enter")
            await wait_for(pilot, lambda: isinstance(app.screen, ActivationScreen))

            await _activate_and_wait(pilot)

            screen = app.screen
            cells = _status_cells(screen.query_one("#roles-table", DataTable), 3)
            if screen.query("#global-roles-table"):
                cells += _status_cells(screen.query_one("#global-roles-table", DataTable), 3)
            assert cells
            assert all("DryRun" in c for c in cells), cells

        assert len(fake_azure.activations) == 1
        assert all(dry_run for *_, dry_run in fake_azure.activations)
        assert fake_azure.justifications == ["smoketest"]

    asyncio.run(scenario())


def test_entra_activation_screen_dry_run(make_app, fake_azure) -> None:
    async def scenario() -> None:
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            entra = await _switch_to_entra(pilot)
            idx = next(i for i, p in enumerate(_prompts(entra)) if "(active)" not in p)
            entra.focus()
            entra.highlighted = idx
            await pilot.pause()
            await pilot.press("x")
            await wait_for(pilot, lambda: len(entra.selected) == 1)
            await pilot.press("enter")
            await wait_for(pilot, lambda: isinstance(app.screen, EntraActivationScreen))

            await _activate_and_wait(pilot)

            cells = _status_cells(app.screen.query_one("#roles-table", DataTable), 2)
            assert cells
            assert all("DryRun" in c for c in cells), cells

        assert len(fake_azure.activations) == 1
        assert all(dry_run for *_, dry_run in fake_azure.activations)

    asyncio.run(scenario())


def test_assignments_screen_populates_both_tables(make_app) -> None:
    async def scenario() -> None:
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            subs = await _subs_loaded(pilot)
            subs.focus()
            await pilot.pause()
            await pilot.press("i")
            await wait_for(pilot, lambda: isinstance(app.screen, AssignmentsScreen))
            await wait_for(
                pilot,
                lambda: (
                    app.screen.query_one("#azure-table", DataTable).row_count == 4
                    and app.screen.query_one("#entra-table", DataTable).row_count == 2
                ),
            )
            await pilot.press("escape")
            await wait_for(pilot, lambda: isinstance(app.screen, ScopeScreen))

    asyncio.run(scenario())


def test_auth_error_modal_quit_exits(make_app, fake_azure) -> None:
    fake_azure.auth_err = RuntimeError("AADSTS700082: … Please run 'az login'")

    async def scenario() -> None:
        app = make_app(demo_mode=False)
        async with app.run_test(size=SIZE) as pilot:
            await wait_for(pilot, lambda: isinstance(app.screen, AuthErrorModal))
            assert app.return_code is None
            await pilot.press("q")
            await wait_for(pilot, lambda: app.return_code is not None)
        assert app.return_code == 0
        assert ("check_auth",) in fake_azure.calls

    asyncio.run(scenario())
