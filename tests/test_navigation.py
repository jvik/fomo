"""Keyboard navigation on the scope and roles screens.

``h``/``l`` switch tabs from anywhere on the scope screen and land on the
target tab's list once it has loaded (F08).

The apps run with ``animation_level = "none"``: otherwise every tab switch
waits for the tab underline animation.
"""

from __future__ import annotations

import asyncio

from textual.widgets import Input, TabbedContent

from fomo.screens.assignments_screen import AssignmentsScreen
from fomo.screens.roles_screen import RolesScreen
from fomo.screens.scope_screen import ScopeScreen
from tests.test_tui_smoke import (
    SIZE,
    _list,
    _subs_loaded,
    make_app,  # noqa: F401  (fixture)
    wait_for,
)


def _active_tab(app) -> str:
    return app.screen.query_one("#scope-tabs", TabbedContent).active


# ---------------------------------------------------------------------------
# F08: h/l switch tabs from anywhere
# ---------------------------------------------------------------------------


def test_l_and_h_switch_tabs_from_the_lists(make_app) -> None:  # noqa: F811
    async def scenario() -> None:
        app = make_app()
        app.animation_level = "none"
        async with app.run_test(size=SIZE) as pilot:
            subs = await _subs_loaded(pilot)
            subs.focus()
            await wait_for(pilot, lambda: app.focused is subs)

            await pilot.press("l")
            entra = _list(app, "#entra-role-list")
            await wait_for(pilot, lambda: _active_tab(app) == "tab-entra" and entra.option_count == 5)
            # Lazy-loaded on first activation, then focused once it has loaded.
            await wait_for(pilot, lambda: app.focused is entra)

            await pilot.press("h")
            await wait_for(pilot, lambda: _active_tab(app) == "tab-azure" and app.focused is subs)

            # Already loaded this time: focused straight away.
            await pilot.press("l")
            await wait_for(pilot, lambda: _active_tab(app) == "tab-entra" and app.focused is entra)

    asyncio.run(scenario())


def test_l_after_returning_from_roles_switches_tab_and_keys_still_work(make_app) -> None:  # noqa: F811
    async def scenario() -> None:
        app = make_app()
        app.animation_level = "none"
        async with app.run_test(size=SIZE) as pilot:
            subs = await _subs_loaded(pilot)
            subs.focus()
            subs.highlighted = 0
            await pilot.pause()
            await pilot.press("x", "enter")
            await wait_for(pilot, lambda: isinstance(app.screen, RolesScreen))
            await wait_for(pilot, lambda: _list(app, "#role-list").option_count > 0)
            await pilot.press("escape")
            await wait_for(pilot, lambda: isinstance(app.screen, ScopeScreen))

            await pilot.press("l")
            await wait_for(pilot, lambda: _active_tab(app) == "tab-entra")
            assert not isinstance(app.focused, Input)
            # Before the fix focus fell into the Azure filter and `i` was typed there.
            await pilot.press("i")
            await wait_for(pilot, lambda: isinstance(app.screen, AssignmentsScreen))

    asyncio.run(scenario())
