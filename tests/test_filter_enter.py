"""Enter in a filter input moves focus to its list and selects nothing.

Enter is a priority binding on ScopeScreen and RolesScreen, so the filters'
Input.Submitted never fires (F31); these tests pin the behaviour that users
actually get.
"""

from __future__ import annotations

import asyncio

from fomo.screens.roles_screen import RolesScreen
from tests.test_activation_screens import make_app  # noqa: F401  (fixture)
from tests.test_tui_smoke import SIZE, _list, _open_roles, _subs_loaded, _switch_to_entra, wait_for


def test_enter_in_subscription_filter_focuses_list_without_selecting(make_app) -> None:  # noqa: F811
    async def scenario() -> None:
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            subs = await _subs_loaded(pilot)
            app.screen.query_one("#filter").focus()
            await pilot.press("C", "o", "enter")
            await wait_for(pilot, lambda: app.focused is subs)
            assert list(subs.selected) == []

    asyncio.run(scenario())


def test_enter_in_entra_filter_focuses_list_without_selecting(make_app) -> None:  # noqa: F811
    async def scenario() -> None:
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            entra = await _switch_to_entra(pilot)
            app.screen.query_one("#entra-filter").focus()
            await pilot.press("R", "enter")
            await wait_for(pilot, lambda: app.focused is entra)
            assert list(entra.selected) == []

    asyncio.run(scenario())


def test_enter_in_roles_filter_focuses_list_without_selecting(make_app) -> None:  # noqa: F811
    async def scenario() -> None:
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            roles = await _open_roles(pilot)
            assert isinstance(app.screen, RolesScreen)
            app.screen.query_one("#filter").focus()
            await pilot.press("e", "enter")
            await wait_for(pilot, lambda: app.focused is roles)
            assert isinstance(app.screen, RolesScreen)
            assert list(roles.selected) == []
            assert app.screen._selected == set()
            assert _list(app, "#role-list") is roles

    asyncio.run(scenario())
