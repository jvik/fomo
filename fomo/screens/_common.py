"""Small helpers shared by several screens."""

from __future__ import annotations

from typing import Protocol

from textual.content import Content
from textual.widget import Widget


def safe_markup(template: str, /, **values: object) -> Content:
    """Render *template* as Textual markup, inserting *values* as literal text.

    Every ``$name`` placeholder in *template* is replaced by ``str(values[name])``
    after the markup has been parsed, so the value is never read as markup:
    ``[/]``, ``[bold]``, ``[legacy]`` and backslashes show up exactly as given.

    This is the only way external text (Azure names and IDs, error messages,
    tiering data, device codes) may enter markup.  Never interpolate it into the
    template with an f-string.  Text that needs no styling at all can be passed
    as ``Content(text)``, and Rich-based widgets (``DataTable``, ``RichLog``)
    take ``rich.text.Text(text)``.
    """
    return Content.from_markup(template, **values)


class _HasFocus(Protocol):
    @property
    def focused(self) -> Widget | None: ...


class VimNavMixin:
    """``vim_down``/``vim_up``/``vim_top``/``vim_bottom`` actions for a Screen.

    Each action forwards to the focused widget if it supports the movement.
    The screen still declares its own ``j``/``k``/``g``/``G`` bindings.
    """

    def action_vim_down(self: _HasFocus) -> None:
        w = self.focused
        if w is not None and hasattr(w, "action_cursor_down"):
            w.action_cursor_down()

    def action_vim_up(self: _HasFocus) -> None:
        w = self.focused
        if w is not None and hasattr(w, "action_cursor_up"):
            w.action_cursor_up()

    def action_vim_top(self: _HasFocus) -> None:
        w = self.focused
        if w is not None and hasattr(w, "scroll_home"):
            w.scroll_home(animate=False)

    def action_vim_bottom(self: _HasFocus) -> None:
        w = self.focused
        if w is not None and hasattr(w, "scroll_end"):
            w.scroll_end(animate=False)


def device_code_markup(url: str, code: str) -> Content:
    """Content for the Microsoft Graph device-code sign-in prompt."""
    return safe_markup(
        "[bold]Sign in to Microsoft Graph[/bold]\n\n"
        "[dim]1.[/dim] Open:  [link]$url[/link]\n"
        "[dim]2.[/dim] Enter code:  [bold]$code[/bold]\n\n"
        "[dim]Waiting for authentication…[/dim]",
        url=url,
        code=code,
    )


def wrap_error_lines(msg: str, width: int = 80) -> str:
    """Hard-wrap each line of *msg* to at most *width* characters."""
    return "\n".join(
        line if len(line) <= width else "\n".join(line[i : i + width] for i in range(0, len(line), width))
        for line in msg.splitlines()
    )
