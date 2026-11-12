"""Small helpers shared by several screens."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from textual.content import Content
from textual.widget import Widget

from fomo import timefmt


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


class _RoleState(Protocol):
    """What the role lists show about an eligible Azure or Entra role's state."""

    @property
    def is_active(self) -> bool: ...
    @property
    def active_until(self) -> str | None: ...
    @property
    def expiry(self) -> str | None: ...


def role_state_tag(role: _RoleState, now: datetime) -> str:
    """The state after a role in a list: "● active · 47m left", "eligible until 2026-12-31" or "".

    An active role whose end is unknown (e.g. activated in this session) is
    just "● active"; an eligibility without an end date shows nothing.
    """
    if role.is_active:
        left = timefmt.format_remaining(role.active_until, now) if role.active_until else ""
        return f"● active · {left}" if left else "● active"
    if role.expiry:
        return f"eligible until {timefmt.format_date(role.expiry)}"
    return ""


def role_list_prompt(text: str, role: _RoleState, now: datetime) -> tuple[str, Content]:
    """A role list row: *text* followed by its :func:`role_state_tag`.

    Returns the plain text (for filtering) and the prompt to show, in which
    an active tag is green and an eligibility tag dim.
    """
    tag = role_state_tag(role, now)
    if not tag:
        return text, Content(text)
    template = "$text   [bold $success]$tag[/]" if role.is_active else "$text   [dim]$tag[/dim]"
    return f"{text}   {tag}", safe_markup(template, text=text, tag=tag)


def role_detail_state(role: _RoleState, now: datetime) -> tuple[str, str]:
    """The detail pane's active line (or "") and eligibility line, as plain text.

    "Active until 14:32 (47m left)", or "Currently active" without a known
    end; "Eligible until 2026-12-31" or "Eligible permanently".
    """
    active = ""
    if role.is_active and role.active_until:
        active = f"Active until {timefmt.format_end(role.active_until, now)}"
    elif role.is_active:
        active = "Currently active"
    eligible = f"Eligible until {timefmt.format_date(role.expiry)}" if role.expiry else "Eligible permanently"
    return active, eligible


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
