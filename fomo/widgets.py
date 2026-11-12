"""Custom Textual widgets for fomo."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Self

from rich.segment import Segment
from rich.style import Style
from textual import events
from textual.strip import Strip
from textual.widgets import SelectionList
from textual.widgets.option_list import OptionDoesNotExist

# Same half-block characters as Textual's ToggleButton.BUTTON_LEFT/BUTTON_RIGHT
# (a private class), so the toggle keeps its look without the private import.
BUTTON_LEFT = "▐"
BUTTON_RIGHT = "▌"


class FomoSelectionList(SelectionList):
    """SelectionList that uses ○/◉ to distinguish unselected/selected.

    A list that gains focus, or is filled while it has focus, highlights its
    first selectable row, so the first Space toggles something.  A list filled
    after mount otherwise has no highlighted row at all.
    """

    def _highlight_first_enabled(self) -> None:
        """Highlight the first enabled row if no row is highlighted."""
        if self.highlighted is not None or self.option_count == 0:
            return
        first = next((i for i, option in enumerate(self.options) if not option.disabled), None)
        if first is not None:
            self.highlighted = first

    def on_focus(self, _event: events.Focus) -> None:
        self._highlight_first_enabled()

    def add_options(self, items: Iterable[Any]) -> Self:
        # Also covers add_option and set_options, which go through here.
        super().add_options(items)
        if self.has_focus:
            self._highlight_first_enabled()
        return self

    def render_line(self, y: int) -> Strip:
        line = super(SelectionList, self).render_line(y)

        _, scroll_y = self.scroll_offset
        selection_index = scroll_y + y
        try:
            selection = self.get_option_at_index(selection_index)
        except OptionDoesNotExist:
            return line

        is_selected = selection.value in self._selected
        component_style = "selection-list--button"
        if is_selected:
            component_style += "-selected"
        if self.highlighted == selection_index:
            component_style += "-highlighted"

        underlying_style = next(iter(line)).style or self.rich_style
        assert underlying_style is not None

        button_style = self.get_component_rich_style(component_style)
        side_style = Style.from_color(button_style.bgcolor, underlying_style.bgcolor)
        side_style += Style(meta={"option": selection_index})
        button_style += Style(meta={"option": selection_index})

        inner = "◉" if is_selected else "○"

        return Strip(
            [
                Segment(BUTTON_LEFT, style=side_style),
                Segment(inner, style=button_style),
                Segment(BUTTON_RIGHT, style=side_style),
                Segment(" ", style=underlying_style),
                *line,
            ]
        )
