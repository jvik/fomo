"""Scope screen — pick which Azure subscriptions to load PIM roles from."""

from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Label, LoadingIndicator, SelectionList

from fzf_pim import azure


class ScopeScreen(Screen):
    """First screen: select Azure subscriptions."""

    BINDINGS = [
        Binding("enter", "proceed", "Load Roles", show=True, priority=True),
        Binding("slash", "focus_filter", "Filter", show=True),
        Binding("tab", "focus_list", "Focus list", show=False),
        Binding("escape", "focus_list", "Focus list", show=False),
        Binding("a", "select_all", "All", show=True),
        Binding("ctrl+a", "select_all_visible", "Select all", show=True),
        Binding("n", "select_none", "None", show=True),
        Binding("q", "quit_app", "Quit", show=True),
        Binding("j", "vim_down", "↓", show=False),
        Binding("k", "vim_up", "↑", show=False),
        Binding("g", "vim_top", "Top", show=False),
        Binding("G", "vim_bottom", "Bottom", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._all_subs: list[azure.Subscription] = []
        self._visible_ids: set[str] = set()
        self._rebuilding = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="main"):
            yield Label("Loading Azure subscriptions…", id="loading-label")
            yield LoadingIndicator(id="spinner")
            yield Input(placeholder="Filter subscriptions… (type to search)", id="filter")
            yield SelectionList(id="sub-list")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#sub-list").display = False
        self.query_one("#filter").display = False
        self._load_subs()

    @work(thread=True)
    def _load_subs(self) -> None:
        try:
            subs = azure.list_subscriptions()
            self.app.call_from_thread(self._show_subs, subs)
        except Exception as exc:
            self.app.call_from_thread(self._show_error, str(exc))

    def _show_subs(self, subs: list[azure.Subscription]) -> None:
        self.query_one("#spinner").display = False
        self.query_one("#loading-label", Label).update(
            f"Select subscriptions  ({len(subs)} found)"
            "   [dim]j/k[/dim]=nav  [dim]a[/dim]=all  [dim]n[/dim]=none  [dim]Enter[/dim]=proceed"
        )
        self._all_subs = subs
        self.query_one("#filter").display = True
        self._rebuild_list("")
        sl = self.query_one("#sub-list", SelectionList)
        sl.display = True
        sl.focus()

    def _show_error(self, msg: str) -> None:
        self.query_one("#spinner").display = False
        if azure.is_auth_error(msg):
            body = (
                "[bold red]Azure session expired.[/bold red]\n\n"
                "Run [bold]az login[/bold] in your terminal, then restart fzf-pim."
            )
        else:
            body = (
                f"[bold red]Error:[/bold red] {msg}\n\n"
                "Is [bold]az[/bold] installed and are you logged in?  Run: [bold]az login[/bold]"
            )
        self.query_one("#loading-label", Label).update(body)

    # ------------------------------------------------------------------
    # Filter helpers
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

    @on(Input.Changed, "#filter")
    def on_filter_changed(self, event: Input.Changed) -> None:
        self._rebuild_list(event.value)

    @on(Input.Submitted, "#filter")
    def on_filter_submitted(self, event: Input.Submitted) -> None:  # noqa: ARG002
        """Select all visible items and move focus to the list."""
        self.action_select_all_visible()
        self.query_one("#sub-list").focus()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_focus_filter(self) -> None:
        self.query_one("#filter").focus()

    def action_focus_list(self) -> None:
        self.query_one("#sub-list").focus()

    def action_select_all(self) -> None:
        self.query_one(SelectionList).select_all()

    def action_select_all_visible(self) -> None:
        """Select all currently visible (filtered) subscriptions."""
        sl = self.query_one("#sub-list", SelectionList)
        self._rebuilding = True
        sl.select_all()
        self._rebuilding = False

    def action_select_none(self) -> None:
        self.query_one(SelectionList).deselect_all()

    def action_proceed(self) -> None:
        sl = self.query_one(SelectionList)
        selected_ids: list[str] = list(sl.selected)
        if not selected_ids:
            self.notify("Select at least one subscription.", severity="warning")
            return
        from fzf_pim.screens.roles_screen import RolesScreen
        self.app.push_screen(RolesScreen(selected_ids))

    def action_quit_app(self) -> None:
        self.app.exit()

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
