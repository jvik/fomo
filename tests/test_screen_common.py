"""Shared screen helpers in fomo.screens._common."""

from __future__ import annotations

import asyncio

from textual.content import Content
from textual.widgets import Label

from fomo.screens._common import device_code_markup, wrap_error_lines
from fomo.screens.scope_screen import ScopeScreen
from tests.test_activation_screens import make_app  # noqa: F401  (fixture)
from tests.test_tui_smoke import SIZE, _subs_loaded


def test_wrap_error_lines_wraps_each_line_on_its_own() -> None:
    msg = "short\n" + "a" * 85 + "\n" + "b" * 10
    assert wrap_error_lines(msg) == "short\n" + "a" * 80 + "\n" + "a" * 5 + "\n" + "b" * 10


def test_wrap_error_lines_custom_width() -> None:
    assert wrap_error_lines("abcdef", width=4) == "abcd\nef"


def test_device_code_markup() -> None:
    content = device_code_markup("https://example.test/device", "ABC123")
    expected = Content.from_markup(
        "[bold]Sign in to Microsoft Graph[/bold]\n\n"
        "[dim]1.[/dim] Open:  [link]https://example.test/device[/link]\n"
        "[dim]2.[/dim] Enter code:  [bold]ABC123[/bold]\n\n"
        "[dim]Waiting for authentication…[/dim]"
    )
    # Content.__eq__ compares plain text only; compare the styling too.
    assert (content.plain, content.spans) == (expected.plain, expected.spans)


def test_vim_keys_move_the_focused_list(make_app) -> None:  # noqa: F811
    async def scenario() -> None:
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            subs = await _subs_loaded(pilot)
            subs.focus()
            subs.highlighted = 0
            await pilot.pause()
            await pilot.press("j", "j")
            await pilot.pause()
            assert subs.highlighted == 2
            await pilot.press("k")
            await pilot.pause()
            assert subs.highlighted == 1

    asyncio.run(scenario())


def test_entra_error_wraps_each_long_line_on_its_own(make_app) -> None:  # noqa: F811
    msg = "Graph request failed:\n" + "x" * 120 + "\nTrace ID: 1"

    async def scenario() -> None:
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            await _subs_loaded(pilot)
            screen = app.screen
            assert isinstance(screen, ScopeScreen)
            screen._on_entra_error(msg)
            await pilot.pause()
            text = str(screen.query_one("#entra-loading-label", Label).visual)
            assert text.count("Graph request failed:") == 1
            assert text.count("x") == 120
            assert "Trace ID: 1" in text
            assert text == "Error:\n\nGraph request failed:\n" + "x" * 80 + "\n" + "x" * 40 + "\nTrace ID: 1"

    asyncio.run(scenario())
