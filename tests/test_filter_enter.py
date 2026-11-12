"""Enter in a filter input moves focus to its list, ready for Space.

Enter is a priority binding on ScopeScreen and RolesScreen, so the filters'
Input.Submitted never fires (F31).  While a filter has focus the footer labels
Enter "To list"; Enter itself selects nothing, and the list highlights its
first selectable row on focus, so the first Space selects the first match
(F09).
"""

from __future__ import annotations

import asyncio

from textual.widgets import Input

from fomo.screens.roles_screen import RolesScreen
from fomo.screens.scope_screen import ScopeScreen
from fomo.widgets import FomoSelectionList
from tests.test_activation_screens import make_app  # noqa: F401  (fixture)
from tests.test_tui_smoke import SIZE, _subs_loaded, _switch_to_entra, wait_for

PROD_ID = "11111111-1111-1111-1111-111111111111"  # demo "Contoso Production"
SHARED_ID = "33333333-3333-3333-3333-333333333333"  # demo "Contoso Shared Services"


def _enter_label(screen) -> str:
    return screen.active_bindings["enter"].binding.description


def test_enter_in_subscription_filter_focuses_list_then_space_selects_first_match(make_app) -> None:  # noqa: F811
    async def scenario() -> None:
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            subs = await _subs_loaded(pilot)
            screen = app.screen
            assert isinstance(screen, ScopeScreen)
            filt = screen.query_one("#filter", Input)
            filt.focus()
            await wait_for(pilot, lambda: app.focused is filt)
            await pilot.press("p", "r", "o", "d")
            await wait_for(pilot, lambda: subs.option_count == 1)
            assert _enter_label(screen) == "To list"

            await pilot.press("enter")
            await wait_for(pilot, lambda: app.focused is subs)
            assert list(subs.selected) == []
            assert subs.highlighted == 0
            assert _enter_label(screen) == "Proceed"

            await pilot.press("space")
            await wait_for(pilot, lambda: screen._selected_ids == {PROD_ID})

    asyncio.run(scenario())


def test_enter_in_entra_filter_focuses_list_without_selecting(make_app) -> None:  # noqa: F811
    async def scenario() -> None:
        app = make_app()
        app.animation_level = "none"  # don't wait for the tab underline
        async with app.run_test(size=SIZE) as pilot:
            entra = await _switch_to_entra(pilot)
            app.screen.query_one("#entra-filter").focus()
            await pilot.press("R", "enter")
            await wait_for(pilot, lambda: app.focused is entra)
            assert list(entra.selected) == []
            assert entra.highlighted == 0

    asyncio.run(scenario())


async def _roles_screen(pilot) -> tuple[RolesScreen, Input, FomoSelectionList]:
    """Open the roles screen for Contoso Production and Shared Services."""
    app = pilot.app
    await wait_for(pilot, lambda: isinstance(app.screen, ScopeScreen))
    app.push_screen(RolesScreen([PROD_ID, SHARED_ID]))
    await wait_for(pilot, lambda: isinstance(app.screen, RolesScreen))
    screen = app.screen
    assert isinstance(screen, RolesScreen)
    # The filter gets focus once the roles have loaded.
    await wait_for(pilot, lambda: app.focused is screen.query_one("#filter"))
    return screen, screen.query_one("#filter", Input), screen.query_one("#role-list", FomoSelectionList)


def test_enter_in_roles_filter_focuses_list_then_space_selects_first_match(make_app) -> None:  # noqa: F811
    async def scenario() -> None:
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            screen, filt, roles = await _roles_screen(pilot)
            assert _enter_label(screen) == "To list"

            filt.value = "key vault"  # the subscription test types its filter
            await wait_for(pilot, lambda: roles.option_count == 1)
            await pilot.press("enter")
            await wait_for(pilot, lambda: app.focused is roles)
            assert isinstance(app.screen, RolesScreen)
            assert screen._selected == set()
            assert _enter_label(screen) == "Activate selected"

            await pilot.press("space")
            await wait_for(pilot, lambda: len(screen._selected) == 1)
            expected = next(i for i, r in enumerate(screen.all_roles) if r.role_name == "Key Vault Administrator")
            assert screen._selected == {expected}

    asyncio.run(scenario())


def test_initial_highlight_skips_active_roles(make_app) -> None:  # noqa: F811
    async def scenario() -> None:
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            screen, filt, roles = await _roles_screen(pilot)
            filt.value = "contributor"
            await wait_for(pilot, lambda: roles.option_count == 3)
            # Row 0 is the active, and so disabled, Contributor role.
            assert roles.get_option_at_index(0).disabled
            assert roles.highlighted is None

            await pilot.press("enter")
            await wait_for(pilot, lambda: app.focused is roles)
            assert roles.highlighted == 1
            await pilot.press("space")
            await wait_for(pilot, lambda: len(screen._selected) == 1)
            (selected,) = screen._selected
            assert screen.all_roles[selected].role_name == "Monitoring Contributor"

            # Changing the sort rebuilds the focused list: the highlight moves
            # to the first selectable row again instead of disappearing.
            await pilot.press("ctrl+s")
            await wait_for(pilot, lambda: screen._sort_mode == "scope")
            assert roles.highlighted is not None
            assert not roles.get_option_at_index(roles.highlighted).disabled

    asyncio.run(scenario())
