"""Shared logic for the Azure and Entra activation screens.

Both screens put the reason (justification) and duration form at the top, so
it stays visible on small terminals, followed by the selected roles in one or
more scrollable tables with a Status column, an error details panel that only
appears after a failure, and the Activate/Back buttons.  The subclasses define
their title, tables and columns and how a role is activated.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import ClassVar, Generic, TypeVar

from rich.cells import cell_len
from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.coordinate import Coordinate
from textual.events import Resize
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, RichLog, Select

from fomo import azure, tiering

_DURATION_OPTIONS: list[tuple[str, str]] = [
    ("30 min", "PT30M"),
    ("1 hour", "PT1H"),
    ("2 hours", "PT2H"),
    ("4 hours", "PT4H"),
    ("6 hours", "PT6H"),
    ("8 hours", "PT8H"),
]

RoleT = TypeVar("RoleT", azure.EligibleRole, azure.EntraEligibleRole)


def fit_column_widths(available: int, natural: Sequence[int], shrink: Sequence[tuple[int, int]]) -> list[int]:
    """Content widths for a table whose last column takes the width left over.

    *natural* holds each column's content width; for the last column it is the
    least it should get.  When the columns don't fit in *available* cells, the
    columns in *shrink*, ``(index, minimum)`` pairs, give up width in that
    order, each down to its minimum.  The last column then gets whatever is
    left, which is less than its natural width only if shrinking wasn't
    enough (but never less than 1).
    """
    widths = list(natural)
    excess = sum(widths) - available
    for index, minimum in shrink:
        if excess <= 0:
            break
        cut = min(excess, max(0, widths[index] - minimum))
        widths[index] -= cut
        excess -= cut
    widths[-1] = max(1, available - sum(widths[:-1]))
    return widths


def table_cell(text: str, style: str = "") -> Text:
    """A literal (never markup) table cell that is cut with "…" when too narrow."""
    return Text(text, style=style, overflow="ellipsis", no_wrap=True)


def tier_cell(info: tiering.TierInfo | None) -> Text:
    """Tier badge cell, e.g. "🔴 T0", or "—" without tier data."""
    if info is None:
        return table_cell("—", "dim")
    tier = info["tier"]
    return table_cell(f"{tiering.tier_badge(tier)} T{tier}", tiering.TIER_COLOUR.get(tier, ""))


def title_markup(count: int, noun: str) -> str:
    """Title line such as "Activate **3** roles" (*noun* is internal text, singular)."""
    return f"Activate [bold]{count}[/bold] {noun}{'' if count == 1 else 's'}"


def _cell_width(cell: object) -> int:
    return cell.cell_len if isinstance(cell, Text) else cell_len(str(cell))


class RoleTable(DataTable):
    """Role table whose last (Status) column takes the width the others leave.

    The table never scrolls sideways: when the columns don't fit, those in
    *shrink* (``(index, minimum)`` pairs) give up width first, in order, and
    their cells are cut with "…".  The surrounding container scrolls the
    table vertically, so the table itself takes no focus.
    """

    # The Status column gets at least this much room, so that it doesn't
    # jump when "✓ Provisioned" or "⏳ PendingApproval" replace "—".
    STATUS_MIN_WIDTH: ClassVar[int] = 17

    def __init__(self, *, shrink: Sequence[tuple[int, int]] = (), id: str | None = None) -> None:
        super().__init__(id=id, show_cursor=False)
        self.can_focus = False
        self._shrink = tuple(shrink)

    def on_resize(self, event: Resize) -> None:  # noqa: ARG002
        self.fit_columns()

    def set_status(self, row: int, text: Text) -> None:
        """Show *text* in the Status cell of *row*."""
        text.overflow = "ellipsis"
        text.no_wrap = True
        self.update_cell_at(Coordinate(row, len(self.columns) - 1), text)
        self.fit_columns()

    def fit_columns(self) -> None:
        """Size the columns to the table's current width."""
        columns = self.ordered_columns
        if not columns or not self.row_count:
            return
        available = self.scrollable_content_region.width - 2 * self.cell_padding * len(columns)
        if available <= 0:
            return
        natural = [
            max(_cell_width(column.label), *(_cell_width(cell) for cell in self.get_column_at(index)))
            for index, column in enumerate(columns)
        ]
        natural[-1] = max(natural[-1], self.STATUS_MIN_WIDTH)
        widths = fit_column_widths(available, natural, self._shrink)
        if all(not c.auto_width and c.width == w for c, w in zip(columns, widths, strict=True)):
            return
        for column, width in zip(columns, widths, strict=True):
            column.auto_width = False
            column.width = width
        # DataTable re-measures and redraws itself only when a cell changes.
        origin = Coordinate(0, 0)
        self.update_cell_at(origin, self.get_cell_at(origin), update_width=True)


class ActivationScreenBase(Screen, Generic[RoleT]):
    """Justification form plus per-role activation progress."""

    # Labels of the columns before Status.
    COLUMNS: ClassVar[tuple[str, ...]]
    # Logger and message used when an activation fails.
    _log: ClassVar[logging.Logger]
    _FAILURE_LOG_MESSAGE: ClassVar[str]

    def __init__(self, roles: list[RoleT]) -> None:
        super().__init__()
        self.roles: list[RoleT] = roles
        self._activating = False
        self._errors: dict[int, str] = {}  # running row index → full error message

    # ------------------------------------------------------------------
    # Subclass hooks
    # ------------------------------------------------------------------

    def _title(self) -> str:
        """Markup for the title line (no external text)."""
        raise NotImplementedError

    def _compose_tables(self) -> ComposeResult:
        """Yield the role tables (``RoleTable``) and anything around them."""
        raise NotImplementedError

    def _role_tables(self) -> Sequence[tuple[str, Sequence[RoleT]]]:
        """Return ``(table_id, roles)`` pairs in activation order."""
        raise NotImplementedError

    def _row_cells(self, role: RoleT) -> Sequence[Text]:
        """Return the cells of *role*'s row before the Status cell."""
        raise NotImplementedError

    def _activate(self, role: RoleT, justification: str, duration: str) -> str:
        """Submit one activation and return its status string."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="activation"):
            yield Label(self._title(), id="title")
            # The reason comes before the duration so that Tab moves from one to the other.
            with Horizontal(id="form"):
                yield Label("Reason", id="reason-label", classes="form-label")
                yield Input(placeholder="Justification (required, for all roles)", id="justification")
                yield Label("Duration", id="duration-label", classes="form-label")
                # No blank row: a blank Select's value is Select.NULL, which is
                # truthy and would reach activate_role as the duration.
                yield Select(_DURATION_OPTIONS, value="PT1H", allow_blank=False, id="duration")
            with VerticalScroll(id="roles-scroll"):
                yield from self._compose_tables()
            # Wrapped to the panel's width; it opens on the first failure, not the last.
            error_log = RichLog(
                id="error-log",
                wrap=True,
                markup=True,
                highlight=True,
                min_width=1,
                auto_scroll=False,
                classes="hidden",
            )
            error_log.border_title = "Details"
            yield error_log
            with Horizontal(id="buttons"):
                yield Button("Activate", variant="primary", id="btn-activate")
                yield Button("Back", id="btn-back")
        yield Footer()

    def on_mount(self) -> None:
        for table_id, roles in self._role_tables():
            table = self.query_one(f"#{table_id}", RoleTable)
            for label in (*self.COLUMNS, "Status"):
                table.add_column(label)
            for role in roles:
                table.add_row(*self._row_cells(role), table_cell("—"))
            self.call_after_refresh(table.fit_columns)
        self.query_one("#justification").focus()

    # ------------------------------------------------------------------
    # Form and button handlers
    # ------------------------------------------------------------------

    @on(Input.Submitted, "#justification")
    def on_justification_submitted(self, event: Input.Submitted) -> None:  # noqa: ARG002
        self._start_activation()

    @on(Button.Pressed, "#btn-back")
    def on_back_pressed(self) -> None:
        self.action_back()

    @on(Button.Pressed, "#btn-activate")
    def on_activate_pressed(self) -> None:
        self._start_activation()

    def _start_activation(self) -> None:
        """Activate every role, unless a run is going on or has finished."""
        btn_activate = self.query_one("#btn-activate", Button)
        if self._activating or btn_activate.disabled:
            return
        justification = self.query_one("#justification", Input).value.strip()
        if not justification:
            self.notify("Justification is required.", severity="warning")
            self.query_one("#justification").focus()
            return
        duration = self.query_one("#duration", Select).value or "PT1H"
        self._activating = True
        btn_activate.disabled = True
        self.query_one("#btn-back", Button).disabled = True
        self._run_activation(justification, duration)

    def action_back(self) -> None:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Background activation worker
    # ------------------------------------------------------------------

    @work(thread=True)
    def _run_activation(self, justification: str, duration: str) -> None:
        offset = 0
        for table_id, roles in self._role_tables():
            for i, role in enumerate(roles):
                self._activate_row(table_id, i, offset + i, role, justification, duration)
            offset += len(roles)
        self.app.call_from_thread(self._on_activation_done)

    def _activate_row(
        self,
        table_id: str,
        row: int,
        error_index: int,
        role: RoleT,
        justification: str,
        duration: str,
    ) -> None:
        """Activate *role* and show progress in its table row (worker thread)."""
        self.app.call_from_thread(self._set_status, table_id, row, Text("Activating…"))
        label: Text
        try:
            label = self._format_status(self._activate(role, justification, duration))
        except Exception as exc:
            full_error = str(exc)
            self._log.error(self._FAILURE_LOG_MESSAGE, role.role_name, full_error)
            self._errors[error_index] = full_error
            short = full_error[:30] + "…" if len(full_error) > 30 else full_error
            label = Text(f"✗ {short}")
            self.app.call_from_thread(self._append_error, role.role_name, full_error)
        self.app.call_from_thread(self._set_status, table_id, row, label)

    # ------------------------------------------------------------------
    # UI update helpers (called on the main thread via call_from_thread)
    # ------------------------------------------------------------------

    def _set_status(self, table_id: str, row: int, text: Text) -> None:
        """Set a Status cell.  Text is never parsed as markup."""
        self.query_one(f"#{table_id}", RoleTable).set_status(row, text)

    def _append_error(self, role_name: str, message: str) -> None:
        error_log = self.query_one("#error-log", RichLog)
        error_log.remove_class("hidden")
        # Text objects are written as-is: neither the role name nor the error
        # message is parsed as markup.  expand=True wraps at the panel's width
        # rather than the console's.
        error_log.write(Text(f"✗ {role_name}", style="bold red"), expand=True)
        error_log.write(error_log.highlighter(Text(message)), expand=True)
        error_log.write("")

    def _on_activation_done(self) -> None:
        self._activating = False
        btn_back = self.query_one("#btn-back", Button)
        btn_back.disabled = False
        btn_back.label = "Done"
        btn_back.focus()
        if self._errors:
            self.notify(
                f"{len(self._errors)} role(s) failed — see error details below.",
                severity="error",
                timeout=8,
            )
        else:
            self.notify("Activation requests submitted.", severity="information")

    @staticmethod
    def _format_status(status: str) -> Text:
        if status in ("Provisioned", "Granted", "DryRun"):
            return Text(f"✓ {status}", style="bold green")
        if "Pending" in status or status in ("Accepted", "ScheduleCreated"):
            return Text(f"⏳ {status}", style="bold yellow")
        if status in ("Failed", "Denied", "Canceled", "TimedOut"):
            return Text(f"✗ {status}", style="bold red")
        return Text(status)
