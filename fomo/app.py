"""Root Textual application for fomo."""

from __future__ import annotations

import os
import subprocess

from textual.app import App
from textual.worker import get_current_worker

from fomo import azure
from fomo.screens.scope_screen import ScopeScreen


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

    def __init__(self, dry_run: bool = False, entra: bool = False) -> None:
        super().__init__()
        self.dry_run = dry_run
        self.entra = entra
        self.theme = "textual-dark" if _system_is_dark() else "textual-light"
        self._color_scheme_proc: subprocess.Popen | None = None

    def on_mount(self) -> None:
        if self.dry_run:
            self.title = "fomo  ·  Azure PIM  [DRY RUN]"
        if self.entra:
            from fomo.screens.entra_screen import EntraRolesScreen
            self.push_screen(EntraRolesScreen())
        else:
            self.push_screen(ScopeScreen())
        self._watch_color_scheme()
        self.run_worker(self._load_account_info, thread=True)

    def _load_account_info(self) -> None:
        try:
            user, tenant = azure.get_account_info()
            base = "fomo  ·  Azure PIM  [DRY RUN]" if self.dry_run else "fomo  ·  Azure PIM"
            self.call_from_thread(setattr, self, "title", f"{base}  ·  {user}  ·  {tenant}")
        except Exception:
            pass

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
                            self.call_from_thread(setattr, self, "theme", "textual-dark")
                        elif scheme == 2:
                            self.call_from_thread(setattr, self, "theme", "textual-light")
                        namespace = None
                        key = None
                else:
                    namespace = None
                    key = None
        finally:
            self._color_scheme_proc = None
            proc.wait()
