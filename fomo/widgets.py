"""Custom Textual widgets for fomo."""

from __future__ import annotations

from rich.segment import Segment
from rich.style import Style

from textual.strip import Strip
from textual.widgets import SelectionList
from textual.widgets._option_list import OptionDoesNotExist
from textual.widgets._toggle_button import ToggleButton


class FomoSelectionList(SelectionList):
    """SelectionList that uses ○/◉ to distinguish unselected/selected."""

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
                Segment(ToggleButton.BUTTON_LEFT, style=side_style),
                Segment(inner, style=button_style),
                Segment(ToggleButton.BUTTON_RIGHT, style=side_style),
                Segment(" ", style=underlying_style),
                *line,
            ]
        )
