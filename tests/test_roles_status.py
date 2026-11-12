"""Roles screen counts, activation order and load failures (F36).

- "M/T shown" used to leave out the active (disabled) rows, so a list with
  nothing filtered out read "2/3 shown".  Now every listed role counts, but
  not the global-assignments separator.
- The activation screen got the selected roles in the order they were loaded,
  not the order the list shows them.
- A subscription that failed to load only showed an 8-second toast.  Now the
  status line keeps saying so, and ``e`` lists the failures with a Retry.
"""

from __future__ import annotations

import asyncio

from textual.widgets import Input, Label

from fomo.azure import Subscription
from fomo.screens.activation_screen import ActivationScreen
from fomo.screens.roles_screen import LoadErrorsModal, RolesScreen
from fomo.widgets import FomoSelectionList
from tests.conftest import ROOT_MG, role
from tests.test_tui_markup import _scope_ready, _text, make_live_app  # noqa: F401
from tests.test_tui_smoke import SIZE, _prompts, wait_for


def test_counts_include_active_rows_and_activation_follows_display_order(make_live_app, fake_azure) -> None:  # noqa: F811
    # Loaded in this order; the list shows them by name.
    fake_azure.roles = {
        "s1": [
            role("Website Contributor", "/subscriptions/s1"),
            role("Key Vault Reader", "/subscriptions/s1"),
            role("Reader", "/subscriptions/s1", active=True),
        ]
    }

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE) as pilot:
            await _scope_ready(pilot)
            screen = RolesScreen(["s1"])
            await app.push_screen(screen)
            role_list = screen.query_one("#role-list", FomoSelectionList)
            status = screen.query_one("#status", Label)
            await wait_for(pilot, lambda: role_list.option_count == 3)
            assert _prompts(role_list) == [
                "Key Vault Reader  —  s1",
                "Reader  —  s1   ● active",
                "Website Contributor  —  s1",
            ]
            assert _text(status) == "0 selected · 3/3 shown · sort: name"

            screen.query_one("#filter", Input).value = "reader"
            await wait_for(pilot, lambda: role_list.option_count == 2)
            assert _text(status) == "0 selected · 2/3 shown · sort: name"
            screen.query_one("#filter", Input).value = ""
            await wait_for(pilot, lambda: role_list.option_count == 3)

            role_list.focus()
            await pilot.press("a")
            await wait_for(pilot, lambda: _text(status).startswith("2 selected"))
            assert _text(status) == "2 selected · 3/3 shown · sort: name"

            await pilot.press("enter")
            await wait_for(pilot, lambda: isinstance(app.screen, ActivationScreen))
            activation = app.screen
            assert isinstance(activation, ActivationScreen)
            assert [r.role_name for r in activation.roles] == ["Key Vault Reader", "Website Contributor"]

            # The global-assignments separator is not a role, and "a" (select
            # all) skips it and the active role.
            screen.all_roles.append(role("Owner", ROOT_MG, disp="Tenant Root"))
            screen._rebuild_list("")
            assert role_list.option_count == 5
            assert _text(status) == "2 selected · 4/4 shown · sort: name"
            screen.action_select_all_visible()
            await pilot.pause()
            assert _text(status) == "3 selected · 4/4 shown · sort: name"
            assert sorted(role_list.selected) == sorted(screen._selected) == [0, 1, 3]

    asyncio.run(scenario())


def test_failed_subscription_stays_in_the_status_line_and_e_retries_it(make_live_app, fake_azure) -> None:  # noqa: F811
    fake_azure.subs.append(Subscription("s3", "Contoso Test"))
    fake_azure.roles["s3"] = [role("Owner", "/subscriptions/s3")]
    fake_azure.roles_err["s3"] = "ERROR: (AuthorizationFailed) no [x] access"
    names = {sub.id: sub.name for sub in fake_azure.subs}

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE) as pilot:
            await _scope_ready(pilot)
            screen = RolesScreen(["s1", "s2", "s3"], names)
            await app.push_screen(screen)
            role_list = screen.query_one("#role-list", FomoSelectionList)
            status = screen.query_one("#status", Label)
            await wait_for(pilot, lambda: role_list.option_count > 0)
            assert _text(status).splitlines()[1] == "⚠ 1 of 3 subscriptions failed · e details"

            role_list.focus()
            await pilot.press("e")
            await wait_for(pilot, lambda: isinstance(app.screen, LoadErrorsModal))
            modal = app.screen
            assert _text(modal.query_one("#load-errors-title", Label)) == "1 subscription failed to load"
            assert [_text(label) for label in modal.query(".load-error").results(Label)] == [
                "Contoso Test  s3\nERROR: (AuthorizationFailed) no [x] access"
            ]

            del fake_azure.roles_err["s3"]
            await pilot.press("r")
            await wait_for(pilot, lambda: "Owner  —  s3" in _prompts(role_list))
            assert app.screen is screen
            assert "failed" not in _text(status)
            assert fake_azure.calls.count(("list_eligible_roles", "s3")) == 2
            assert fake_azure.calls.count(("list_eligible_roles", "s1")) == 1

    asyncio.run(scenario())
