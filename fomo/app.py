"""Root Textual application for fomo."""

from __future__ import annotations

import os
import subprocess

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import Button, Label
from textual.worker import get_current_worker

from fomo import azure
from fomo.screens.scope_screen import ScopeScreen

FOMO_DARK = Theme(
    name="fomo-dark",
    primary="#0078D4",
    secondary="#50E6FF",
    background="#141414",
    surface="#1c1c1c",
    panel="#2a2a2a",
    boost="#222222",
    success="#4ebf71",
    warning="#ffa62b",
    error="#e05450",
    dark=True,
    variables={"block-cursor-foreground": "#ffffff"},
)

FOMO_LIGHT = Theme(
    name="fomo-light",
    primary="#0078D4",
    secondary="#004578",
    background="#f0f2f5",
    surface="#ffffff",
    panel="#d4d8de",
    boost="#f8f9fa",
    success="#2e7d32",
    warning="#e65100",
    error="#c62828",
    dark=False,
    variables={"block-cursor-foreground": "#ffffff"},
)


class AuthErrorModal(ModalScreen):
    """Persistent modal shown when the az CLI session has expired."""

    BINDINGS = [
        ("escape", "dismiss", "Dismiss"),
        ("q", "quit_app", "Quit"),
        ("ctrl+c", "quit_app", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="auth-error-dialog"):
            yield Label("Azure session expired", id="auth-error-title")
            yield Label(
                "Run [bold]az login[/bold] in your terminal, then restart fomo.",
                id="auth-error-body",
            )
            with Horizontal(id="auth-error-buttons"):
                yield Button("Dismiss", variant="default", id="auth-error-ok")
                yield Button("Quit", variant="error", id="auth-error-quit")

    def on_mount(self) -> None:
        self.query_one("#auth-error-ok").focus()

    def on_key(self, event) -> None:
        if event.key in ("left", "right"):
            focused = self.focused
            if focused and focused.id == "auth-error-ok":
                self.query_one("#auth-error-quit").focus()
            else:
                self.query_one("#auth-error-ok").focus()
            event.stop()

    @on(Button.Pressed, "#auth-error-ok")
    def _ok(self) -> None:
        self.dismiss()

    def action_quit_app(self) -> None:
        self.app.exit()

    @on(Button.Pressed, "#auth-error-quit")
    def _quit(self) -> None:
        self.app.exit()


def _system_is_dark() -> bool:
    """Return True if the system prefers a dark colour scheme."""
    # Freedesktop portal — most reliable cross-DE method
    # Returns: 0 = no preference, 1 = dark, 2 = light
    try:
        result = subprocess.run(
            [
                "dbus-send", "--session",
                "--dest=org.freedesktop.portal.Desktop",
                "--print-reply",
                "/org/freedesktop/portal/desktop",
                "org.freedesktop.portal.Settings.Read",
                "string:org.freedesktop.appearance",
                "string:color-scheme",
            ],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if result.returncode == 0:
            # Output contains "uint32 <value>" — extract last integer
            for token in reversed(result.stdout.split()):
                if token.isdigit():
                    scheme = int(token)
                    if scheme == 1:
                        return True
                    if scheme == 2:
                        return False
                    break  # 0 = no preference, fall through
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # GNOME / colour-scheme setting
    try:
        result = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if result.returncode == 0:
            val = result.stdout.strip().strip("'\"")
            if val == "prefer-dark":
                return True
            if val == "prefer-light":
                return False
            # 'default' means no preference — fall through to gtk-theme
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # GTK theme name (e.g. "Adwaita-dark", "Arc-Dark")
    try:
        result = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if result.returncode == 0 and result.stdout.strip():
            return "dark" in result.stdout.lower()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # KDE plasma
    try:
        result = subprocess.run(
            ["kreadconfig5", "--group", "General", "--key", "ColorScheme"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if result.returncode == 0 and result.stdout.strip():
            return "dark" in result.stdout.lower()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # GTK_THEME env var (e.g. "Adwaita:dark")
    gtk_theme = os.environ.get("GTK_THEME", "")
    if gtk_theme:
        return "dark" in gtk_theme.lower()

    # Default: dark
    return True


class PimApp(App):
    """Azure PIM role activation TUI."""

    CSS_PATH = "app.tcss"
    TITLE = "fomo  ·  Azure PIM"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [("ctrl+c", "quit", "Quit")]

    def __init__(self, dry_run: bool = False, entra: bool = False, demo_mode: bool = False) -> None:
        super().__init__()
        self.register_theme(FOMO_DARK)
        self.register_theme(FOMO_LIGHT)
        self.dry_run = dry_run
        self.entra = entra
        self.demo_mode = demo_mode
        self.theme = "fomo-dark" if _system_is_dark() else "fomo-light"
        self._color_scheme_proc: subprocess.Popen | None = None

    def on_mount(self) -> None:
        if self.demo_mode:
            self.title = "fomo  ·  Azure PIM  [DEMO]"
        elif self.dry_run:
            self.title = "fomo  ·  Azure PIM  [DRY RUN]"
        initial_tab = "tab-entra" if self.entra else "tab-azure"
        self.push_screen(ScopeScreen(initial_tab=initial_tab))
        self._watch_color_scheme()
        self.run_worker(self._load_account_info, thread=True)

    def _load_account_info(self) -> None:
        if self.demo_mode:
            from fomo import demo as demo_data
            base = "fomo  ·  Azure PIM  [DEMO]"
            self.call_from_thread(
                setattr, self, "title",
                f"{base}  ·  {demo_data.DEMO_USER}  ·  {demo_data.DEMO_TENANT}",
            )
            return
        try:
            azure.check_auth()
            user, tenant = azure.get_account_info()
            base = "fomo  ·  Azure PIM  [DRY RUN]" if self.dry_run else "fomo  ·  Azure PIM"
            self.call_from_thread(setattr, self, "title", f"{base}  ·  {user}  ·  {tenant}")
        except Exception as exc:
            if azure.is_auth_error(str(exc)):
                self.call_from_thread(self.push_screen, AuthErrorModal())

    def on_unmount(self) -> None:
        if self._color_scheme_proc is not None:
            self._color_scheme_proc.terminate()

    def _watch_color_scheme(self) -> None:
        """Start background worker that listens for OS dark/light changes."""
        try:
            subprocess.run(["dbus-monitor", "--version"], capture_output=True, timeout=1)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return
        self.run_worker(self._dbus_color_scheme_watcher, thread=True)

    def _dbus_color_scheme_watcher(self) -> None:
        """Thread worker: tail dbus-monitor and update theme on changes."""
        worker = get_current_worker()
        proc = subprocess.Popen(
            [
                "dbus-monitor", "--session",
                "type='signal',interface='org.freedesktop.portal.Settings',"
                "member='SettingChanged'",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self._color_scheme_proc = proc
        namespace = None
        key = None
        try:
            for line in proc.stdout:
                if worker.is_cancelled:
                    break
                line = line.strip()
                if "org.freedesktop.appearance" in line:
                    namespace = "org.freedesktop.appearance"
                elif namespace and "color-scheme" in line:
                    key = "color-scheme"
                elif namespace == "org.freedesktop.appearance" and key == "color-scheme":
                    # Next uint32 line is the new value
                    parts = line.split()
                    if parts and parts[0] == "uint32" and parts[1].isdigit():
                        scheme = int(parts[1])
                        if scheme == 1:
                            self.call_from_thread(setattr, self, "theme", "fomo-dark")
                        elif scheme == 2:
                            self.call_from_thread(setattr, self, "theme", "fomo-light")
                        namespace = None
                        key = None
                else:
                    namespace = None
                    key = None
        finally:
            self._color_scheme_proc = None
            proc.wait()
