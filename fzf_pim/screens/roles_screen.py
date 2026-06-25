"""Roles screen — fzf-like multiselect for eligible PIM roles."""

from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Label, LoadingIndicator, SelectionList
from textual.widgets._selection_list import Selection

MAX_ROLES = 3

from fzf_pim import azure


class RolesScreen(Screen):
    """Fuzzy-filter and multiselect eligible PIM roles."""

    BINDINGS = [
        Binding("enter", "proceed", "Activate selected", show=True, priority=True),
        Binding("escape", "app.pop_screen", "Back", show=True, priority=True),
        Binding("q", "app.pop_screen", "Back", show=False),
        Binding("tab", "focus_list", "Next box", show=True),
        Binding("shift+tab", "focus_filter", "Prev box", show=True),
        Binding("slash", "focus_filter", "Filter", show=False),
        Binding("a", "select_all_visible", "All", show=True),
        Binding("j", "vim_down", "↓", show=False),
        Binding("k", "vim_up", "↑", show=False),
        Binding("g", "vim_top", "Top", show=False),
        Binding("G", "vim_bottom", "Bottom", show=False),
        Binding("x", "select_focused", "Toggle", show=False, priority=True),
    ]

    def __init__(self, subscription_ids: list[str]) -> None:
        super().__init__()
        self._sub_ids = subscription_ids
        self.all_roles: list[azure.EligibleRole] = []
        self._selected: set[int] = set()       # indices into all_roles
        self._visible_indices: set[int] = set()
        self._loaded_count = 0
        self._rebuilding = False
        self._auth_error_shown = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="main"):
            yield Label(
                f"Loading roles from {len(self._sub_ids)} subscription(s)…",
                id="loading-label",
            )
            yield LoadingIndicator(id="spinner")
            yield Input(placeholder="Filter roles… (type to search)", id="filter")
            yield SelectionList(id="role-list")
            yield Label("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#filter").display = False
        self.query_one("#role-list").display = False
        self.query_one("#status").display = False
        for sub_id in self._sub_ids:
            self._load_roles_for_sub(sub_id)

    # ------------------------------------------------------------------
    # Background loading (one worker per subscription, run in parallel)
    # ------------------------------------------------------------------

    @work(thread=True)
    def _load_roles_for_sub(self, sub_id: str) -> None:
        try:
            roles = azure.list_eligible_roles(sub_id)
            self.app.call_from_thread(self._on_roles_loaded, sub_id, roles)
        except Exception as exc:
            self.app.call_from_thread(self._on_roles_error, sub_id, str(exc))

    def _on_roles_loaded(
        self, sub_id: str, roles: list[azure.EligibleRole]
    ) -> None:
        self.all_roles.extend(roles)
        self._increment_loaded()

    def _on_roles_error(self, sub_id: str, msg: str) -> None:
        if azure.is_auth_error(msg):
            if not self._auth_error_shown:
                self._auth_error_shown = True
                self.notify(
                    "Azure session expired. Run [bold]az login[/bold] and restart.",
                    severity="error",
                    timeout=30,
                )
        else:
            self.notify(f"[{sub_id[:8]}…] {msg}", severity="error", timeout=8)
        self._increment_loaded()

    def _increment_loaded(self) -> None:
        self._loaded_count += 1
        self.query_one("#loading-label", Label).update(
            f"Loading roles… {self._loaded_count}/{len(self._sub_ids)}"
        )
        if self._loaded_count < len(self._sub_ids):
            return
        # All subscriptions have responded
        self.query_one("#spinner").display = False
        self.query_one("#loading-label").display = False
        if not self.all_roles:
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
        self.all_roles.sort(key=lambda r: (r.role_name, r.scope_display_name))
        self.query_one("#filter").display = True
        self.query_one("#role-list").display = True
        self.query_one("#status").display = True
        self._rebuild_list("")
        self.query_one("#filter").focus()

    # ------------------------------------------------------------------
    # List management
    # ------------------------------------------------------------------

    def _rebuild_list(self, query: str) -> None:
        sl = self.query_one("#role-list", SelectionList)
        self._rebuilding = True
        sl.clear_options()
        self._visible_indices = set()
        q = query.strip().lower()

        sub_items = [(i, r) for i, r in enumerate(self.all_roles) if not r.is_global]
        global_items = [(i, r) for i, r in enumerate(self.all_roles) if r.is_global]

        def _add(items: list) -> None:
            for i, role in items:
                text = f"{role.role_name}  —  {role.scope_display_name}"
                expiry_tag = f"  [expires {azure.format_expiry(role.expiry)}]" if role.expiry else ""
                active_tag = "  (active)" if role.is_active else ""
                display = f"{text}{expiry_tag}{active_tag}"
                if q and q not in display.lower():
                    continue
                if role.is_active:
                    sl.add_option(Selection(display, i, False, disabled=True))
                else:
                    sl.add_option(Selection(display, i, i in self._selected))
                    self._visible_indices.add(i)

        _add(sub_items)

        visible_globals = [
            (i, r) for i, r in global_items
            if not q or q in f"{r.role_name}  —  {r.scope_display_name}".lower()
        ]
        if visible_globals:
            sl.add_option(Selection(
                "⚠ Global assignments (management group scope)",
                -1,
                disabled=True,
            ))
            _add(global_items)

        self._rebuilding = False
        self._update_status()

    def _update_status(self) -> None:
        n_sel = len(self._selected)
        n_vis = len(self._visible_indices)
        n_total = len(self.all_roles)
        parts = [f"{n_sel} selected"]
        if n_vis < n_total:
            parts.append(f"{n_vis}/{n_total} shown")
        self.query_one("#status", Label).update("  ·  ".join(parts))

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    @on(Input.Changed, "#filter")
    def on_filter_changed(self, event: Input.Changed) -> None:
        # Snapshot visible selections before rebuilding
        sl = self.query_one("#role-list", SelectionList)
        self._selected.update(sl.selected)
        self._rebuild_list(event.value)

    @on(Input.Submitted, "#filter")
    def on_filter_submitted(self, event: Input.Submitted) -> None:  # noqa: ARG002
        """Select all visible items and move focus to the list."""
        self.action_select_all_visible()
        self.query_one("#role-list").focus()

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

    def action_focus_list(self) -> None:
        self.query_one("#role-list").focus()

    def action_focus_filter(self) -> None:
        self.query_one("#filter").focus()

    def action_select_all_visible(self) -> None:
        """Select all currently visible (filtered) roles."""
        self._selected.update(self._visible_indices)
        sl = self.query_one("#role-list", SelectionList)
        self._rebuilding = True
        sl.select_all()
        self._rebuilding = False
        self._update_status()

    def action_vim_down(self) -> None:
        w = self.focused
        if hasattr(w, "action_cursor_down"):
            w.action_cursor_down()

    def action_vim_up(self) -> None:
        w = self.focused
        if hasattr(w, "action_cursor_up"):
            w.action_cursor_up()

    def action_vim_top(self) -> None:
        w = self.focused
        if hasattr(w, "scroll_home"):
            w.scroll_home(animate=False)

    def action_vim_bottom(self) -> None:
        w = self.focused
        if hasattr(w, "scroll_end"):
            w.scroll_end(animate=False)

    def action_proceed(self) -> None:
        if self.focused is self.query_one("#filter"):
            self.action_focus_list()
            return
        # Merge any pending visible selections
        if self.query_one("#role-list").display:
            sl = self.query_one("#role-list", SelectionList)
            self._selected.update(sl.selected)
            visible_unselected = self._visible_indices - set(sl.selected)
            self._selected -= visible_unselected

        selected_roles = [self.all_roles[i] for i in sorted(self._selected)]
        if not selected_roles:
            self.notify("Select at least one role.", severity="warning")
            return
        if len(selected_roles) > MAX_ROLES:
            self.notify(
                f"You selected {len(selected_roles)} roles. Activating more than {MAX_ROLES} at once can be slow and error-prone. Proceed with care.",
                severity="warning",
                timeout=8,
            )
        from fzf_pim.screens.activation_screen import ActivationScreen
        self.app.push_screen(ActivationScreen(selected_roles))
