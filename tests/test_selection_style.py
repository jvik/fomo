"""Selected rows stand out (F34).

A selected row used to differ from the others only by its one-cell ◉, which
was faint in the light theme (3.6:1 on the toggle background), and the
highlighted ○ was white on light grey (1.4:1).  Selected rows now have bold
text and a bold ◉ in the theme's legible success colour.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from rich.segment import Segment
from rich.style import Style
from textual.app import App, ComposeResult

from fomo import app as app_module
from fomo.widgets import FomoSelectionList


class _ListApp(App):
    """Just a FomoSelectionList, styled by fomo's stylesheet and themes."""

    CSS_PATH = str(Path(app_module.__file__).with_name("app.tcss"))

    def __init__(self, theme: str) -> None:
        super().__init__()
        self.register_theme(app_module.FOMO_DARK)
        self.register_theme(app_module.FOMO_LIGHT)
        self.theme = theme

    def compose(self) -> ComposeResult:
        yield FomoSelectionList(("Alpha", 0), ("Beta [beta]", 1, True), ("Gamma", 2))


def _luminance(style: Style, background: bool) -> float:
    color = style.bgcolor if background else style.color
    assert color is not None and color.triplet is not None
    channels = [c / 255 for c in color.triplet]
    r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(style: Style) -> float:
    """WCAG contrast ratio of a segment's text against its background."""
    high, low = sorted((_luminance(style, False), _luminance(style, True)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _row(widget: FomoSelectionList, y: int) -> tuple[Segment, list[Segment]]:
    """The toggle segment and the text segments of row *y*."""
    segments = list(widget.render_line(y))
    return segments[1], [s for s in segments[4:] if s.text.strip()]


@pytest.mark.parametrize("theme", ["fomo-dark", "fomo-light"])
def test_selected_rows_are_bold_with_a_legible_success_toggle(theme: str) -> None:
    async def scenario() -> None:
        app = _ListApp(theme)
        async with app.run_test(size=(40, 8)) as pilot:
            widget = app.query_one(FomoSelectionList)
            widget.focus()
            widget.highlighted = 2
            await pilot.pause()

            toggle, text = _row(widget, 1)  # selected
            assert toggle.text == "◉"
            assert toggle.style.bold
            assert toggle.style.color is not None and toggle.style.color.triplet is not None
            assert toggle.style.color.triplet.hex == app.theme_variables["text-success"].lower()
            assert _contrast(toggle.style) >= 4.5
            assert text and all(s.style.bold for s in text)

            toggle, text = _row(widget, 0)  # not selected
            assert toggle.text == "○"
            assert not toggle.style.bold
            assert text and not any(s.style.bold for s in text)

            toggle, _ = _row(widget, 2)  # highlighted, not selected
            assert toggle.text == "○"
            assert _contrast(toggle.style) >= 4.5

    asyncio.run(scenario())
