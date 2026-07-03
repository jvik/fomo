"""Scope screen — pick which Azure subscriptions to load PIM roles from."""

from __future__ import annotations

import threading

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    LoadingIndicator,
    TabbedContent,
    TabPane,
    Tabs,
)

from fomo.widgets import FomoSelectionList as SelectionList
from textual.widgets._selection_list import Selection

from rich.text import Text

from fomo import azure, tiering

MAX_SUBSCRIPTIONS = 3


class ScopeScreen(Screen):
    """First screen: select Azure subscriptions or Entra roles."""

    BINDINGS = [
        Binding("enter", "proceed", "Proceed", show=True, priority=True),
        Binding("slash", "focus_filter", "Filter", show=True),
        Binding("escape", "escape_key", "Back to filter", show=False, priority=True),
        Binding("a", "select_all", "All", show=True),
        Binding("n", "select_none", "None", show=True),
        Binding("i", "open_assignments", "Assignments", show=True),
        Binding("q", "quit_app", "Quit", show=True),
        Binding("up", "arrow_up", "↑", show=False),
        Binding("down", "arrow_down", "↓", show=False),
        Binding("h", "prev_tab", "← Tab", show=False),
        Binding("l", "next_tab", "→ Tab", show=False),
        Binding("j", "vim_down", "↓", show=False),
        Binding("k", "vim_up", "↑", show=False),
        Binding("g", "vim_top", "Top", show=False),
        Binding("G", "vim_bottom", "Bottom", show=False),
        Binding("x", "select_focused", "Toggle", show=False, priority=True),
    ]

    def __init__(self, initial_tab: str = "tab-azure") -> None:
        super().__init__()
        self._initial_tab = initial_tab
        # Azure tab state
        self._all_subs: list[azure.Subscription] = []
        self._visible_ids: set[str] = set()
        self._rebuilding = False
        # Entra tab state
        self._entra_loaded = False
        self._entra_loading = False
        self._stop_event = threading.Event()
        self.all_roles: list[azure.EntraEligibleRole] = []
        self._selected: set[int] = set()
        self._visible_indices: set[int] = set()
        self._option_values: list[int | None] = []
        self._entra_rebuilding = False

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
        yield Label("[bold]←/→[/bold] switch tab  •  [bold]Tab[/bold] enter list", id="tab-hint")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#sub-list").display = False
        self.query_one("#filter").display = False
        self.query_one("#sel-count").display = False
        self.query_one("#entra-split").display = False
        self.query_one("#entra-spinner").display = False
        self._load_subs()
        if self._initial_tab == "tab-entra":
            self._start_entra_load()
        self.call_after_refresh(self.query_one("#scope-tabs").focus)

    def on_unmount(self) -> None:
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Tab navigation
    # ------------------------------------------------------------------

    def _active_tab(self) -> str:
        return self.query_one("#scope-tabs", TabbedContent).active or "tab-azure"

    def action_next_tab(self) -> None:
        tc = self.query_one("#scope-tabs", TabbedContent)
        tc.active = "tab-entra" if tc.active == "tab-azure" else "tab-azure"

    def action_prev_tab(self) -> None:
        tc = self.query_one("#scope-tabs", TabbedContent)
        tc.active = "tab-azure" if tc.active == "tab-entra" else "tab-entra"

    @on(TabbedContent.TabActivated, "#scope-tabs")
    def on_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.pane.id == "tab-entra" and not self._entra_loaded and not self._entra_loading:
            self._start_entra_load()

    def watch_focused(self, focused) -> None:
        try:
            self.query_one("#tab-hint").display = isinstance(focused, Tabs)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Azure — subscription loading
    # ------------------------------------------------------------------

    @work(thread=True)
    def _load_subs(self) -> None:
        try:
            if getattr(self.app, "demo_mode", False):
                from fomo import demo as demo_data
                subs = demo_data.list_subscriptions()
            else:
                subs = azure.list_subscriptions()
            self.app.call_from_thread(self._show_subs, subs)
        except Exception as exc:
            self.app.call_from_thread(self._show_error, str(exc))

    def _show_subs(self, subs: list[azure.Subscription]) -> None:
        self.query_one("#spinner").display = False
        self.query_one("#loading-label", Label).update(
            f"Select subscriptions  ({len(subs)} found)"
        )
        self._all_subs = subs
        self.query_one("#filter").display = True
        self._rebuild_list("")
        sl = self.query_one("#sub-list", SelectionList)
        sl.display = True
        self.query_one("#sel-count").display = True
        self._update_sel_count()
        self.query_one("#scope-tabs").focus()

    def _show_error(self, msg: str) -> None:
        self.query_one("#spinner").display = False
        if azure.is_auth_error(msg):
            body = (
                "[bold red]Azure session expired.[/bold red]\n\n"
                "Run [bold]az login[/bold] in your terminal, then restart fomo."
            )
        else:
            body = (
                f"[bold red]Error:[/bold red] {msg}\n\n"
                "Is [bold]az[/bold] installed and are you logged in?  Run: [bold]az login[/bold]"
            )
        self.query_one("#loading-label", Label).update(body)

    # ------------------------------------------------------------------
    # Azure — filter helpers
    # ------------------------------------------------------------------

    def _rebuild_list(self, query: str) -> None:
        sl = self.query_one("#sub-list", SelectionList)
        current_selected: set[str] = set(sl.selected)
        self._rebuilding = True
        sl.clear_options()
        self._visible_ids = set()
        q = query.strip().lower()
        for sub in self._all_subs:
            display = f"{sub.name}  [dim]{sub.id}[/dim]"
            if q and q not in f"{sub.name} {sub.id}".lower():
                continue
            sl.add_option((display, sub.id, sub.id in current_selected))
            self._visible_ids.add(sub.id)
        self._rebuilding = False

    @on(SelectionList.SelectedChanged, "#sub-list")
    def on_sub_selection_changed(self, event: SelectionList.SelectedChanged) -> None:  # noqa: ARG002
        if not self._rebuilding:
            self._update_sel_count()

    def _update_sel_count(self) -> None:
        n = len(self.query_one("#sub-list", SelectionList).selected)
        label = self.query_one("#sel-count", Label)
        if n == 0:
            label.update("[dim]No subscriptions selected[/dim]")
        elif n > MAX_SUBSCRIPTIONS:
            label.update(f"[bold]{n} subscriptions selected[/bold]  [bold red](warning: >{MAX_SUBSCRIPTIONS})[/bold red]")
        else:
            label.update(f"[bold]{n}[/bold] subscription(s) selected")

    @on(Input.Changed, "#filter")
    def on_filter_changed(self, event: Input.Changed) -> None:
        self._rebuild_list(event.value)

    @on(Input.Submitted, "#filter")
    def on_filter_submitted(self, event: Input.Submitted) -> None:  # noqa: ARG002
        self._select_all_subs_visible()
        self.query_one("#sub-list").focus()

    def _select_all_subs_visible(self) -> None:
        sl = self.query_one("#sub-list", SelectionList)
        self._rebuilding = True
        sl.select_all()
        self._rebuilding = False

    # ------------------------------------------------------------------
    # Entra — role loading
    # ------------------------------------------------------------------

    def _start_entra_load(self) -> None:
        self._entra_loading = True
        self.query_one("#entra-spinner").display = True
        self.query_one("#entra-loading-label", Label).update("Loading Entra eligible roles…")
        self._load_entra_roles()

    @work(thread=True)
    def _load_entra_roles(self) -> None:
        if getattr(self.app, "demo_mode", False):
            from fomo import demo as demo_data
            roles = demo_data.list_entra_eligible_roles()
            if not tiering._entra_index:
                tiering.load_entra()
            self.app.call_from_thread(self._on_entra_roles_loaded, roles)
            return

        def _on_device_code(message: str) -> None:
            url, _, code = message.partition("\n")
            def _update() -> None:
                self.query_one("#entra-loading-label", Label).update(
                    "[bold]Sign in to Microsoft Graph[/bold]\n\n"
                    f"[dim]1.[/dim] Open:  [link]{url}[/link]\n"
                    f"[dim]2.[/dim] Enter code:  [bold]{code}[/bold]\n\n"
                    "[dim]Waiting for authentication…[/dim]"
                )
            self.app.call_from_thread(_update)

        try:
            roles = azure.list_entra_eligible_roles(
                on_device_code=_on_device_code,
                stop_event=self._stop_event,
            )
            if not tiering._entra_index:
                tiering.load_entra()
            self.app.call_from_thread(self._on_entra_roles_loaded, roles)
        except Exception as exc:
            self.app.call_from_thread(self._on_entra_error, str(exc))

    def _on_entra_roles_loaded(self, roles: list[azure.EntraEligibleRole]) -> None:
        self._entra_loaded = True
        self._entra_loading = False
        self.all_roles = roles
        self.query_one("#entra-spinner").display = False
        if not roles:
            self.query_one("#entra-loading-label", Label).update("[dim]No eligible Entra roles found.[/dim]")
            return
        self.query_one("#entra-loading-area").display = False
        self.query_one("#entra-split").display = True
        self._rebuild_entra_list("")
        if self._initial_tab == "tab-entra":
            self.query_one("#entra-role-list").focus()
        self._update_entra_status()

    def _on_entra_error(self, msg: str) -> None:
        self._entra_loading = False
        self.query_one("#entra-spinner").display = False
        if azure.is_auth_error(msg):
            body = (
                "[bold red]Azure session expired.[/bold red]\n\n"
                "Run [bold]az login[/bold] in your terminal, then restart fomo."
            )
        else:
            wrapped = "\n".join(
                line if len(line) <= 80 else "\n".join(
                    msg[i:i+80] for i in range(0, len(line), 80)
                )
                for line in msg.splitlines()
            )
            body = f"[bold red]Error:[/bold red]\n\n{wrapped}"
        self.query_one("#entra-loading-label", Label).update(body)

    # ------------------------------------------------------------------
    # Entra — filter helpers
    # ------------------------------------------------------------------

    def _rebuild_entra_list(self, query: str) -> None:
        sl = self.query_one("#entra-role-list", SelectionList)
        q = query.strip().lower()
        self._entra_rebuilding = True
        sl.clear_options()
        self._visible_indices = set()
        self._option_values = []
        for idx, role in enumerate(self.all_roles):
            if q and q not in role.role_name.lower():
                continue
            active_tag = " [bold green](active)[/bold green]" if role.is_active else ""
            expiry_tag = f" [dim]- {azure.format_expiry(role.expiry)}[/dim]"
            label = f"{role.role_name}{active_tag}{expiry_tag}"
            sl.add_option(Selection(label, idx, idx in self._selected))
            self._visible_indices.add(idx)
            self._option_values.append(idx)
        self._entra_rebuilding = False
        if self._visible_indices:
            self._update_entra_detail(self.all_roles[min(self._visible_indices)])
        else:
            self.query_one("#entra-detail", Label).update("[dim]No roles match filter.[/dim]")

    @on(Input.Changed, "#entra-filter")
    def on_entra_filter_changed(self, event: Input.Changed) -> None:
        self._rebuild_entra_list(event.value)

    @on(Input.Submitted, "#entra-filter")
    def on_entra_filter_submitted(self, event: Input.Submitted) -> None:  # noqa: ARG002
        self._select_all_entra_visible()
        self.query_one("#entra-role-list").focus()

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
        if n == 0:
            lbl.update("[dim]No roles selected[/dim]")
        else:
            lbl.update(f"[bold]{n}[/bold] role(s) selected")

    def _update_entra_detail(self, role: azure.EntraEligibleRole) -> None:
        detail_lbl = self.query_one("#entra-detail", Label)
        tier_info = tiering.get_entra_tier(role.role_definition_id)
        expiry = azure.format_expiry(role.expiry)
        active_tag = "\n[bold #27ae60]● Currently active[/bold #27ae60]" if role.is_active else ""

        if not tier_info:
            detail_lbl.update(
                f"[bold]{role.role_name}[/bold]{active_tag}\n"
                f"Expires: [dim]{expiry}[/dim]\n\n"
                f"[dim]No tiering data available for this role.[/dim]"
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
            f"[bold]{role.role_name}[/bold]{active_tag}",
            f"Expires: [dim]{expiry}[/dim]",
        ]
        if attack and attack != "-":
            parts.extend(["", f"[bold]{path_header}:[/bold]", attack])
        detail_lbl.update("\n".join(parts))

    def _select_all_entra_visible(self) -> None:
        self._selected.update(self._visible_indices)
        sl = self.query_one("#entra-role-list", SelectionList)
        self._entra_rebuilding = True
        sl.select_all()
        self._entra_rebuilding = False
        self._update_entra_status()

    # ------------------------------------------------------------------
    # Actions — tab-aware
    # ------------------------------------------------------------------

    def action_focus_filter(self) -> None:
        if self._active_tab() == "tab-entra":
            self.query_one("#entra-filter").focus()
        else:
            self.query_one("#filter").focus()

    def action_focus_list(self) -> None:
        if self._active_tab() == "tab-entra":
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
            self.query_one("#sub-list", SelectionList).deselect_all()

    def action_proceed(self) -> None:
        if isinstance(self.focused, Tabs):
            self.action_focus_filter()
            return
        if self._active_tab() == "tab-entra":
            if self.focused is self.query_one("#entra-filter"):
                self.query_one("#entra-role-list").focus()
                return
            selected_roles = [self.all_roles[i] for i in sorted(self._selected)]
            if not selected_roles:
                self.notify("Select at least one role.", severity="warning")
                return
            high_risk = [
                t for r in selected_roles
                if (t := tiering.get_entra_tier(r.role_definition_id)) is not None
                and t["tier"] <= 1
            ]
            if high_risk:
                summary = tiering.high_risk_summary(high_risk)
                self.notify(
                    f"Blast-radius warning: {len(high_risk)} high-risk role(s) selected\n{summary}",
                    severity="warning",
                    timeout=15,
                )
            from fomo.screens.entra_screen import EntraActivationScreen
            self.app.push_screen(EntraActivationScreen(selected_roles))
        else:
            if self.focused is self.query_one("#filter"):
                self.action_focus_list()
                return
            sl = self.query_one("#sub-list", SelectionList)
            selected_ids: list[str] = list(sl.selected)
            if not selected_ids:
                self.notify("Select at least one subscription.", severity="warning")
                return
            from fomo.screens.roles_screen import RolesScreen
            self.app.push_screen(RolesScreen(selected_ids))

    def action_select_focused(self) -> None:
        list_id = "#entra-role-list" if self._active_tab() == "tab-entra" else "#sub-list"
        sub_list = self.query_one(list_id, SelectionList)
        if self.focused is sub_list:
            sub_list.action_select()
        else:
            focused = self.focused
            if focused is not None and hasattr(focused, "insert_text_at_cursor"):
                focused.insert_text_at_cursor("x")

    def action_open_assignments(self) -> None:
        from fomo.screens.assignments_screen import AssignmentsScreen
        self.app.push_screen(AssignmentsScreen())

    def action_quit_app(self) -> None:
        self.app.exit()

    # ------------------------------------------------------------------
    # Vim-style navigation (focus-based, works for both tabs)
    # ------------------------------------------------------------------

    def action_arrow_down(self) -> None:
        self.focus_next()

    def action_arrow_up(self) -> None:
        self.focus_previous()

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
