"""Assignments screen — view current Azure ARM and Entra role assignments."""

from __future__ import annotations

import logging
import threading

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label, LoadingIndicator, TabbedContent, TabPane

from fzf_pim import azure

log = logging.getLogger(__name__)


class AssignmentsScreen(Screen):
    """Show all currently active Azure ARM and Entra role assignments."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("q", "app.pop_screen", "Back", show=False),
        Binding("j", "vim_down", "↓", show=False),
        Binding("k", "vim_up", "↑", show=False),
        Binding("g", "vim_top", "Top", show=False),
        Binding("G", "vim_bottom", "Bottom", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._stop_event = threading.Event()

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
    # Azure ARM loading
    # ------------------------------------------------------------------

    @work(thread=True)
    def _load_azure(self) -> None:
        try:
            assignments = azure.list_active_arm_assignments()
        except Exception as exc:
            self.app.call_from_thread(self._on_azure_error, str(exc))
            return
        self.app.call_from_thread(self._on_azure_done, assignments)

    def _on_azure_done(self, assignments: list[azure.ActiveAssignment]) -> None:
        self.query_one("#azure-spinner").display = False
        label = self.query_one("#azure-loading", Label)
        if not assignments:
            label.update("[dim]No active Azure assignments found.[/dim]")
            return
        label.update(f"Azure assignments  ({len(assignments)} found)")
        table = self.query_one("#azure-table", DataTable)
        for a in sorted(assignments, key=lambda x: (x.role_name, x.scope_display_name)):
            table.add_row(
                a.role_name,
                a.scope_display_name,
                azure.format_expiry(a.expiry),
                a.assignment_type,
            )
        table.display = True
        table.focus()

    def _on_azure_error(self, msg: str) -> None:
        self.query_one("#azure-spinner").display = False
        if azure.is_auth_error(msg):
            body = (
                "[bold red]Azure session expired.[/bold red]\n\n"
                "Run [bold]az login[/bold] in your terminal, then restart fzf-pim."
            )
        else:
            body = f"[bold red]Error:[/bold red] {msg}"
        self.query_one("#azure-loading", Label).update(body)

    # ------------------------------------------------------------------
    # Entra (Graph) loading
    # ------------------------------------------------------------------

    @work(thread=True)
    def _load_entra(self) -> None:
        def _on_device_code(message: str) -> None:
            url, _, code = message.partition("\n")

            def _update() -> None:
                self.query_one("#entra-loading", Label).update(
                    "[bold]Sign in to Microsoft Graph[/bold]\n\n"
                    f"[dim]1.[/dim] Open:  [link]{url}[/link]\n"
                    f"[dim]2.[/dim] Enter code:  [bold]{code}[/bold]\n\n"
                    "[dim]Waiting for authentication…[/dim]"
                )

            self.app.call_from_thread(_update)

        try:
            assignments = azure.list_active_entra_assignments(
                on_device_code=_on_device_code,
                stop_event=self._stop_event,
            )
            self.app.call_from_thread(self._on_entra_done, assignments)
        except Exception as exc:
            self.app.call_from_thread(self._on_entra_error, str(exc))

    def _on_entra_done(self, assignments: list[azure.ActiveEntraAssignment]) -> None:
        self.query_one("#entra-spinner").display = False
        label = self.query_one("#entra-loading", Label)
        if not assignments:
            label.update("[dim]No active Entra assignments found.[/dim]")
            return
        label.update(f"Entra assignments  ({len(assignments)} found)")
        table = self.query_one("#entra-table", DataTable)
        for a in sorted(assignments, key=lambda x: x.role_name):
            table.add_row(
                a.role_name,
                a.directory_scope_id,
                azure.format_expiry(a.expiry),
                a.assignment_type,
            )
        table.display = True

    def _on_entra_error(self, msg: str) -> None:
        self.query_one("#entra-spinner").display = False
        if azure.is_auth_error(msg):
            body = (
                "[bold red]Azure session expired.[/bold red]\n\n"
                "Run [bold]az login[/bold] in your terminal, then restart fzf-pim."
            )
        elif azure.is_scope_error(msg):
            body = (
                "[bold red]Missing Graph permissions.[/bold red]\n\n"
                "Re-run [bold]fzf-pim --entra[/bold] to re-authorise."
            )
        else:
            wrapped = "\n".join(
                line if len(line) <= 80 else "\n".join(
                    line[i : i + 80] for i in range(0, len(line), 80)
                )
                for line in msg.splitlines()
            )
            body = f"[bold red]Error:[/bold red]\n\n{wrapped}"
        self.query_one("#entra-loading", Label).update(body)

    # ------------------------------------------------------------------
    # vim-style navigation
    # ------------------------------------------------------------------

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
