"""Keyboard navigation on the scope screen and in the selection lists.

- ``h``/``l`` switch tabs from anywhere on the scope screen and land on the
  target tab's list once it has loaded (F08).
- A ``FomoSelectionList`` that gains focus, or is rebuilt while focused,
  highlights its first selectable row (F09).  ``test_filter_enter.py`` covers
  what that means for Enter in a filter.

The tab tests run with ``animation_level = "none"``: otherwise every tab
switch waits for the tab underline animation.
"""

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Input, TabbedContent
from textual.widgets.selection_list import Selection

from fomo.screens.assignments_screen import AssignmentsScreen
from fomo.screens.roles_screen import RolesScreen
from fomo.screens.scope_screen import ScopeScreen
from fomo.widgets import FomoSelectionList
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


# ---------------------------------------------------------------------------
# F09: a list that gains focus highlights its first selectable row
# ---------------------------------------------------------------------------


class _ListApp(App[None]):
    def compose(self) -> ComposeResult:
        yield Input(id="other")
        # Empty at first, like the screens' lists: they are filled after mount,
        # and a list filled through its constructor already highlights a row.
        yield FomoSelectionList(id="list")


def test_focus_and_rebuild_highlight_first_enabled_row() -> None:
    async def scenario() -> None:
        app = _ListApp()
        async with app.run_test() as pilot:
            sl = app.query_one("#list", FomoSelectionList)
            await wait_for(pilot, lambda: isinstance(app.focused, Input))
            sl.add_options(
                [
                    Selection("separator", -1, disabled=True),
                    Selection("active", 0, disabled=True),
                    Selection("first", 1),
                    Selection("second", 2),
                ]
            )
            assert sl.highlighted is None
            sl.focus()
            await wait_for(pilot, lambda: sl.highlighted == 2)

            # A rebuild while focused highlights the first selectable row again.
            sl.clear_options()
            sl.add_option(Selection("active", 0, disabled=True))
            sl.add_option(Selection("second", 2))
            assert sl.highlighted == 1

            # Without focus a rebuild leaves nothing highlighted.
            app.query_one("#other").focus()
            await wait_for(pilot, lambda: not sl.has_focus)
            sl.clear_options()
            sl.add_option(Selection("first", 1))
            assert sl.highlighted is None

            # Only disabled rows: nothing to highlight.
            sl.clear_options()
            sl.add_option(Selection("active", 0, disabled=True))
            sl.focus()
            await wait_for(pilot, lambda: sl.has_focus)
            assert sl.highlighted is None

    asyncio.run(scenario())
