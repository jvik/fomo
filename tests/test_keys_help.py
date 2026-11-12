"""Keys screen (``?``/F1) and consistent footers (F35).

The Keys screen is generated from the active screen's bindings, hidden ones
included, so it lists keys the footer has no room for (``x``, ``h``/``l``,
``j``/``k``, ``g``/``G``).  Every footer shows Quit, as ``q`` where q quits
and as ``ctrl+c`` while typing or where q goes back, plus Back where it
applies, and still fits 80 columns.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from textual.actions import SkipAction
from textual.binding import Binding
from textual.pilot import Pilot
from textual.screen import Screen
from textual.widgets import Footer, Input
from textual.widgets._footer import FooterKey, FooterLabel

from fomo import demo
from fomo.app import PimApp
from fomo.azure import EligibleRole
from fomo.screens.activation_screen import ActivationScreen
from fomo.screens.assignments_screen import AssignmentsScreen
from fomo.screens.keys_screen import KeyRow, KeysScreen, binding_rows, key_label
from fomo.screens.roles_screen import RolesScreen
from fomo.widgets import FomoSelectionList
from tests.test_tui_smoke import _subs_loaded, make_app, wait_for  # noqa: F401  (fixture)

SUB_ID = demo.SUBSCRIPTIONS[0].id
ROLE = EligibleRole("Reader", f"/subscriptions/{SUB_ID}/x/Reader", f"/subscriptions/{SUB_ID}", "Prod", "u", "s", None)


def test_key_label_spells_keys_out() -> None:
    keys = ("enter", "escape", "slash", "question_mark", "ctrl+s", "shift+tab", "f1", "G", "x")
    assert [key_label(key) for key in keys] == ["Enter", "Esc", "/", "?", "Ctrl+S", "Shift+Tab", "F1", "G", "x"]


def test_binding_rows_share_rows_by_group_and_description() -> None:
    move = Binding.Group("Move")
    bindings = [
        Binding("j", "down", "Down", show=False, group=move),
        Binding("k", "up", "Up", show=False, group=move),
        Binding("escape", "back", "Back"),
        Binding("q", "back", "Back", show=False),
        Binding("r", "retry", "Retry"),  # disabled below: a row of its own
        Binding("ctrl+c", "quit_a", "Quit", priority=True),
        Binding("ctrl+c", "quit", "Quit", show=False),  # same key: not repeated
        Binding("tab", "nothing", ""),  # no description: left out
    ]
    rows = binding_rows(bindings, lambda binding: binding.key != "r")
    assert rows == [
        KeyRow("j / k", "Move"),
        KeyRow("Esc / q", "Back"),
        KeyRow("r", "Retry", enabled=False),
        KeyRow("Ctrl+C", "Quit"),
    ]


def _footer(screen: Screen) -> list[tuple[str, str]]:
    """(key, description) of the footer entries, in footer order, one per action."""
    seen: set[str] = set()
    entries = []
    for key, active in screen.active_bindings.items():
        if active.binding.show and active.binding.action not in seen:
            seen.add(active.binding.action)
            entries.append((key, active.binding.description))
    return entries


def _assert_footer_fits(screen: Screen) -> None:
    footer = screen.query_one(Footer)
    items = [w for w in footer.query("*") if isinstance(w, FooterKey | FooterLabel)]
    assert items and max(w.region.right for w in items) <= screen.size.width


async def _open_keys(pilot: Pilot, key: str) -> KeysScreen:
    await pilot.press(key)
    await wait_for(pilot, lambda: isinstance(pilot.app.screen, KeysScreen))
    screen = pilot.app.screen
    assert isinstance(screen, KeysScreen)
    return screen


def test_keys_screen_and_footers_on_every_screen(make_app) -> None:  # noqa: F811
    async def scenario() -> None:
        app = make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            # Scope: q quits, so the footer shows q, not ctrl+c; both app keys come last.
            subs = await _subs_loaded(pilot)
            scope = app.screen
            subs.focus()
            await pilot.pause()
            footer = _footer(scope)
            assert footer[-2:] == [("q", "Quit"), ("question_mark", "Keys")]
            assert ("ctrl+c", "Quit") not in footer
            _assert_footer_fits(scope)
            keys = await _open_keys(pilot, "question_mark")
            assert KeyRow("x", "Toggle") in keys.screen_rows
            assert KeyRow("h / l", "Tabs") in keys.screen_rows
            assert KeyRow("↑ / ↓ / j / k", "Move") in keys.screen_rows
            assert KeyRow("g / G", "Top / Bottom") in keys.screen_rows
            assert KeyRow("Ctrl+C", "Quit") in keys.app_rows
            await pilot.press("question_mark")  # ? closes it again
            await wait_for(pilot, lambda: app.screen is scope)

            # Typing in the filter: q and ? would be typed, so ctrl+c and F1.
            scope.query_one("#filter", Input).focus()
            await pilot.pause()
            assert _footer(scope)[-2:] == [("ctrl+c", "Quit"), ("f1", "Keys")]

            # Roles: q goes back; F1 opens the keys from the (focused) filter.
            roles = RolesScreen([SUB_ID])
            await app.push_screen(roles)
            await wait_for(pilot, lambda: roles.query_one("#role-list", FomoSelectionList).option_count > 0)
            await wait_for(pilot, lambda: isinstance(app.focused, Input))
            footer = _footer(roles)
            assert ("escape", "Back") in footer
            assert footer[-2:] == [("ctrl+c", "Quit"), ("f1", "Keys")]
            keys = await _open_keys(pilot, "f1")
            assert KeyRow("x", "Toggle") in keys.screen_rows
            assert KeyRow("Esc / q", "Back") in keys.screen_rows
            assert not any("Tabs" in row.description for row in keys.screen_rows)
            await pilot.press("escape")
            await wait_for(pilot, lambda: app.screen is roles)
            assert roles.query_one("#filter", Input).value == ""
            roles.query_one("#role-list").focus()
            await pilot.pause()
            assert _footer(roles)[-2:] == [("ctrl+c", "Quit"), ("question_mark", "Keys")]
            _assert_footer_fits(roles)

            # Activation, before a run: the after-run keys are listed, dimmed.
            activation = ActivationScreen([ROLE])
            await app.push_screen(activation)
            await wait_for(pilot, lambda: isinstance(app.focused, Input))
            back = activation.query_one("#btn-back")
            back.focus()
            await wait_for(pilot, lambda: app.focused is back)
            assert _footer(activation) == [("escape", "Back"), ("ctrl+c", "Quit"), ("question_mark", "Keys")]
            keys = await _open_keys(pilot, "question_mark")
            assert KeyRow("r", "Retry failed", enabled=False) in keys.screen_rows
            assert not any(row.keys in ("x", "h / l") for row in keys.screen_rows)
            await pilot.press("f1")  # F1 closes it too
            await wait_for(pilot, lambda: app.screen is activation)

            # Assignments.
            assignments = AssignmentsScreen()
            await app.push_screen(assignments)
            await pilot.pause()
            footer = _footer(assignments)
            assert footer[0] == ("escape", "Back")
            assert footer[-2:] == [("ctrl+c", "Quit"), ("question_mark", "Keys")]
            _assert_footer_fits(assignments)
            keys = await _open_keys(pilot, "question_mark")
            assert KeyRow("j / k", "Move") in keys.screen_rows

            # ctrl+c quits, from the Keys screen too.
            assert app.return_code is None
            await pilot.press("ctrl+c")
            await wait_for(pilot, lambda: app.return_code is not None)
        assert app.return_code == 0

    asyncio.run(scenario())


def test_ctrl_c_leaves_selected_text_to_be_copied() -> None:
    """With text selected, the footer's ctrl+c skips, so the field's copy binding runs."""
    exits: list[bool] = []

    def _app(field_selection: str, screen_selection: str | None) -> SimpleNamespace:
        return SimpleNamespace(
            focused=SimpleNamespace(selected_text=field_selection),
            screen=SimpleNamespace(get_selected_text=lambda: screen_selection),
            exit=lambda: exits.append(True),
        )

    for selection in (("abc", None), ("", "abc")):
        with pytest.raises(SkipAction):
            PimApp.action_quit_ctrl_c(_app(*selection))  # type: ignore[arg-type]
    assert not exits
    PimApp.action_quit_ctrl_c(_app("", None))  # type: ignore[arg-type]
    assert exits == [True]
