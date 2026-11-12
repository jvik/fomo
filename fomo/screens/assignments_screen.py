"""Assignments screen — view current Azure ARM and Entra role assignments."""

from __future__ import annotations

import threading

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.content import Content
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label, LoadingIndicator, TabbedContent, TabPane
from textual.widgets.data_table import ColumnKey

from fomo import azure
from fomo.screens._common import VimNavMixin, device_code_markup, safe_markup, wrap_error_lines

_COL_NAMES = ("Role", "Scope", "Expiry", "Type")

_SESSION_EXPIRED = (
    "[bold red]Azure session expired.[/bold red]\n\n"
    "Run [bold]az login[/bold] in another terminal, then press [bold]r[/bold] to retry."
)


class AssignmentsScreen(VimNavMixin, Screen):
    """Show all currently active Azure ARM and Entra role assignments."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("q", "app.pop_screen", "Back", show=False),
        Binding("j", "vim_down", "↓", show=False),
        Binding("k", "vim_up", "↑", show=False),
        Binding("g", "vim_top", "Top", show=False),
        Binding("G", "vim_bottom", "Bottom", show=False),
        Binding("1", "sort_col(0)", "Sort: Role", show=True),
        Binding("2", "sort_col(1)", "Sort: Scope", show=True),
        Binding("3", "sort_col(2)", "Sort: Expiry", show=True),
        Binding("4", "sort_col(3)", "Sort: Type", show=True),
        Binding("r", "reload", "Reload", show=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._stop_event = threading.Event()
        self._sort_col: dict[str, ColumnKey | str] = {}  # table id → last sorted column key
        self._sort_asc: dict[str, bool] = {}  # table id → ascending?
        self._azure_loading = False
        self._entra_loading = False
        self._entra_failed = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with TabbedContent(id="assignment-tabs"):
            with TabPane("Azure", id="tab-azure"):
                yield Label("Loading Azure subscriptions…", id="azure-loading")
                yield LoadingIndicator(id="azure-spinner")
                yield DataTable(id="azure-table", show_cursor=True)
            with TabPane("Entra", id="tab-entra"):
                yield Label("Loading Entra assignments…", id="entra-loading")
                yield LoadingIndicator(id="entra-spinner")
                yield DataTable(id="entra-table", show_cursor=True)
        yield Footer()

    def on_mount(self) -> None:
        azure_table = self.query_one("#azure-table", DataTable)
        azure_table.add_columns("Role", "Scope", "Expiry", "Type")
        azure_table.display = False

        entra_table = self.query_one("#entra-table", DataTable)
        entra_table.add_columns("Role", "Scope", "Expiry", "Type")
        entra_table.display = False

        self._load_azure()
        self._load_entra()

    def on_unmount(self) -> None:
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Reload (r)
    # ------------------------------------------------------------------

    def action_reload(self) -> None:
        """Load both tabs again, e.g. after ``az login`` or a new Graph sign-in.

        A tab whose load is still running (such as a device-code sign-in) is
        left alone.
        """
        if not self._azure_loading:
            self._reset_tab("azure", "Loading Azure assignments…")
            self._load_azure()
        if not self._entra_loading:
            if self._entra_failed:
                # Otherwise the retry reuses the access token that just failed,
                # even after the user deleted graph_token.json to sign in again.
                azure.forget_graph_access_token()
            self._reset_tab("entra", "Loading Entra assignments…")
            self._load_entra()

    def _reset_tab(self, prefix: str, loading_text: str) -> None:
        """Empty one tab's table and show its spinner again."""
        table = self.query_one(f"#{prefix}-table", DataTable)
        table.clear()
        table.display = False
        tid = table.id or ""
        self._sort_col.pop(tid, None)
        self._sort_asc.pop(tid, None)
        self._refresh_headers(table)
        self.query_one(f"#{prefix}-spinner").display = True
        self.query_one(f"#{prefix}-loading", Label).update(loading_text)

    # ------------------------------------------------------------------
    # Azure ARM loading
    # ------------------------------------------------------------------

    def _load_azure(self) -> None:
        self._azure_loading = True
        self._fetch_azure()

    @work(thread=True)
    def _fetch_azure(self) -> None:
        try:
            assignments = self.app.backend.list_active_arm_assignments()  # type: ignore[attr-defined]
        except Exception as exc:
            self.app.call_from_thread(self._on_azure_error, str(exc))
            return
        self.app.call_from_thread(self._on_azure_done, assignments)

    def _on_azure_done(self, assignments: list[azure.ActiveAssignment]) -> None:
        self._azure_loading = False
        self.query_one("#azure-spinner").display = False
        label = self.query_one("#azure-loading", Label)
        if not assignments:
            label.update("[dim]No active Azure assignments found.[/dim]")
            return
        label.update(f"Azure assignments  ({len(assignments)} found)")
        table = self.query_one("#azure-table", DataTable)
        for a in sorted(assignments, key=lambda x: (x.role_name, x.scope_display_name)):
            table.add_row(
                Text(a.role_name),
                Text(a.scope_display_name),
                Text(azure.format_expiry(a.expiry)),
                Text(a.assignment_type),
            )
        table.display = True
        table.focus()

    def _on_azure_error(self, msg: str) -> None:
        self._azure_loading = False
        self.query_one("#azure-spinner").display = False
        body: str | Content
        if azure.is_auth_error(msg):
            body = _SESSION_EXPIRED
        else:
            body = safe_markup("[bold red]Error:[/bold red] $msg", msg=msg)
        self.query_one("#azure-loading", Label).update(body)

    # ------------------------------------------------------------------
    # Entra (Graph) loading
    # ------------------------------------------------------------------

    def _load_entra(self) -> None:
        self._entra_loading = True
        self._fetch_entra()

    @work(thread=True)
    def _fetch_entra(self) -> None:
        def _on_device_code(message: str) -> None:
            url, _, code = message.partition("\n")

            def _update() -> None:
                self.query_one("#entra-loading", Label).update(device_code_markup(url, code))

            self.app.call_from_thread(_update)

        try:
            assignments = self.app.backend.list_active_entra_assignments(  # type: ignore[attr-defined]
                on_device_code=_on_device_code,
                stop_event=self._stop_event,
            )
            self.app.call_from_thread(self._on_entra_done, assignments)
        except Exception as exc:
            self.app.call_from_thread(self._on_entra_error, str(exc))

    def _on_entra_done(self, assignments: list[azure.ActiveEntraAssignment]) -> None:
        self._entra_loading = False
        self._entra_failed = False
        self.query_one("#entra-spinner").display = False
        label = self.query_one("#entra-loading", Label)
        if not assignments:
            label.update("[dim]No active Entra assignments found.[/dim]")
            return
        label.update(f"Entra assignments  ({len(assignments)} found)")
        table = self.query_one("#entra-table", DataTable)
        for a in sorted(assignments, key=lambda x: x.role_name):
            table.add_row(
                Text(a.role_name),
                Text(a.directory_scope_id),
                Text(azure.format_expiry(a.expiry)),
                Text(a.assignment_type),
            )
        table.display = True

    def _on_entra_error(self, msg: str) -> None:
        self._entra_loading = False
        self._entra_failed = True
        self.query_one("#entra-spinner").display = False
        body: str | Content
        if azure.is_auth_error(msg):
            body = _SESSION_EXPIRED
        elif azure.is_scope_error(msg):
            body = (
                "[bold red]Missing Graph permissions.[/bold red]\n\n"
                "Sign in to Graph again: delete [bold]~/.cache/fomo/graph_token.json[/bold] "
                "and press [bold]r[/bold] to retry."
            )
        else:
            body = safe_markup("[bold red]Error:[/bold red]\n\n$error", error=wrap_error_lines(msg))
        self.query_one("#entra-loading", Label).update(body)

    # ------------------------------------------------------------------
    # Column-header sorting (mouse) and key-based sorting
    # ------------------------------------------------------------------

    def _sort_table(self, table: DataTable, col: ColumnKey | str) -> None:
        tid = table.id or ""
        if self._sort_col.get(tid) == col:
            self._sort_asc[tid] = not self._sort_asc.get(tid, True)
        else:
            self._sort_col[tid] = col
            self._sort_asc[tid] = True
        # Cells are rich Text objects, which don't order; sort by their plain text.
        table.sort(col, key=str, reverse=not self._sort_asc[tid])
        self._refresh_headers(table)

    def _refresh_headers(self, table: DataTable) -> None:
        tid = table.id or ""
        sort_col = self._sort_col.get(tid)
        asc = self._sort_asc.get(tid, True)
        arrow = " ↑" if asc else " ↓"
        for key, name in zip(table.columns, _COL_NAMES, strict=False):
            label = Text(name + arrow) if key == sort_col else Text(name)
            table.columns[key].label = label
        table.refresh()

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        self._sort_table(event.data_table, event.column_key)

    def action_sort_col(self, col_index: int) -> None:
        focused = self.focused
        if not isinstance(focused, DataTable):
            return
        keys = list(focused.columns.keys())
        if col_index < len(keys):
            self._sort_table(focused, keys[col_index])
