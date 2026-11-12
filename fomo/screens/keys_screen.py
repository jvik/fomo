"""Keys screen (``?`` or F1): the keys of the screen below and the app-wide keys.

The rows are generated from the bindings, the hidden ones included, so the
panel never goes out of date.  Bindings in the same ``Binding.Group`` (``j``
and ``k``: Move), and neighbours with the same description (``Esc`` and
``q``: Back), share a row.  Keys that don't apply right now, such as the
after-run keys of an activation screen, are dimmed.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from textual.actions import parse as parse_action
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.screen import ModalScreen, Screen
from textual.widgets import Label, Static

from fomo.screens._common import safe_markup

# Readable names for the keys that Textual spells out.
_KEY_NAMES = {
    "enter": "Enter",
    "escape": "Esc",
    "tab": "Tab",
    "space": "Space",
    "slash": "/",
    "question_mark": "?",
    "up": "↑",
    "down": "↓",
    "left": "←",
    "right": "→",
}


def key_label(key: str) -> str:
    """A readable name for a Textual key: "Enter", "Esc", "/", "Ctrl+S", "Shift+Tab", "F1", "G"."""
    *modifiers, name = key.split("+")
    if name in _KEY_NAMES:
        label = _KEY_NAMES[name]
    elif len(name) == 1:
        label = name.upper() if modifiers else name
    else:
        label = name.capitalize()
    return "+".join([*(modifier.capitalize() for modifier in modifiers), label])


@dataclass(frozen=True)
class KeyRow:
    """One row of the Keys screen: "j / k", "Move"."""

    keys: str
    description: str
    enabled: bool = True


def binding_rows(bindings: Iterable[BindingType], enabled: Callable[[Binding], bool] | None = None) -> list[KeyRow]:
    """The Keys screen rows for *bindings*, in their order.

    A binding in a group is described by the group; one without a
    description is left out.  Neighbouring bindings with the same
    description and the same *enabled* state share a row, and a key that
    is already in its row isn't repeated.
    """
    rows: list[tuple[list[str], str, bool]] = []
    for binding in Binding.make_bindings(bindings):
        description = binding.group.description if binding.group is not None else binding.description
        if not description:
            continue
        key = key_label(binding.key)
        on = enabled(binding) if enabled is not None else True
        if rows and rows[-1][1:] == (description, on):
            if key not in rows[-1][0]:
                rows[-1][0].append(key)
            continue
        rows.append(([key], description, on))
    return [KeyRow(" / ".join(keys), description, on) for keys, description, on in rows]


def screen_key_rows(screen: Screen) -> list[KeyRow]:
    """Rows for the bindings of *screen*'s class, dimmed where its ``check_action`` says no."""

    def _enabled(binding: Binding) -> bool:
        namespace, action, parameters = parse_action(binding.action)
        target = screen.app if namespace == "app" else screen
        return target.check_action(action, parameters) is True

    return binding_rows(type(screen).BINDINGS, _enabled)


def _rows_content(rows: list[KeyRow]) -> Content:
    """The rows as two aligned columns: bold keys and their description, dim if they don't apply."""
    width = max((len(row.keys) for row in rows), default=0)
    lines = [
        safe_markup(
            "[bold]$keys[/bold]  $description" if row.enabled else "[dim]$keys  $description[/dim]",
            keys=row.keys.ljust(width),
            description=row.description,
        )
        for row in rows
    ]
    return Content("\n").join(lines)


class KeysScreen(ModalScreen[None]):
    """The keys of the screen below (*screen_rows*) and the app-wide ones (*app_rows*).

    The two lists sit side by side, so that even the longest one fits an
    80x24 terminal; below that size the lists scroll.  Escape or ``?``
    closes the screen (F1 too, through the app's binding).
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("question_mark", "close", "Close"),
    ]

    def __init__(self, screen_rows: list[KeyRow], app_rows: list[KeyRow]) -> None:
        super().__init__()
        self.screen_rows = screen_rows
        self.app_rows = app_rows

    def compose(self) -> ComposeResult:
        with Vertical(id="keys-dialog") as dialog:
            dialog.border_title = "Keys"
            with VerticalScroll(id="keys-list"), Horizontal(id="keys-columns"):
                with Vertical(classes="keys-column"):
                    yield Label("This screen", classes="keys-heading")
                    yield Static(_rows_content(self.screen_rows), id="keys-screen")
                with Vertical(classes="keys-column"):
                    yield Label("Everywhere", classes="keys-heading")
                    yield Static(_rows_content(self.app_rows), id="keys-app")
            dimmed = any(not row.enabled for row in (*self.screen_rows, *self.app_rows))
            hint = "Dimmed keys don't apply right now.  Esc or ? closes this." if dimmed else "Esc or ? closes this."
            yield Label(Content.styled(hint, "dim"), id="keys-hint")

    def action_close(self) -> None:
        self.dismiss()
