"""Shared logic for the Azure and Entra activation screens.

Both screens put the reason (justification) and duration form at the top, so
it stays visible on small terminals, followed by the selected roles in one or
more scrollable tables with a Status column, an error details panel that only
appears after a failure, and the Back and Activate buttons at the bottom
right.  The subclasses define their title, tables and columns and how a role
is activated.

When a run finishes, a summary toast reports the outcomes and the screen
offers the next steps: retry the failed roles (``r``, or the Activate button,
relabelled "Retry failed (N)"), show the active assignments (``i``), quit
(``q``), or Done (Enter), which returns to the first screen.  The screen
dismisses with an :class:`ActivationResult`, so the screen below can mark the
activated roles active and clear its selection.

A run in which any request went through is remembered as a recent activation
(``app.recents``), so that the scope screen can start it again; the form can
be prefilled with a recent activation's justification and duration.
"""

from __future__ import annotations

import enum
import logging
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import ClassVar, Generic, TypeVar

from rich.cells import cell_len
from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.coordinate import Coordinate
from textual.events import Resize
from textual.notifications import SeverityLevel
from textual.widget import Widget
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, RichLog, Select

from fomo import azure, state, tiering
from fomo.screens._common import FomoScreen

_DURATION_OPTIONS: list[tuple[str, str]] = [
    ("30 min", "PT30M"),
    ("1 hour", "PT1H"),
    ("2 hours", "PT2H"),
    ("4 hours", "PT4H"),
    ("6 hours", "PT6H"),
    ("8 hours", "PT8H"),
]
DEFAULT_DURATION = "PT1H"

RoleT = TypeVar("RoleT", azure.EligibleRole, azure.EntraEligibleRole)

# An ISO 8601 duration such as PT4H, PT30M or P1DT12H.
_ISO_DURATION = r"P(?=\d|T\d)(?:\d+[YMWD])*(?:T(?:\d+[HMS])+)?"
# The first duration after "max"/"maximum": the policy's allowed maximum.
_MAX_DURATION_RE = re.compile(rf"(?i:max)[^\n]*?\b({_ISO_DURATION})\b")
_MFA_RE = re.compile(r"MfaRule|\bMFA\b")
_SHORT_ERROR_LENGTH = 40

# The activation screens' full layout needs this many terminal rows to keep
# two table rows in view with the details panel open (see app.tcss).
_TALL_HEIGHT = 28


def summarize_activation_error(message: str) -> str:
    """A short, human status for a failed activation.

    Recognises the common ARM and Microsoft Graph policy errors; anything else
    is cut to the first 40 characters of its first line.  The details panel
    always shows the full *message*.
    """
    if "ExpirationRule" in message:
        match = _MAX_DURATION_RE.search(message)
        return f"Exceeds max duration ({match.group(1)})" if match else "Exceeds max duration"
    if "JustificationRule" in message:
        return "Justification rejected by policy"
    if _MFA_RE.search(message):
        return "MFA required"
    if "RoleAssignmentExists" in message or "already exists" in message.lower():
        return "Already active"
    if "AuthorizationFailed" in message:
        return "Not authorized"
    first_line = next((stripped for line in message.splitlines() if (stripped := line.strip())), "")
    if not first_line:
        return "Failed"
    if len(first_line) <= _SHORT_ERROR_LENGTH:
        return first_line
    return first_line[:_SHORT_ERROR_LENGTH] + "…"


class Outcome(enum.Enum):
    """How one role's activation request ended; the members are in summary order."""

    ACTIVATED = "activated"
    SIMULATED = "activated (dry run)"
    PENDING_APPROVAL = "pending approval"
    PENDING = "pending"
    SUBMITTED = "submitted"  # a status fomo doesn't know
    FAILED = "failed"


# The role is active once the request returns (or would be, in a dry run).
SUCCESS_OUTCOMES = frozenset({Outcome.ACTIVATED, Outcome.SIMULATED})

# Status cell mark and style per outcome; any other outcome is shown plain.
_OUTCOME_MARKS: dict[Outcome, tuple[str, str]] = {
    Outcome.ACTIVATED: ("✓", "bold green"),
    Outcome.SIMULATED: ("✓", "bold green"),
    Outcome.PENDING_APPROVAL: ("⏳", "bold yellow"),
    Outcome.PENDING: ("⏳", "bold yellow"),
    Outcome.FAILED: ("✗", "bold red"),
}


def status_outcome(status: str) -> Outcome:
    """Classify the status that ARM or Microsoft Graph returned for a request."""
    if status in ("Provisioned", "Granted"):
        return Outcome.ACTIVATED
    if status == "DryRun":
        return Outcome.SIMULATED
    if "Approval" in status or status == "PendingAdminDecision":
        return Outcome.PENDING_APPROVAL
    if "Pending" in status or status in ("Accepted", "ScheduleCreated"):
        return Outcome.PENDING
    if status in ("Failed", "Denied", "Canceled", "TimedOut"):
        return Outcome.FAILED
    return Outcome.SUBMITTED


def summarize_outcomes(outcomes: Iterable[Outcome]) -> tuple[str, SeverityLevel]:
    """The end-of-run summary, e.g. "2 activated · 1 pending approval · 1 failed".

    The severity is that of the worst outcome: an error if anything failed, a
    warning if anything is still pending, otherwise information.
    """
    counts = Counter(outcomes)
    text = " · ".join(f"{counts[outcome]} {outcome.value}" for outcome in Outcome if counts[outcome])
    if counts[Outcome.FAILED]:
        return text, "error"
    if counts[Outcome.PENDING_APPROVAL] or counts[Outcome.PENDING]:
        return text, "warning"
    return text, "information"


@dataclass(frozen=True)
class ActivationResult(Generic[RoleT]):
    """What an activation screen reports to the screen below when it closes after a run.

    It closes with ``None`` when no run has finished.
    """

    # The roles whose request succeeded (✓): show them as active from now on.
    activated: tuple[RoleT, ...]
    # True for Done (return to the first screen), False for Escape or q (one screen back).
    done: bool


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


class RolesScroll(VerticalScroll):
    """Scrolls the role tables, and is a Tab stop only while there is something to scroll.

    A scroll container takes focus by default, but with every row in view a
    focused one shows nothing and its keys do nothing: Tab seemed to stop
    nowhere.  This one takes focus only while its content overflows, and then
    the arrow keys, Page Up/Down, Home and End scroll it.  While it has focus,
    its tables' frames change colour (app.tcss).
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.can_focus = False

    def on_resize(self, event: Resize) -> None:  # noqa: ARG002
        self._update_can_focus()

    def watch_virtual_size(self) -> None:
        # The content's height changed (rows added, a table shown), which
        # sends no Resize.  Check once the layout is complete.
        self.call_after_refresh(self._update_can_focus)

    def _update_can_focus(self) -> None:
        overflows = self.max_scroll_y > 0
        if overflows == self.can_focus:
            return
        if self.has_focus:
            # Everything fits now: hand focus on while this is still in the chain.
            self.screen.focus_next()
        self.can_focus = overflows


class ActivationScreenBase(FomoScreen[ActivationResult[RoleT] | None], Generic[RoleT]):
    """Justification form plus per-role activation progress."""

    # Enter, r, i and q (Quit) only apply once a run has finished, and the two
    # q bindings take turns: check_action enables the ones that apply.  The
    # letters and Escape are not priority bindings: a focused Input types the
    # letters, and an open Duration menu closes on Escape before the screen
    # sees it.  Enter is, so that the footer shows "Done" rather than the
    # focused Done button's own (hidden) Enter; check_action leaves Enter to
    # the reason field, the Duration menu and the Retry button.
    BINDINGS = [
        Binding("enter", "done", "Done", show=True, priority=True),
        Binding("r", "retry_failed", "Retry failed", show=True),
        Binding("i", "assignments", "Assignments", show=True),
        Binding("q", "quit_app", "Quit", show=True),
        Binding("q", "back_before_run", "Back", show=False),
        Binding("escape", "back", "Back", show=True),
    ]
    _AFTER_RUN_ACTIONS: ClassVar[frozenset[str]] = frozenset({"done", "retry_failed", "assignments", "quit_app"})

    # Below _TALL_HEIGHT rows the screen has the "-short" class, and app.tcss
    # tightens the layout so that the form, a few table rows, the details
    # panel and the buttons still fit (80x24 included).
    VERTICAL_BREAKPOINTS = [(0, "-short"), (_TALL_HEIGHT, "-tall")]

    # Labels of the columns before Status.
    COLUMNS: ClassVar[tuple[str, ...]]
    # Logger and message used when an activation fails.
    _log: ClassVar[logging.Logger]
    _FAILURE_LOG_MESSAGE: ClassVar[str]

    def __init__(self, roles: list[RoleT], *, justification: str = "", duration: str = DEFAULT_DURATION) -> None:
        """*justification* and *duration* prefill the form (a recent activation)."""
        super().__init__()
        self.roles: list[RoleT] = roles
        self._initial_justification = justification
        self._initial_duration = duration if duration in {value for _, value in _DURATION_OPTIONS} else DEFAULT_DURATION
        # The reason, duration and running row indices of the latest run.
        self._run: tuple[str, str, list[int]] | None = None
        self._activating = False
        self._finished = False  # a run has finished; later runs only retry failed rows
        self._errors: dict[int, str] = {}  # running row index → full error message
        self._outcomes: dict[int, Outcome] = {}  # running row index → outcome of its last attempt

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

    def _recent_entry(self, roles: Sequence[RoleT], justification: str, duration: str) -> state.Recent | None:
        """The recent activation to remember for *roles*, or ``None`` to remember nothing."""
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
                yield Input(
                    self._initial_justification,
                    placeholder="Justification (required, for all roles)",
                    id="justification",
                )
                yield Label("Duration", id="duration-label", classes="form-label")
                # No blank row: a blank Select's value is Select.NULL, which is
                # truthy and would reach activate_role as the duration.
                yield Select(_DURATION_OPTIONS, value=self._initial_duration, allow_blank=False, id="duration")
            with RolesScroll(id="roles-scroll"):
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
            # Bottom right, the primary button rightmost (see focus_chain for Tab).
            with Horizontal(id="buttons"):
                yield Button("Back", id="btn-back")
                yield Button("Activate", variant="primary", id="btn-activate")
        yield Footer()

    @property
    def focus_chain(self) -> list[Widget]:
        """Tab order: reason, duration, the role list (when it scrolls), Activate, Back.

        Textual orders Tab stops by position, and Back is drawn to the left of
        Activate; Tab still reaches the primary button first.
        """
        chain = super().focus_chain
        ids = [widget.id for widget in chain]
        if "btn-back" in ids and "btn-activate" in ids:
            back, activate = ids.index("btn-back"), ids.index("btn-activate")
            if back < activate:
                chain[back], chain[activate] = chain[activate], chain[back]
        return chain

    def on_mount(self) -> None:
        # Textual sets the VERTICAL_BREAKPOINTS class on the screen's first
        # Resize, after the first layout: set it now, so that a short
        # terminal doesn't see the tall layout for a frame.
        tall = self.app.size.height >= _TALL_HEIGHT
        self.set_class(tall, "-tall")
        self.set_class(not tall, "-short")
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
        # The button reads "Done" once a run has finished.
        if self._finished:
            self.action_done()
        else:
            self.action_back()

    @on(Button.Pressed, "#btn-activate")
    def on_activate_pressed(self) -> None:
        self._start_activation()

    def _rows(self) -> list[tuple[int, str, int, RoleT]]:
        """``(index, table_id, row, role)`` for every role, in activation order.

        *index* runs on across the tables; it keys ``_errors`` and ``_outcomes``.
        """
        rows: list[tuple[int, str, int, RoleT]] = []
        for table_id, roles in self._role_tables():
            for row, role in enumerate(roles):
                rows.append((len(rows), table_id, row, role))
        return rows

    def _failed_rows(self) -> list[int]:
        """Running indices of the rows whose last attempt failed."""
        return sorted(index for index, outcome in self._outcomes.items() if outcome is Outcome.FAILED)

    def _start_activation(self) -> None:
        """Activate every role or, after a run, retry the failed ones.

        Does nothing while a run is going on, or once nothing is left to retry
        (the Activate button is disabled then).  A retry uses the reason and
        duration as they are now.
        """
        btn_activate = self.query_one("#btn-activate", Button)
        if self._activating or btn_activate.disabled:
            return
        justification = self.query_one("#justification", Input).value.strip()
        if not justification:
            self.notify("Justification is required.", severity="warning")
            self.query_one("#justification").focus()
            return
        selected = self.query_one("#duration", Select).value
        duration = selected if isinstance(selected, str) and selected else DEFAULT_DURATION
        rows = self._rows()
        if self._finished:
            retry = set(self._failed_rows())
            rows = [entry for entry in rows if entry[0] in retry]
            # The Details panel only shows the errors of the latest attempt.
            self._errors.clear()
            error_log = self.query_one("#error-log", RichLog)
            error_log.clear()
            error_log.add_class("hidden")
        self._run = (justification, duration, [entry[0] for entry in rows])
        self._activating = True
        btn_activate.disabled = True
        self.query_one("#btn-back", Button).disabled = True
        self.refresh_bindings()
        self._run_activation(rows, justification, duration)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "back_before_run":
            return not self._finished
        if action in self._AFTER_RUN_ACTIONS:
            if not self._finished or self._activating:
                return False
            if action == "done":
                # Enter is Done on the Done button or with nothing focused;
                # elsewhere it submits the reason, opens the menu or retries.
                focused = self.focused
                return focused is None or focused.id == "btn-back"
            if action == "retry_failed":
                return bool(self._failed_rows())
        return super().check_action(action, parameters)

    def action_back(self) -> None:
        """Escape and the Back button, and q before a run.

        In a focused Input that has text, only leave the field and keep the
        text; the next Escape goes back.  Otherwise go back, unless an
        activation is running.  After a run, the screen below marks the
        activated roles active and clears its selection.
        """
        focused = self.focused
        if isinstance(focused, Input) and focused.value:
            self.set_focus(None)
            return
        if not self._activating:
            self.dismiss(self._result(done=False))

    def action_back_before_run(self) -> None:
        """q before a run finishes: the same as Escape (afterwards q quits)."""
        self.action_back()

    def action_done(self) -> None:
        """Enter or the Done button after a run: return to the first screen."""
        if self._finished and not self._activating:
            self.dismiss(self._result(done=True))

    def action_retry_failed(self) -> None:
        """r after a run: activate the roles that failed again."""
        self._start_activation()

    def action_assignments(self) -> None:
        """i after a run: show the active assignments, freshly loaded."""
        from fomo.screens.assignments_screen import AssignmentsScreen

        self.app.push_screen(AssignmentsScreen())

    def action_quit_app(self) -> None:
        """q after a run."""
        self.app.exit()

    def _result(self, done: bool) -> ActivationResult[RoleT] | None:
        """The result to dismiss with: ``None`` unless a run has finished."""
        if not self._finished:
            return None
        activated = tuple(role for index, _, _, role in self._rows() if self._outcomes.get(index) in SUCCESS_OUTCOMES)
        return ActivationResult(activated, done)

    # ------------------------------------------------------------------
    # Background activation worker
    # ------------------------------------------------------------------

    @work(thread=True)
    def _run_activation(self, rows: list[tuple[int, str, int, RoleT]], justification: str, duration: str) -> None:
        for index, table_id, row, role in rows:
            self._activate_row(table_id, row, index, role, justification, duration)
        self.app.call_from_thread(self._on_activation_done)

    def _activate_row(
        self,
        table_id: str,
        row: int,
        index: int,
        role: RoleT,
        justification: str,
        duration: str,
    ) -> None:
        """Activate *role* and show progress in its table row (worker thread)."""
        self.app.call_from_thread(self._set_status, table_id, row, Text("Activating…"))
        label: Text
        outcome: Outcome
        try:
            status = self._activate(role, justification, duration)
            outcome = status_outcome(status)
            label = self._format_status(status)
        except Exception as exc:
            full_error = str(exc)
            self._log.error(self._FAILURE_LOG_MESSAGE, role.role_name, full_error)
            self._errors[index] = full_error
            outcome = Outcome.FAILED
            label = Text(f"✗ {summarize_activation_error(full_error)}", style="bold red")
            self.app.call_from_thread(self._append_error, role.role_name, full_error)
        self._outcomes[index] = outcome
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
        self._finished = True
        failed = len(self._failed_rows())
        btn_activate = self.query_one("#btn-activate", Button)
        btn_activate.label = f"Retry failed ({failed})" if failed else "Activate"
        btn_activate.disabled = not failed
        btn_back = self.query_one("#btn-back", Button)
        btn_back.disabled = False
        btn_back.label = "Done"
        btn_back.focus()
        self.refresh_bindings()
        self._remember_run()
        # The outcome of every row, retried or not, e.g. "2 activated · 1 failed".
        summary, severity = summarize_outcomes(self._outcomes.values())
        if failed:
            summary += " — see Details below."
        self.notify(summary, severity=severity, timeout=8 if severity == "error" else None, markup=False)

    def _remember_run(self) -> None:
        """Remember the roles as a recent activation if any of the latest run's requests went through.

        All of the screen's roles are remembered, with the reason and
        duration of the latest run, so that a retry updates the same entry.
        """
        if self._run is None:
            return
        justification, duration, indices = self._run
        if all(self._outcomes.get(index) is Outcome.FAILED for index in indices):
            return
        entry = self._recent_entry([role for _, _, _, role in self._rows()], justification, duration)
        if entry is not None:
            self.app.recents.add(entry)  # type: ignore[attr-defined]

    @staticmethod
    def _format_status(status: str) -> Text:
        """Status cell for a submitted request: green ✓, yellow ⏳ (e.g. PendingApproval) or red ✗.

        A failed request (an exception) gets a red ✗ and the summary from
        :func:`summarize_activation_error` instead.
        """
        mark = _OUTCOME_MARKS.get(status_outcome(status))
        if mark is None:
            return Text(status)
        symbol, style = mark
        return Text(f"{symbol} {status}", style=style)
