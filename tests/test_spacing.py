"""The spacing system in app.tcss: every screen's content shares one gutter.

Titles, filters, lists, tables, the activation form and the tab labels all
start $gutter columns from the screen's edge (never flush against it), and
the activation screen's tables and buttons end the same distance from the
right edge.
"""

from __future__ import annotations

import asyncio

from textual.widgets import Input, TabbedContent, Tabs

from fomo import demo
from fomo.screens.activation_screen import ActivationScreen
from fomo.screens.assignments_screen import AssignmentsScreen
from tests.test_tui_smoke import _subs_loaded, make_app, wait_for  # noqa: F401  (fixture)

GUTTER = 2  # $gutter in app.tcss


def test_screens_share_one_gutter_at_80x24(make_app) -> None:  # noqa: F811
    async def scenario() -> None:
        app = make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await _subs_loaded(pilot)
            await pilot.pause()
            scope = app.screen
            lefts = {
                selector: scope.query_one(selector).region.x
                for selector in ("#loading-label", "#filter", "#sub-list", "#sel-count")
            }
            lefts["first tab label"] = scope.query_one(Tabs).query("Tab").first().content_region.x

            scope.query_one("#scope-tabs", TabbedContent).active = "tab-entra"
            await wait_for(pilot, lambda: scope.query_one("#entra-role-list").region.width)
            for selector in ("#entra-filter", "#entra-role-list", "#entra-status"):
                lefts[selector] = scope.query_one(selector).region.x

            assignments = AssignmentsScreen()
            await app.push_screen(assignments)
            await wait_for(pilot, lambda: assignments.query_one("#azure-table").region.width)
            for selector in ("#azure-loading", "#azure-table"):
                lefts[selector] = assignments.query_one(selector).region.x

            roles = demo.list_eligible_roles(demo.SUBSCRIPTIONS[0].id)
            activation = ActivationScreen(roles)
            await app.push_screen(activation)
            await wait_for(pilot, lambda: isinstance(app.focused, Input))
            await pilot.pause()
            for selector in ("#title", "#reason-label", "#roles-table", "#global-roles-box"):
                lefts[selector] = activation.query_one(selector).region.x

            assert lefts == dict.fromkeys(lefts, GUTTER)
            right = activation.size.width - GUTTER
            assert activation.query_one("#duration").region.right == right
            assert activation.query_one("#roles-scroll").region.right == right
            assert activation.query_one("#btn-activate").region.right == right

    asyncio.run(scenario())
