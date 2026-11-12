"""Small helpers shared by several screens."""

from __future__ import annotations

from typing import Protocol

from textual.widget import Widget


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


def device_code_markup(url: str, code: str) -> str:
    """Markup for the Microsoft Graph device-code sign-in prompt."""
    return (
        "[bold]Sign in to Microsoft Graph[/bold]\n\n"
        f"[dim]1.[/dim] Open:  [link]{url}[/link]\n"
        f"[dim]2.[/dim] Enter code:  [bold]{code}[/bold]\n\n"
        "[dim]Waiting for authentication…[/dim]"
    )


def wrap_error_lines(msg: str, width: int = 80) -> str:
    """Hard-wrap each line of *msg* to at most *width* characters."""
    return "\n".join(
        line if len(line) <= width else "\n".join(line[i : i + width] for i in range(0, len(line), width))
        for line in msg.splitlines()
    )
