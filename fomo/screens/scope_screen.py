"""Scope screen — pick which Azure subscriptions to load PIM roles from.

Its Entra tab lists the eligible Entra roles, and its Recent tab, shown once
there is something on it, the recent activations: keys 1-5 start one again.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.css.query import NoMatches
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    LoadingIndicator,
    OptionList,
    TabbedContent,
    TabPane,
    Tabs,
)
from textual.widgets.selection_list import Selection

from fomo import azure, state, tiering, timefmt
from fomo.screens._common import (
    MOVE,
    TABS,
    VIM_BINDINGS,
    FomoScreen,
    VimNavMixin,
    device_code_markup,
    role_detail_state,
    role_list_prompt,
    safe_markup,
    wrap_error_lines,
)
from fomo.widgets import FomoSelectionList as SelectionList

if TYPE_CHECKING:
    from fomo.screens._activation_base import ActivationResult

MAX_SUBSCRIPTIONS = 3
ENTRA_SORT_MODES = ("name", "tier", "expiry")
# Keys 1-5 start a recent activation; the Keys screen (?) lists them on one row.
RECENT = Binding.Group("Activate recent")
# A recent activation's justification is cut to this many characters in its row.
_RECENT_REASON_WIDTH = 30
# The filter, selection and sort keys of the other tabs do nothing on the Recent tab.
_NOT_ON_RECENT_TAB = frozenset(
    {"focus_filter", "escape_key", "select_all", "select_none", "cycle_sort", "select_focused"}
)


def recent_prompt(number: int, recent: state.Recent) -> Content:
    """An entry of the Recent tab: its number and roles, then its duration and reason, dimmed.

    E.g.::

        1  Key Vault Administrator · Contoso Production
           1h · "INC-4711 prod hotfix"

    Each role is on a line of its own, and the reason is cut to 30
    characters, so that an entry doesn't wrap in an 80-column terminal.
    """
    reason = recent.justification
    if len(reason) > _RECENT_REASON_WIDTH:
        reason = reason[: _RECENT_REASON_WIDTH - 1].rstrip() + "…"
    indent = " " * (len(str(number)) + 2)
    lines = [safe_markup("[bold]$number[/bold]  $label", number=number, label=recent.label(0))]
    lines.extend(Content(indent + recent.label(i)) for i in range(1, len(recent.targets)))
    lines.append(
        safe_markup(
            f'{indent}[dim]$duration · "$reason"[/dim]',
            duration=timefmt.format_duration(recent.duration),
            reason=reason,
        )
    )
    return Content("\n").join(lines)


def _recent_pane() -> TabPane:
    """The Recent tab: the recent activations, filled in by ``ScopeScreen._show_recents``."""
    return TabPane(
        "Recent",
        Vertical(
            Label("Recent activations", id="recent-title"),
            OptionList(id="recent-list"),
            Label("", id="recent-hint"),
            id="recent-pane",
        ),
        id="tab-recent",
    )


class ScopeScreen(VimNavMixin, FomoScreen):
    """First screen: select Azure subscriptions or Entra roles, or start a recent activation."""

    BINDINGS = [
        # Priority bindings: Enter in a filter input never reaches Input.Submitted.
        # check_action enables exactly one of the two, so the footer shows what
        # Enter does: move from the filter to its list, or proceed.
        Binding("enter", "to_list", "To list", show=True, priority=True),
        Binding("enter", "proceed", "Proceed", show=True, priority=True),
        Binding("slash", "focus_filter", "Filter", show=True),
        Binding("escape", "escape_key", "Filter ↔ list", show=False, priority=True),
        Binding("a", "select_all", "All", show=True),
        Binding("n", "select_none", "None", show=True),
        Binding("ctrl+s", "cycle_sort", "Sort", show=True, priority=True),
        Binding("i", "open_assignments", "Assignments", show=True),
        Binding("q", "quit_app", "Quit", show=True),
        # Hidden from the footer; the Keys screen (?) lists them.
        Binding("x", "select_focused", "Toggle", show=False, priority=True),
        Binding("h", "prev_tab", "Previous tab", show=False, group=TABS),
        Binding("l", "next_tab", "Next tab", show=False, group=TABS),
        Binding("up", "arrow_up", "Up", show=False, group=MOVE),
        Binding("down", "arrow_down", "Down", show=False, group=MOVE),
        *VIM_BINDINGS,
        # Not while typing: a focused filter takes the digits.
        *(
            Binding(str(n), f"start_recent({n - 1})", f"Recent {n}", show=False, group=RECENT)
            for n in range(1, state.MAX_RECENT + 1)
        ),
    ]

    def __init__(self, initial_tab: str = "tab-azure") -> None:
        super().__init__()
        self._initial_tab = initial_tab
        # Azure tab state
        self._all_subs: list[azure.Subscription] = []
        self._visible_ids: set[str] = set()
        self._selected_ids: set[str] = set()
        self._rebuilding = False
        self._subs_desc = False
        self._subs_loading = False
        # Entra tab state
        self._entra_loaded = False
        self._entra_loading = False
        self._focus_entra_on_load = False  # set by h/l while the roles are loading
        self._stop_event = threading.Event()
        self.all_roles: list[azure.EntraEligibleRole] = []
        self._selected: set[int] = set()
        self._visible_indices: set[int] = set()
        self._option_values: list[int] = []
        self._entra_rebuilding = False
        self._entra_sort_mode = ENTRA_SORT_MODES[0]
        # A recent Entra activation to start once the Entra roles have loaded.
        self._entra_recent: state.Recent | None = None
        # The Entra activation screen's justification and duration, from a recent activation.
        self._entra_prefill: dict[str, str] = {}
        # Recent tab: the entries it shows (None until first shown).
        self._recents: list[state.Recent] | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with TabbedContent(id="scope-tabs", initial=self._initial_tab):
            with TabPane("Azure", id="tab-azure"):
                with Vertical(id="main"):
                    yield Label("Loading Azure subscriptions…", id="loading-label")
                    yield LoadingIndicator(id="spinner")
                    yield Input(placeholder="Filter subscriptions… (type to search)", id="filter")
                    yield SelectionList(id="sub-list")
                    yield Label("", id="sel-count")
            with TabPane("Entra", id="tab-entra"):
                with Vertical(id="entra-loading-area"):
                    yield Label("Switch to this tab to load Entra roles…", id="entra-loading-label")
                    yield LoadingIndicator(id="entra-spinner")
                with Horizontal(id="entra-split"):
                    with Vertical(id="entra-left-pane"):
                        yield Input(placeholder="Filter roles… (type to search)", id="entra-filter")
                        yield SelectionList(id="entra-role-list")
                        yield Label("", id="entra-status")
                    with Vertical(id="entra-detail-pane"):
                        yield Label(
                            "[dim]Navigate the list to see role details.[/dim]",
                            id="entra-detail",
                        )
            # Only once there are recent activations (see on_screen_resume).
            if self.app.recents.entries():  # type: ignore[attr-defined]
                yield _recent_pane()
        yield Label("[bold]←/→[/bold] switch tab  •  [bold]Tab[/bold] enter list", id="tab-hint")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#sub-list").display = False
        self.query_one("#filter").display = False
        self.query_one("#sel-count").display = False
        self.query_one("#entra-split").display = False
        self.query_one("#entra-spinner").display = False
        self._show_recents()
        self._load_subs()
        if self._initial_tab == "tab-entra":
            self._start_entra_load()
        self.call_after_refresh(self.query_one("#scope-tabs").focus)

    async def on_screen_resume(self) -> None:
        # Back from an activation, which may have added a recent activation,
        # or the first one: then the Recent tab appears.
        if not self.is_mounted:
            return
        if self.app.recents.entries() and not self.query("#recent-list"):  # type: ignore[attr-defined]
            await self.query_one("#scope-tabs", TabbedContent).add_pane(_recent_pane())
        self._show_recents()

    def on_unmount(self) -> None:
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Tab navigation
    # ------------------------------------------------------------------

    def _active_tab(self) -> str:
        return self.query_one("#scope-tabs", TabbedContent).active or "tab-azure"

    def _on_recent_tab(self) -> bool:
        try:
            return self._active_tab() == "tab-recent"
        except NoMatches:  # not composed yet
            return False

    def _tab_ids(self) -> list[str]:
        """The tabs that are shown, in order."""
        return ["tab-azure", "tab-entra", *(["tab-recent"] if self._recents else [])]

    def action_next_tab(self) -> None:
        self._step_tab(1)

    def action_prev_tab(self) -> None:
        self._step_tab(-1)

    def _step_tab(self, step: int) -> None:
        tabs = self._tab_ids()
        current = self._active_tab()
        position = tabs.index(current) if current in tabs else 0
        self._switch_tab(tabs[(position + step) % len(tabs)])

    def _switch_tab(self, target: str) -> None:
        """Activate *target* and move focus to its list (``h``/``l``)."""
        tc = self.query_one("#scope-tabs", TabbedContent)
        # Take focus off the old pane first, synchronously.  Otherwise hiding the
        # pane hands focus to the old pane's filter, and TabbedContent switches
        # straight back to the pane that now holds focus.
        self.set_focus(tc.query_one(Tabs))
        tc.active = target
        self.call_after_refresh(self._focus_pane_list, target)

    def _focus_pane_list(self, target: str) -> None:
        """Focus the list on *target* if it has loaded; else keep the tab bar."""
        if not self.is_attached or self._active_tab() != target or not isinstance(self.focused, Tabs):
            return
        if target == "tab-recent":
            self.query_one("#recent-list").focus()
        elif target == "tab-entra":
            if not self._entra_loaded:
                # The roles are (about to start) loading: focus the list when they arrive.
                self._focus_entra_on_load = True
            elif self.all_roles:
                self.query_one("#entra-role-list").focus()
        elif self._all_subs:
            self.query_one("#sub-list").focus()

    @on(TabbedContent.TabActivated, "#scope-tabs")
    def on_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.pane.id == "tab-entra" and not self._entra_loaded and not self._entra_loading:
            self._start_entra_load()
        # The footer: the Recent tab has no filter, selection or sort.
        self.refresh_bindings()

    def watch_focused(self, focused) -> None:
        try:
            self.query_one("#tab-hint").display = isinstance(focused, Tabs)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Azure — subscription loading
    # ------------------------------------------------------------------

    @property
    def has_subscriptions(self) -> bool:
        """True once the subscription list has loaded with at least one entry."""
        return bool(self._all_subs)

    def reload_subscriptions(self) -> None:
        """Fetch the subscription list again (Retry after re-login).

        Does nothing while a load is already running.
        """
        if self._subs_loading or not self.is_attached:
            return
        self.query_one("#spinner").display = True
        self.query_one("#loading-label", Label).update("Loading Azure subscriptions…")
        self._load_subs()

    def _load_subs(self) -> None:
        self._subs_loading = True
        self._fetch_subs()

    @work(thread=True)
    def _fetch_subs(self) -> None:
        try:
            subs = self.app.backend.list_subscriptions()  # type: ignore[attr-defined]
            self.app.call_from_thread(self._show_subs, subs)
        except Exception as exc:
            self.app.call_from_thread(self._show_error, str(exc))

    def _show_subs(self, subs: list[azure.Subscription]) -> None:
        self._subs_loading = False
        self.query_one("#spinner").display = False
        self.query_one("#loading-label", Label).update(f"Select subscriptions  ({len(subs)} found)")
        self._all_subs = subs
        self.query_one("#filter").display = True
        self._rebuild_list("")
        sl = self.query_one("#sub-list", SelectionList)
        sl.display = True
        self.query_one("#sel-count").display = True
        self._update_sel_count()
        self.query_one("#scope-tabs").focus()

    def _show_error(self, msg: str) -> None:
        self._subs_loading = False
        self.query_one("#spinner").display = False
        body: str | Content
        if azure.is_auth_error(msg):
            body = (
                "[bold red]Azure session expired.[/bold red]\n\n"
                "Run [bold]az login[/bold] in your terminal, then restart fomo."
            )
            self.app.show_auth_error(  # type: ignore[attr-defined]
                azure.classify_auth_error(msg), msg, self.reload_subscriptions
            )
        else:
            body = safe_markup(
                "[bold red]Error:[/bold red] $msg\n\n"
                "Is [bold]az[/bold] installed and are you logged in?  Run: [bold]az login[/bold]",
                msg=msg,
            )
        self.query_one("#loading-label", Label).update(body)

    # ------------------------------------------------------------------
    # Azure — filter helpers
    # ------------------------------------------------------------------

    def _rebuild_list(self, query: str) -> None:
        sl = self.query_one("#sub-list", SelectionList)
        self._rebuilding = True
        sl.clear_options()
        self._visible_ids = set()
        q = query.strip().lower()
        ordered = sorted(self._all_subs, key=lambda s: s.name.casefold(), reverse=self._subs_desc)
        for sub in ordered:
            if q and q not in f"{sub.name} {sub.id}".lower():
                continue
            display = safe_markup("$name  [dim]$id[/dim]", name=sub.name, id=sub.id)
            sl.add_option((display, sub.id, sub.id in self._selected_ids))
            self._visible_ids.add(sub.id)
        self._rebuilding = False

    @on(SelectionList.SelectedChanged, "#sub-list")
    def on_sub_selection_changed(self, event: SelectionList.SelectedChanged) -> None:
        if self._rebuilding:
            return
        visible_selected: set[str] = set(event.selection_list.selected)
        visible_unselected = self._visible_ids - visible_selected
        self._selected_ids |= visible_selected
        self._selected_ids -= visible_unselected
        self._update_sel_count()

    def _update_sel_count(self) -> None:
        n = len(self._selected_ids)
        label = self.query_one("#sel-count", Label)
        sort_tag = f"  ·  [dim]sort: {'Z→A' if self._subs_desc else 'A→Z'}[/dim]"
        if n == 0:
            label.update(f"[dim]No subscriptions selected[/dim]{sort_tag}")
        elif n > MAX_SUBSCRIPTIONS:
            label.update(
                f"[bold]{n} subscriptions selected[/bold]  "
                f"[bold red](warning: >{MAX_SUBSCRIPTIONS})[/bold red]{sort_tag}"
            )
        else:
            label.update(f"[bold]{n}[/bold] subscription(s) selected{sort_tag}")

    @on(Input.Changed, "#filter")
    def on_filter_changed(self, event: Input.Changed) -> None:
        self._rebuild_list(event.value)

    # ------------------------------------------------------------------
    # Entra — role loading
    # ------------------------------------------------------------------

    def _start_entra_load(self) -> None:
        self._entra_loading = True
        self.query_one("#entra-spinner").display = True
        self.query_one("#entra-loading-label", Label).update("Loading Entra eligible roles…")
        self._load_entra_tiering()
        self._load_entra_roles()

    @work(thread=True)
    def _load_entra_tiering(self) -> None:
        # Separate from the role fetch: tier data is optional, and loading it
        # never raises, so it can neither delay nor fail the role list.
        tiering.ensure_entra_loaded(allow_network=self.app.backend.allow_network)  # type: ignore[attr-defined]
        self.app.call_from_thread(self._on_entra_tiering_loaded)

    def _on_entra_tiering_loaded(self) -> None:
        """Re-render the detail pane if the list appeared before the tier data."""
        if self.is_attached and self.query_one("#entra-split").display:
            self._refresh_entra_detail()

    @work(thread=True)
    def _load_entra_roles(self) -> None:
        def _on_device_code(message: str) -> None:
            url, _, code = message.partition("\n")

            def _update() -> None:
                self.query_one("#entra-loading-label", Label).update(device_code_markup(url, code))

            self.app.call_from_thread(_update)

        try:
            roles = self.app.backend.list_entra_eligible_roles(  # type: ignore[attr-defined]
                on_device_code=_on_device_code,
                stop_event=self._stop_event,
            )
        except Exception as exc:
            self.app.call_from_thread(self._on_entra_error, str(exc))
            return
        # Outside the try: a failure in the UI callback is not a fetch error.
        self.app.call_from_thread(self._on_entra_roles_loaded, roles)

    def _on_entra_roles_loaded(self, roles: list[azure.EntraEligibleRole]) -> None:
        self._entra_loaded = True
        self._entra_loading = False
        focus_pending, self._focus_entra_on_load = self._focus_entra_on_load, False
        self.all_roles = roles
        self.query_one("#entra-spinner").display = False
        if not roles:
            self.query_one("#entra-loading-label", Label).update("[dim]No eligible Entra roles found.[/dim]")
            self._start_pending_entra_recent()
            return
        self.query_one("#entra-loading-area").display = False
        self.query_one("#entra-split").display = True
        self._rebuild_entra_list("")
        # Started on this tab (--entra), or got here with h/l and still waiting
        # on the tab bar.
        if self._initial_tab == "tab-entra" or (
            focus_pending and self._active_tab() == "tab-entra" and isinstance(self.focused, Tabs)
        ):
            self.query_one("#entra-role-list").focus()
        self._update_entra_status()
        self._start_pending_entra_recent()

    def _on_entra_error(self, msg: str) -> None:
        self._entra_loading = False
        self._focus_entra_on_load = False
        self._entra_recent = None
        self.query_one("#entra-spinner").display = False
        body: str | Content
        if azure.is_auth_error(msg):
            body = (
                "[bold red]Azure session expired.[/bold red]\n\n"
                "Run [bold]az login[/bold] in your terminal, then restart fomo."
            )
        else:
            body = safe_markup("[bold red]Error:[/bold red]\n\n$error", error=wrap_error_lines(msg))
        self.query_one("#entra-loading-label", Label).update(body)

    # ------------------------------------------------------------------
    # Entra — filter helpers
    # ------------------------------------------------------------------

    def _entra_sort_key(self, role: azure.EntraEligibleRole) -> tuple:
        name = role.role_name.casefold()
        if self._entra_sort_mode == "tier":
            info = tiering.get_entra_tier(role.role_definition_id)
            return (info["tier"] if info else 99, name)
        if self._entra_sort_mode == "expiry":
            return (role.expiry is None, role.expiry or "", name)
        return (name,)

    def _rebuild_entra_list(self, query: str) -> None:
        sl = self.query_one("#entra-role-list", SelectionList)
        q = query.strip().lower()
        self._entra_rebuilding = True
        sl.clear_options()
        self._visible_indices = set()
        self._option_values = []
        ordered = sorted(enumerate(self.all_roles), key=lambda item: self._entra_sort_key(item[1]))
        now = timefmt.now()
        for idx, role in ordered:
            if q and q not in role.role_name.lower():
                continue
            _, label = role_list_prompt(role.role_name, role, now)
            sl.add_option(Selection(label, idx, idx in self._selected))
            self._visible_indices.add(idx)
            self._option_values.append(idx)
        self._entra_rebuilding = False
        if self._option_values:
            self._update_entra_detail(self.all_roles[self._option_values[0]])
        else:
            self.query_one("#entra-detail", Label).update("[dim]No roles match filter.[/dim]")

    @on(Input.Changed, "#entra-filter")
    def on_entra_filter_changed(self, event: Input.Changed) -> None:
        self._rebuild_entra_list(event.value)

    @on(SelectionList.SelectedChanged, "#entra-role-list")
    def on_entra_selection_changed(self, event: SelectionList.SelectedChanged) -> None:
        if self._entra_rebuilding:
            return
        visible_selected: set[int] = set(event.selection_list.selected)
        visible_unselected = self._visible_indices - visible_selected
        self._selected |= visible_selected
        self._selected -= visible_unselected
        self._update_entra_status()

    @on(SelectionList.SelectionHighlighted, "#entra-role-list")
    def on_entra_option_highlighted(self, event: SelectionList.SelectionHighlighted) -> None:
        idx = event.selection_index
        if idx < 0 or idx >= len(self._option_values):
            return
        role_idx = self._option_values[idx]
        if role_idx is None or role_idx < 0 or role_idx >= len(self.all_roles):
            return
        self._update_entra_detail(self.all_roles[role_idx])

    def _update_entra_status(self) -> None:
        n = len(self._selected)
        lbl = self.query_one("#entra-status", Label)
        sort_tag = f"  ·  [dim]sort: {self._entra_sort_mode}[/dim]"
        if n == 0:
            lbl.update(f"[dim]No roles selected[/dim]{sort_tag}")
        else:
            lbl.update(f"[bold]{n}[/bold] role(s) selected{sort_tag}")

    def _refresh_entra_detail(self) -> None:
        """Re-render the detail pane for the highlighted (or first listed) role."""
        idx = self.query_one("#entra-role-list", SelectionList).highlighted
        if idx is None or not 0 <= idx < len(self._option_values):
            idx = 0
        if self._option_values:
            self._update_entra_detail(self.all_roles[self._option_values[idx]])

    def _update_entra_detail(self, role: azure.EntraEligibleRole) -> None:
        detail_lbl = self.query_one("#entra-detail", Label)
        tier_info = tiering.get_entra_tier(role.role_definition_id)
        active, eligible = role_detail_state(role, timefmt.now())
        active_tag = "\n[bold $success]● $active[/]" if active else ""

        if not tier_info:
            detail_lbl.update(
                safe_markup(
                    f"[bold]$name[/bold]{active_tag}\n$eligible\n\n[dim]No tiering data available for this role.[/dim]",
                    name=role.role_name,
                    active=active,
                    eligible=eligible,
                )
            )
            return

        tier = tier_info["tier"]
        badge = tiering.tier_badge(tier)
        tlabel = tiering.tier_label(tier)
        attack = (tier_info.get("attack_path") or "").strip()
        col = tiering.TIER_COLOUR.get(tier, "white")
        path_headers = {0: "Attack path", 1: "Provides access to", 2: "Notes", 3: "Notes"}
        path_header = path_headers.get(tier, "Notes")

        parts: list[str] = [
            f"{badge} [bold {col}]Tier {tier}[/bold {col}]  [dim]{tlabel}[/dim]",
            "",
            f"[bold]$name[/bold]{active_tag}",
            "$eligible",
        ]
        if attack and attack != "-":
            parts.extend(["", f"[bold]{path_header}:[/bold]", "$attack"])
        detail_lbl.update(
            safe_markup("\n".join(parts), name=role.role_name, active=active, eligible=eligible, attack=attack)
        )

    def _select_all_entra_visible(self) -> None:
        self._selected.update(self._visible_indices)
        sl = self.query_one("#entra-role-list", SelectionList)
        self._entra_rebuilding = True
        sl.select_all()
        self._entra_rebuilding = False
        self._update_entra_status()

    # ------------------------------------------------------------------
    # Recent activations (Recent tab, keys 1-5)
    # ------------------------------------------------------------------

    def _show_recents(self) -> None:
        """List the recent activations on the Recent tab, if it is there and they have changed."""
        recents = self.app.recents.entries()  # type: ignore[attr-defined]
        if recents == self._recents or not self.query("#recent-list"):
            return
        self._recents = recents
        recent_list = self.query_one("#recent-list", OptionList)
        recent_list.set_options(recent_prompt(number, recent) for number, recent in enumerate(recents, 1))
        recent_list.highlighted = 0
        keys = "[bold]1[/bold]" if len(recents) == 1 else f"[bold]1[/bold]–[bold]{len(recents)}[/bold]"
        self.query_one("#recent-hint", Label).update(
            f"Press {keys} (also on the other tabs) or [bold]⏎[/bold] to activate the same roles again.  "
            "The reason and duration are filled in, and you can change them first."
        )
        self.refresh_bindings()

    @on(OptionList.OptionSelected, "#recent-list")
    def on_recent_selected(self, event: OptionList.OptionSelected) -> None:
        """A click on a recent activation (Enter is the proceed binding)."""
        self.action_start_recent(event.option_index)

    def action_start_recent(self, index: int) -> None:
        """1-5: start recent activation *index* (from 0), with its reason and duration.

        Azure: open the roles screen for its subscriptions, which selects the
        roles and, if they can all be activated, goes on to the activation
        screen.  Entra: the same on the Entra tab, once its roles have loaded.
        """
        recents = self._recents or []
        if not 0 <= index < len(recents):
            self.notify(f"There is no recent activation {index + 1}.", severity="warning")
            return
        recent = recents[index]
        if recent.kind == "entra":
            self._start_entra_recent(recent)
            return
        from fomo.screens.roles_screen import RolesScreen

        names = {sub.id: sub.name for sub in self._all_subs}
        self.app.push_screen(RolesScreen(list(recent.subscriptions), names, recent=recent))

    def _start_entra_recent(self, recent: state.Recent) -> None:
        self._entra_recent = recent
        if self._active_tab() != "tab-entra":
            self._switch_tab("tab-entra")  # loads the roles the first time
        elif not self._entra_loaded and not self._entra_loading:
            self._start_entra_load()  # the last load failed
        if self._entra_loaded:
            self._start_pending_entra_recent()

    def _start_pending_entra_recent(self) -> None:
        """Select the roles of the recent Entra activation waiting for the roles, if any.

        If they can all be activated, open the activation screen; otherwise a
        toast names the others.
        """
        recent, self._entra_recent = self._entra_recent, None
        if recent is None:
            return
        self._entra_prefill = {"justification": recent.justification, "duration": recent.duration}
        match = state.match_targets(recent, self.all_roles, state.entra_target)
        if self.all_roles:
            self._selected = set(match.ready)
            self._rebuild_entra_list(self.query_one("#entra-filter", Input).value)
            self._update_entra_status()
        # Not when another screen (a dialog) has come up meanwhile.
        if match.complete and self.app.screen is self:
            self._open_entra_activation([self.all_roles[i] for i in sorted(match.ready)])
            return
        if self.all_roles:
            self.query_one("#entra-role-list").focus()
        if not match.complete:
            self.notify(match.problems(), title="Recent activation", severity="warning", timeout=10, markup=False)

    # ------------------------------------------------------------------
    # Actions — tab-aware
    # ------------------------------------------------------------------

    def _filter_has_focus(self) -> bool:
        focused = self.focused
        return isinstance(focused, Input) and focused.id in ("filter", "entra-filter")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # Enter is "to_list" while a filter has focus and "proceed" otherwise.
        if action == "to_list":
            return self._filter_has_focus()
        if action == "proceed":
            return not self._filter_has_focus()
        if action == "start_recent":
            return bool(self._recents)
        if action in _NOT_ON_RECENT_TAB and self._on_recent_tab():
            return False
        return super().check_action(action, parameters)

    def action_to_list(self) -> None:
        """Enter in a filter: move focus to the list below it."""
        self.action_focus_list()

    def action_focus_filter(self) -> None:
        if self._active_tab() == "tab-entra":
            self.query_one("#entra-filter").focus()
        else:
            self.query_one("#filter").focus()

    def action_focus_list(self) -> None:
        if self._active_tab() == "tab-recent":
            self.query_one("#recent-list").focus()
        elif self._active_tab() == "tab-entra":
            self.query_one("#entra-role-list").focus()
        else:
            self.query_one("#sub-list").focus()

    def action_escape_key(self) -> None:
        if self._active_tab() == "tab-entra":
            filt = self.query_one("#entra-filter")
            lst = self.query_one("#entra-role-list")
        else:
            filt = self.query_one("#filter")
            lst = self.query_one("#sub-list")
        if self.focused is filt:
            lst.focus()
        else:
            filt.focus()

    def action_select_all(self) -> None:
        if self._active_tab() == "tab-entra":
            self._select_all_entra_visible()
        else:
            self.query_one("#sub-list", SelectionList).select_all()

    def action_select_none(self) -> None:
        if self._active_tab() == "tab-entra":
            self._selected.clear()
            sl = self.query_one("#entra-role-list", SelectionList)
            self._entra_rebuilding = True
            sl.deselect_all()
            self._entra_rebuilding = False
            self._update_entra_status()
        else:
            self._selected_ids.clear()
            self.query_one("#sub-list", SelectionList).deselect_all()

    def action_proceed(self) -> None:
        if self._active_tab() == "tab-recent":
            recent_list = self.query_one("#recent-list", OptionList)
            if self.focused is not recent_list:
                recent_list.focus()
            elif recent_list.highlighted is not None:
                self.action_start_recent(recent_list.highlighted)
            return
        if isinstance(self.focused, Tabs):
            self.action_focus_filter()
            return
        if self._active_tab() == "tab-entra":
            selected_roles = [self.all_roles[i] for i in sorted(self._selected)]
            if not selected_roles:
                self.notify("Select at least one role.", severity="warning")
                return
            self._open_entra_activation(selected_roles)
        else:
            selected_ids: list[str] = list(self._selected_ids)
            if not selected_ids:
                self.notify("Select at least one subscription.", severity="warning")
                return
            from fomo.screens.roles_screen import RolesScreen

            names = {sub.id: sub.name for sub in self._all_subs}
            self.app.push_screen(RolesScreen(selected_ids, names))

    def _open_entra_activation(self, selected_roles: list[azure.EntraEligibleRole]) -> None:
        """Warn about high-risk roles, then open the Entra activation screen for *selected_roles*."""
        high_risk = [
            t
            for r in selected_roles
            if (t := tiering.get_entra_tier(r.role_definition_id)) is not None and t["tier"] <= 1
        ]
        if high_risk:
            summary = tiering.high_risk_summary(high_risk)
            self.notify(
                f"Blast-radius warning: {len(high_risk)} high-risk role(s) selected\n{summary}",
                severity="warning",
                timeout=15,
                markup=False,
            )
        from fomo.screens.entra_screen import EntraActivationScreen

        screen = EntraActivationScreen(selected_roles, **self._entra_prefill)
        self.app.push_screen(screen, self._after_entra_activation)

    def _after_entra_activation(self, result: ActivationResult[azure.EntraEligibleRole] | None) -> None:
        """Back on the Entra tab from the Entra activation screen (Done or Escape).

        After a run (*result* is not ``None``), mark the activated roles
        active and clear the selection, so nothing is submitted twice.
        """
        if result is None or not self.is_attached:
            return
        # A recent activation's reason and duration were for that run only.
        self._entra_prefill = {}
        activated = {(role.role_definition_id, role.directory_scope_id) for role in result.activated}
        for role in self.all_roles:
            if (role.role_definition_id, role.directory_scope_id) in activated:
                role.is_active = True
        self._selected.clear()
        self._rebuild_entra_list(self.query_one("#entra-filter", Input).value)
        self._update_entra_status()

    def action_select_focused(self) -> None:
        list_id = "#entra-role-list" if self._active_tab() == "tab-entra" else "#sub-list"
        sub_list = self.query_one(list_id, SelectionList)
        if self.focused is sub_list:
            sub_list.action_select()
        else:
            focused = self.focused
            if focused is not None and hasattr(focused, "insert_text_at_cursor"):
                focused.insert_text_at_cursor("x")

    def action_cycle_sort(self) -> None:
        """Azure tab: toggle A→Z / Z→A. Entra tab: cycle name → tier → expiry."""
        if self._active_tab() != "tab-entra":
            if not self._all_subs:
                return
            self._subs_desc = not self._subs_desc
            self._rebuild_list(self.query_one("#filter", Input).value)
            self._update_sel_count()
            return
        if not self._entra_loaded or not self.all_roles:
            return
        idx = ENTRA_SORT_MODES.index(self._entra_sort_mode)
        self._entra_sort_mode = ENTRA_SORT_MODES[(idx + 1) % len(ENTRA_SORT_MODES)]
        self._rebuild_entra_list(self.query_one("#entra-filter", Input).value)
        self._update_entra_status()

    def action_open_assignments(self) -> None:
        from fomo.screens.assignments_screen import AssignmentsScreen

        self.app.push_screen(AssignmentsScreen())

    def action_quit_app(self) -> None:
        self.app.exit()

    # ------------------------------------------------------------------
    # Arrow navigation (vim actions come from VimNavMixin)
    # ------------------------------------------------------------------

    def action_arrow_down(self) -> None:
        self.focus_next()

    def action_arrow_up(self) -> None:
        self.focus_previous()
