"""Roles screen — fzf-like multiselect for eligible PIM roles."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Header, Input, Label, LoadingIndicator
from textual.widgets.selection_list import Selection

from fomo import azure, tiering, timefmt
from fomo.screens._common import VimNavMixin, role_detail_state, role_list_prompt, safe_markup
from fomo.widgets import FomoSelectionList as SelectionList

if TYPE_CHECKING:
    from fomo.screens._activation_base import ActivationResult

MAX_ROLES = 3
SORT_MODES = ("name", "scope", "tier", "expiry")
# Subscriptions whose roles load at the same time.  Each load runs a few `az`
# processes, so fifty selected subscriptions must not start them all at once.
MAX_PARALLEL_LOADS = 4
# A load error is cut to this many characters in the load errors dialog.
_LOAD_ERROR_LIMIT = 300


class LoadErrorsModal(ModalScreen[bool]):
    """The subscriptions whose roles failed to load, each with its error (``e``).

    Dismisses with ``True`` for Retry (load just those subscriptions again)
    and ``False`` for Close.
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("r", "retry", "Retry"),
    ]

    def __init__(self, failures: list[tuple[str, str, str]]) -> None:
        """*failures* holds ``(subscription name or "", subscription id, error)`` triples."""
        super().__init__()
        self.failures = failures

    def compose(self) -> ComposeResult:
        count = len(self.failures)
        with Vertical(id="load-errors-dialog"):
            yield Label(
                f"{count} subscription{'' if count == 1 else 's'} failed to load",
                id="load-errors-title",
            )
            with VerticalScroll(id="load-errors-list"):
                for name, sub_id, error in self.failures:
                    template = "[bold]$name[/bold]  [dim]$id[/dim]\n$error" if name else "[bold]$id[/bold]\n$error"
                    yield Label(safe_markup(template, name=name, id=sub_id, error=error), classes="load-error")
            with Horizontal(id="load-errors-buttons"):
                yield Button("Retry", variant="primary", id="load-errors-retry")
                yield Button("Close", id="load-errors-close")

    def on_mount(self) -> None:
        self.query_one("#load-errors-retry").focus()

    @on(Button.Pressed, "#load-errors-retry")
    def action_retry(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#load-errors-close")
    def action_close(self) -> None:
        self.dismiss(False)


def _short_error(message: str, limit: int = _LOAD_ERROR_LIMIT) -> str:
    """*message* without surrounding blank space, cut to *limit* characters."""
    message = message.strip()
    return message if len(message) <= limit else message[: limit - 1] + "…"


class RolesScreen(VimNavMixin, Screen):
    """Fuzzy-filter and multiselect eligible PIM roles."""

    BINDINGS = [
        # Priority bindings: Enter in the filter never reaches Input.Submitted.
        # check_action enables exactly one of the two, so the footer shows what
        # Enter does: move from the filter to the list, or activate.
        Binding("enter", "to_list", "To list", show=True, priority=True),
        Binding("enter", "proceed", "Activate selected", show=True, priority=True),
        Binding("escape", "app.pop_screen", "Back", show=True, priority=True),
        Binding("q", "app.pop_screen", "Back", show=False),
        Binding("tab", "focus_list", "Next box", show=True),
        Binding("shift+tab", "focus_filter", "Prev box", show=True),
        Binding("slash", "focus_filter", "Filter", show=False),
        Binding("a", "select_all_visible", "All", show=True),
        # Only while subscriptions failed to load; the status line says so.
        Binding("e", "show_load_errors", "Load errors", show=False),
        Binding("ctrl+s", "cycle_sort", "Sort", show=True, priority=True),
        Binding("j", "vim_down", "↓", show=False),
        Binding("k", "vim_up", "↑", show=False),
        Binding("g", "vim_top", "Top", show=False),
        Binding("G", "vim_bottom", "Bottom", show=False),
        Binding("x", "select_focused", "Toggle", show=False, priority=True),
    ]

    def __init__(self, subscription_ids: list[str], subscription_names: dict[str, str] | None = None) -> None:
        super().__init__()
        self._sub_ids = subscription_ids
        self._sub_names = subscription_names or {}
        self.all_roles: list[azure.EligibleRole] = []
        self._selected: set[int] = set()  # indices into all_roles
        self._visible_indices: set[int] = set()
        self._option_values: list[int | None] = []  # option_index → all_roles index (None for separators)
        self._loaded_count = 0
        self._rebuilding = False
        self._auth_error_shown = False
        self._auth_failed_subs: list[str] = []  # failed with an expired/missing session
        self._failed_subs: dict[str, str] = {}  # subscription id → error of its last load, any kind
        self._sort_mode = SORT_MODES[0]
        # Shared by every subscription worker of this screen, retries included.
        self._load_slots = threading.BoundedSemaphore(MAX_PARALLEL_LOADS)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="loading-area"):
            yield Label(
                f"Loading roles from {len(self._sub_ids)} subscription(s)…",
                id="loading-label",
            )
            yield LoadingIndicator(id="spinner")
        with Horizontal(id="split"):
            with Vertical(id="left-pane"):
                yield Input(placeholder="Filter roles… (type to search)", id="filter")
                yield SelectionList(id="role-list")
                yield Label("", id="status")
            with Vertical(id="detail-pane"):
                yield Label(
                    "[dim]Navigate the list to see role details.[/dim]",
                    id="detail",
                )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#split").display = False
        self._load_tiering()
        for sub_id in self._sub_ids:
            self._load_roles_for_sub(sub_id)

    # ------------------------------------------------------------------
    # Background loading (one worker per subscription, at most
    # MAX_PARALLEL_LOADS fetching at a time, plus one for the optional tier data)
    # ------------------------------------------------------------------

    @work(thread=True)
    def _load_tiering(self) -> None:
        # Separate from the role fetches: tier data is optional, and loading
        # it never raises, so it can neither delay nor fail the role list.
        tiering.ensure_azure_loaded(allow_network=self.app.backend.allow_network)  # type: ignore[attr-defined]
        self.app.call_from_thread(self._on_tiering_loaded)

    @work(thread=True)
    def _load_roles_for_sub(self, sub_id: str) -> None:
        try:
            with self._load_slots:
                roles = self.app.backend.list_eligible_roles(sub_id)  # type: ignore[attr-defined]
        except Exception as exc:
            self.app.call_from_thread(self._on_roles_error, sub_id, str(exc))
            return
        # Outside the try: a failure in the UI callback is not a fetch error
        # and must not count this subscription a second time.
        self.app.call_from_thread(self._on_roles_loaded, sub_id, roles)

    def _on_tiering_loaded(self) -> None:
        """Re-render the detail pane if the list appeared before the tier data."""
        if self.is_attached and self.query_one("#split").display:
            self._refresh_detail()

    def _on_roles_loaded(self, _sub_id: str, roles: list[azure.EligibleRole]) -> None:
        self.all_roles.extend(roles)
        self._increment_loaded()

    def _on_roles_error(self, sub_id: str, msg: str) -> None:
        # Every failure stays in the status line ("e" lists them).  Only an
        # expired or missing session opens the dialog, and only once; MFA,
        # consent and other errors are reported for their subscription.
        self._failed_subs[sub_id] = msg
        if azure.is_auth_error(msg):
            self._auth_failed_subs.append(sub_id)
            if not self._auth_error_shown:
                self._auth_error_shown = True
                self.app.show_auth_error(  # type: ignore[attr-defined]
                    azure.classify_auth_error(msg), msg, self._retry_failed_subs
                )
        else:
            self.notify(f"[{sub_id[:8]}…] {msg}", severity="error", timeout=8, markup=False)
        self._increment_loaded()

    def _retry_failed_subs(self) -> None:
        """Reload the subscriptions that failed with a session error (Retry after re-login)."""
        failed, self._auth_failed_subs = self._auth_failed_subs, []
        self._auth_error_shown = False
        # Those the load errors dialog has retried meanwhile are loading already.
        self._reload_subs([sub_id for sub_id in failed if sub_id in self._failed_subs])

    def _retry_all_failed_subs(self) -> None:
        """Reload every subscription that failed, whatever the error (Retry in the ``e`` dialog)."""
        self._auth_failed_subs = []
        self._auth_error_shown = False
        self._reload_subs(list(self._failed_subs))

    def _reload_subs(self, sub_ids: list[str]) -> None:
        """Load the roles of *sub_ids*, which have failed, again."""
        if not sub_ids or not self.is_attached:
            return
        for sub_id in sub_ids:
            self._failed_subs.pop(sub_id, None)
        self._loaded_count -= len(sub_ids)
        if self.query_one("#split").display:
            self._update_status()
        else:
            self.query_one("#spinner").display = True
            self.query_one("#loading-label", Label).update(f"Loading roles… {self._loaded_count}/{len(self._sub_ids)}")
        for sub_id in sub_ids:
            self._load_roles_for_sub(sub_id)

    def _increment_loaded(self) -> None:
        self._loaded_count += 1
        self.query_one("#loading-label", Label).update(f"Loading roles… {self._loaded_count}/{len(self._sub_ids)}")
        if self._loaded_count < len(self._sub_ids):
            return
        # All subscriptions have responded
        self.query_one("#spinner").display = False
        if not self.all_roles:
            if self._failed_subs:
                # Not "no roles found": some subscriptions could not be read at all.
                others = "\n[dim]No eligible PIM roles in the others.[/dim]" if self._loaded_ok_count() else ""
                self.query_one("#loading-label", Label).update(self._load_failure_markup() + others)
                # The (hidden) filter has had focus since the screen opened;
                # it would swallow the "e" the label asks for.
                self.set_focus(None)
                return
            self.query_one("#loading-label", Label).update(
                "[dim]No eligible PIM roles found in the selected subscriptions.[/dim]"
            )
            self.notify(
                "No eligible PIM roles found in the selected subscriptions.",
                severity="warning",
                timeout=10,
            )
            return
        # Deduplicate: same role on the same scope may appear once per queried subscription.
        # role_definition_id is a full resource path that includes the subscription ID,
        # so extract just the trailing GUID for the comparison key.
        seen: set[tuple[str, str]] = set()
        unique: list[azure.EligibleRole] = []
        for r in self.all_roles:
            role_guid = r.role_definition_id.rsplit("/", 1)[-1]
            key = (role_guid, r.scope)
            if key not in seen:
                seen.add(key)
                unique.append(r)
        self.all_roles = unique
        self.query_one("#loading-area").display = False
        self.query_one("#split").display = True
        # Keep the filter: after a retry the list may already have been in use.
        self._rebuild_list(self.query_one("#filter", Input).value)
        self.query_one("#filter").focus()

    # ------------------------------------------------------------------
    # List management
    # ------------------------------------------------------------------

    def _loaded_ok_count(self) -> int:
        """How many subscriptions have loaded without an error."""
        return self._loaded_count - len(self._failed_subs)

    def _load_failure_markup(self) -> str:
        """E.g. "⚠ 2 of 5 subscriptions failed · e details" (no external text)."""
        return (
            f"[bold $text-warning]⚠ {len(self._failed_subs)} of {len(self._sub_ids)} subscriptions failed[/]"
            " · [bold]e[/bold] details"
        )

    def _sort_key(self, role: azure.EligibleRole) -> tuple:
        name = role.role_name.casefold()
        scope = role.scope_display_name.casefold()
        if self._sort_mode == "scope":
            return (scope, name)
        if self._sort_mode == "tier":
            info = tiering.get_azure_tier(role.role_definition_id)
            return (info["tier"] if info else 99, name, scope)
        if self._sort_mode == "expiry":
            return (role.expiry is None, role.expiry or "", name, scope)
        return (name, scope)

    def _display_order(self) -> list[int]:
        """Indices into all_roles in list order: subscription roles, then global ones, each sorted."""
        ordered = sorted(range(len(self.all_roles)), key=lambda i: self._sort_key(self.all_roles[i]))
        return [i for i in ordered if not self.all_roles[i].is_global] + [
            i for i in ordered if self.all_roles[i].is_global
        ]

    def _rebuild_list(self, query: str) -> None:
        sl = self.query_one("#role-list", SelectionList)
        self._rebuilding = True
        sl.clear_options()
        self._visible_indices = set()
        self._option_values = []
        q = query.strip().lower()

        ordered = [(i, self.all_roles[i]) for i in self._display_order()]
        sub_items = [(i, r) for i, r in ordered if not r.is_global]
        global_items = [(i, r) for i, r in ordered if r.is_global]

        now = timefmt.now()

        def _add(items: list) -> None:
            for i, role in items:
                display, prompt = role_list_prompt(f"{role.role_name}  —  {role.scope_display_name}", role, now)
                if q and q not in display.lower():
                    continue
                if role.is_active:
                    sl.add_option(Selection(prompt, i, False, disabled=True))
                else:
                    sl.add_option(Selection(prompt, i, i in self._selected))
                    self._visible_indices.add(i)
                self._option_values.append(i)

        _add(sub_items)

        visible_globals = [
            (i, r) for i, r in global_items if not q or q in f"{r.role_name}  —  {r.scope_display_name}".lower()
        ]
        if visible_globals:
            sl.add_option(
                Selection(
                    "⚠ Global assignments (management group scope)",
                    -1,
                    disabled=True,
                )
            )
            self._option_values.append(None)
            _add(global_items)

        self._rebuilding = False
        self._update_status()
        first = next((v for v in self._option_values if v is not None), None)
        if first is not None:
            self._update_detail(self.all_roles[first])
        else:
            self.query_one("#detail", Label).update("[dim]No roles match filter.[/dim]")

    def _update_status(self) -> None:
        """E.g. "2 selected · 5/7 shown · sort: name", plus a line about failed loads.

        Shown counts every listed role, the active (disabled) ones included,
        but not the global-assignments separator.
        """
        n_sel = len(self._selected)
        n_shown = sum(1 for value in self._option_values if value is not None)
        n_total = len(self.all_roles)
        status = f"{n_sel} selected · {n_shown}/{n_total} shown · sort: {self._sort_mode}"
        if self._failed_subs:
            status += "\n" + self._load_failure_markup()
        self.query_one("#status", Label).update(status)

    def _refresh_detail(self) -> None:
        """Re-render the detail pane for the highlighted (or first listed) role."""
        idx = self.query_one("#role-list", SelectionList).highlighted
        role_idx = self._option_values[idx] if idx is not None and 0 <= idx < len(self._option_values) else None
        if role_idx is None:
            role_idx = next((v for v in self._option_values if v is not None), None)
        if role_idx is not None:
            self._update_detail(self.all_roles[role_idx])

    def _update_detail(self, role: azure.EligibleRole) -> None:
        """Render tier + security info for *role* in the right-hand detail pane."""
        detail_lbl = self.query_one("#detail", Label)
        tier_info = tiering.get_azure_tier(role.role_definition_id)
        scope = role.scope_display_name
        active, eligible = role_detail_state(role, timefmt.now())
        active_tag = "\n[bold $success]● $active[/]" if active else ""

        if not tier_info:
            detail_lbl.update(
                safe_markup(
                    f"[bold]$name[/bold]{active_tag}\n"
                    "[dim]$scope[/dim]\n"
                    "$eligible\n\n"
                    "[dim]No tiering data available for this role.[/dim]",
                    name=role.role_name,
                    active=active,
                    scope=scope,
                    eligible=eligible,
                )
            )
            return

        tier = tier_info["tier"]
        badge = tiering.tier_badge(tier)
        tlabel = tiering.tier_label(tier)
        attack = (tier_info.get("attack_path") or "").strip()
        col = tiering.TIER_COLOUR.get(tier, "white")
        path_headers = {0: "Attack path", 1: "Lateral movement", 2: "Worst case", 3: "Worst case"}
        path_header = path_headers.get(tier, "Notes")

        parts: list[str] = [
            f"{badge} [bold {col}]Tier {tier}[/bold {col}]  [dim]{tlabel}[/dim]",
            "",
            f"[bold]$name[/bold]{active_tag}",
            "[dim]$scope[/dim]",
            "$eligible",
        ]
        if attack and attack != "-":
            parts.extend(["", f"[bold]{path_header}:[/bold]", "$attack"])
        detail_lbl.update(
            safe_markup(
                "\n".join(parts),
                name=role.role_name,
                active=active,
                scope=scope,
                eligible=eligible,
                attack=attack,
            )
        )

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    @on(SelectionList.SelectionHighlighted, "#role-list")
    def on_option_highlighted(self, event: SelectionList.SelectionHighlighted) -> None:
        """Update the detail pane when the cursor moves in the role list."""
        idx = event.selection_index
        if idx < 0 or idx >= len(self._option_values):
            return
        role_idx = self._option_values[idx]
        if role_idx is None or role_idx < 0 or role_idx >= len(self.all_roles):
            return
        self._update_detail(self.all_roles[role_idx])

    @on(Input.Changed, "#filter")
    def on_filter_changed(self, event: Input.Changed) -> None:
        # Snapshot visible selections before rebuilding
        sl = self.query_one("#role-list", SelectionList)
        self._selected.update(sl.selected)
        self._rebuild_list(event.value)

    @on(SelectionList.SelectedChanged, "#role-list")
    def on_selection_changed(self, event: SelectionList.SelectedChanged) -> None:
        if self._rebuilding:
            return
        visible_selected: set[int] = set(event.selection_list.selected)
        visible_unselected = self._visible_indices - visible_selected
        self._selected |= visible_selected
        self._selected -= visible_unselected
        self._update_status()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_select_focused(self) -> None:
        """Toggle selection when role list has focus; otherwise type 'x' normally."""
        role_list = self.query_one("#role-list", SelectionList)
        if self.focused is role_list:
            role_list.action_select()
        else:
            # Not on the list — pass x through as a character to the focused widget.
            focused = self.focused
            if focused is not None and hasattr(focused, "insert_text_at_cursor"):
                focused.insert_text_at_cursor("x")

    def action_cycle_sort(self) -> None:
        """Cycle the role list sort order: name → scope → tier → expiry."""
        if not self.query_one("#split").display:
            return
        self._sort_mode = SORT_MODES[(SORT_MODES.index(self._sort_mode) + 1) % len(SORT_MODES)]
        self._rebuild_list(self.query_one("#filter", Input).value)

    def _filter_has_focus(self) -> bool:
        focused = self.focused
        return isinstance(focused, Input) and focused.id == "filter"

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # Enter is "to_list" while the filter has focus and "proceed" otherwise.
        if action == "to_list":
            return self._filter_has_focus()
        if action == "proceed":
            return not self._filter_has_focus()
        if action == "show_load_errors":
            return bool(self._failed_subs)
        return super().check_action(action, parameters)

    def action_show_load_errors(self) -> None:
        """e: list the subscriptions that failed to load; Retry loads just those again."""
        failures = [
            (self._sub_names.get(sub_id, ""), sub_id, _short_error(error))
            for sub_id, error in self._failed_subs.items()
        ]

        def _closed(retry: bool | None) -> None:
            if retry:
                self._retry_all_failed_subs()

        self.app.push_screen(LoadErrorsModal(failures), _closed)

    def action_to_list(self) -> None:
        """Enter in the filter: move focus to the list."""
        self.action_focus_list()

    def action_focus_list(self) -> None:
        self.query_one("#role-list").focus()

    def action_focus_filter(self) -> None:
        self.query_one("#filter").focus()

    def action_select_all_visible(self) -> None:
        """Select all currently visible (filtered) roles that can be activated.

        Not SelectionList.select_all: that also selects the disabled rows (the
        active roles and the global-assignments separator), and its
        SelectedChanged arrives after any flag set around it is cleared.
        """
        self._selected.update(self._visible_indices)
        sl = self.query_one("#role-list", SelectionList)
        with sl.prevent(SelectionList.SelectedChanged):
            for index in self._visible_indices:
                sl.select(index)
        self._update_status()

    def action_proceed(self) -> None:
        # Merge any pending visible selections
        if self.query_one("#role-list").display:
            sl = self.query_one("#role-list", SelectionList)
            self._selected.update(sl.selected)
            visible_unselected = self._visible_indices - set(sl.selected)
            self._selected -= visible_unselected

        # In the order the list shows them, whatever order they were selected in.
        selected_roles = [self.all_roles[i] for i in self._display_order() if i in self._selected]
        if not selected_roles:
            self.notify("Select at least one role.", severity="warning")
            return

        # Blast-radius warning for high-risk (Tier 0 / Tier 1) roles
        high_risk = [
            t
            for r in selected_roles
            if (t := tiering.get_azure_tier(r.role_definition_id)) is not None and t["tier"] <= 1
        ]
        if high_risk:
            summary = tiering.high_risk_summary(high_risk)
            self.notify(
                f"Blast-radius warning: {len(high_risk)} high-risk role(s) selected\n{summary}",
                severity="warning",
                timeout=15,
                markup=False,
            )

        if len(selected_roles) > MAX_ROLES:
            self.notify(
                f"You selected {len(selected_roles)} roles. Activating more than {MAX_ROLES} "
                "at once can be slow and error-prone. Proceed with care.",
                severity="warning",
                timeout=8,
            )
        from fomo.screens.activation_screen import ActivationScreen

        self.app.push_screen(ActivationScreen(selected_roles), self._after_activation)

    def _after_activation(self, result: ActivationResult[azure.EligibleRole] | None) -> None:
        """Back from the activation screen.

        Without a finished run (*result* is ``None``) nothing changes.  After
        one, Done returns to the scope screen, which keeps its subscription
        selection; Escape stays here, with the activated roles marked active
        (so they can't be submitted twice) and the selection cleared.
        """
        if result is None or not self.is_attached:
            return
        if result.done:
            self.dismiss()
            return
        activated = {(role.role_definition_id, role.scope) for role in result.activated}
        for role in self.all_roles:
            if (role.role_definition_id, role.scope) in activated:
                role.is_active = True
        self._selected.clear()
        self._rebuild_list(self.query_one("#filter", Input).value)
