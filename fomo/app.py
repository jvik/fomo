"""Root Textual application for fomo."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable

from textual import events, on
from textual.actions import SkipAction
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import Button, Label
from textual.worker import get_current_worker

from fomo import azure
from fomo.backend import Backend, make_backend
from fomo.screens._common import safe_markup
from fomo.screens.keys_screen import KeysScreen, binding_rows, screen_key_rows
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


_RELOGIN_BODY = "Run [bold]az login[/bold] in another terminal, then press Retry."

# Title and body markup for each kind of error that opens the dialog.
_AUTH_ERROR_TEXT: dict[str, tuple[str, str]] = {
    "expired": ("Azure session expired", _RELOGIN_BODY),
    "not_logged_in": ("Not logged in to Azure", _RELOGIN_BODY),
    "mfa": (
        "MFA or compliant device required",
        "Your tenant requires MFA or a compliant device for this request. "
        "Run [bold]az login --scope https://management.azure.com/.default[/bold] "
        "(or [bold]az login --tenant <id>[/bold]), then Retry.",
    ),
}

# The raw error line is cut to this many characters so that the dialog,
# wrapped at its 58-column text width, always fits an 80x24 terminal.
_MESSAGE_LIMIT = 200


def _first_line(message: str, limit: int = _MESSAGE_LIMIT) -> str:
    """The first non-blank line of *message*, cut to *limit* characters."""
    line = next((stripped for raw in message.splitlines() if (stripped := raw.strip())), "")
    return line if len(line) <= limit else line[: limit - 1] + "…"


class AuthErrorModal(ModalScreen[bool]):
    """Dialog shown when the az CLI session can't be used.

    *kind* (from ``azure.classify_auth_error``) picks the title and the fix to
    suggest; the first line of the raw *message* is shown underneath.  The
    screen dismisses with ``True`` for Retry and ``False`` for Dismiss; Quit
    exits the app.  Open it with ``PimApp.show_auth_error``, which runs the
    retry callbacks.
    """

    BINDINGS = [
        ("escape", "close", "Dismiss"),
        ("r", "retry", "Retry"),
        ("q", "quit_app", "Quit"),
        ("ctrl+c", "quit_app", "Quit"),
    ]

    _BUTTON_IDS = ("auth-error-retry", "auth-error-ok", "auth-error-quit")

    def __init__(self, kind: azure.AuthErrorKind, message: str) -> None:
        super().__init__()
        self.kind = kind
        self.message = message
        #: Called, in order, when the user picks Retry.
        self.retry_callbacks: list[Callable[[], None]] = []

    def compose(self) -> ComposeResult:
        title, body = _AUTH_ERROR_TEXT.get(self.kind, _AUTH_ERROR_TEXT["expired"])
        with Vertical(id="auth-error-dialog"):
            yield Label(title, id="auth-error-title")
            yield Label(body, id="auth-error-body")
            line = _first_line(self.message)
            if line:
                yield Label(safe_markup("[dim]$line[/dim]", line=line), id="auth-error-message")
            with Horizontal(id="auth-error-buttons"):
                yield Button("Retry", variant="primary", id="auth-error-retry")
                yield Button("Dismiss", variant="default", id="auth-error-ok")
                yield Button("Quit", variant="error", id="auth-error-quit")

    def on_mount(self) -> None:
        self.query_one("#auth-error-retry").focus()

    def on_key(self, event: events.Key) -> None:
        if event.key in ("left", "right"):
            ids = self._BUTTON_IDS
            focused_id = self.focused.id if self.focused is not None else None
            current = ids.index(focused_id) if focused_id in ids else 0
            step = 1 if event.key == "right" else -1
            self.query_one(f"#{ids[(current + step) % len(ids)]}").focus()
            event.stop()

    @on(Button.Pressed, "#auth-error-retry")
    def action_retry(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#auth-error-ok")
    def action_close(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#auth-error-quit")
    def action_quit_app(self) -> None:
        self.app.exit()


# (namespace, key) of the portal SettingChanged signal seen so far.
_ColorSchemeState = tuple[str | None, str | None]
_COLOR_SCHEME_IDLE: _ColorSchemeState = (None, None)


def _parse_color_scheme_line(state: _ColorSchemeState, line: str) -> tuple[_ColorSchemeState, str | None]:
    """Feed one line of ``dbus-monitor`` output to the colour-scheme state machine.

    The watcher waits for an ``org.freedesktop.appearance`` line, then a
    ``color-scheme`` line, then a ``uint32 <n>`` line with the new value
    (1 = dark, 2 = light).  Returns the next state and the theme to switch to,
    or ``None``.  Malformed value lines are ignored.
    """
    namespace, key = state
    line = line.strip()
    if "org.freedesktop.appearance" in line:
        return ("org.freedesktop.appearance", key), None
    if namespace and "color-scheme" in line:
        return (namespace, "color-scheme"), None
    if namespace == "org.freedesktop.appearance" and key == "color-scheme":
        # Next uint32 line is the new value
        parts = line.split()
        if len(parts) > 1 and parts[0] == "uint32" and parts[1].isdecimal():
            scheme = int(parts[1])
            if scheme == 1:
                return _COLOR_SCHEME_IDLE, "fomo-dark"
            if scheme == 2:
                return _COLOR_SCHEME_IDLE, "fomo-light"
            return _COLOR_SCHEME_IDLE, None
        return state, None
    return _COLOR_SCHEME_IDLE, None


_THEMES = {"dark": "fomo-dark", "light": "fomo-light"}


def _theme_override() -> str | None:
    """The theme ``FOMO_THEME`` asks for ("dark" or "light"), or None to follow the system."""
    return _THEMES.get(os.environ.get("FOMO_THEME", "").strip().lower())


# How long each colour-scheme probe may take.  Detection runs in a worker
# after startup, so even a hanging desktop service never delays the app.
_PROBE_TIMEOUT = 0.3


def _probe(args: list[str]) -> subprocess.CompletedProcess[str] | None:
    """Run a colour-scheme probe; None if it isn't installed, can't start or times out."""
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=_PROBE_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None


def _system_is_dark() -> bool:
    """Return True if the system prefers a dark colour scheme (also when it can't tell).

    Asks one source after another and stops at the first decisive answer.
    Each probe can take up to 0.3 s, so call this from a worker thread.
    """
    if sys.platform == "darwin":
        # "Dark" in dark mode; in light mode the key doesn't exist (exit status 1).
        result = _probe(["defaults", "read", "-g", "AppleInterfaceStyle"])
        if result is None:
            return True
        return result.returncode == 0 and "dark" in result.stdout.lower()

    # Freedesktop portal — most reliable cross-DE method
    # Returns: 0 = no preference, 1 = dark, 2 = light
    result = _probe(
        [
            "dbus-send",
            "--session",
            "--dest=org.freedesktop.portal.Desktop",
            "--print-reply",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.Settings.Read",
            "string:org.freedesktop.appearance",
            "string:color-scheme",
        ]
    )
    if result is not None and result.returncode == 0:
        # Output contains "uint32 <value>" — extract last integer
        for token in reversed(result.stdout.split()):
            if token.isdecimal():
                scheme = int(token)
                if scheme == 1:
                    return True
                if scheme == 2:
                    return False
                break  # 0 = no preference, fall through

    # GNOME / colour-scheme setting
    result = _probe(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"])
    if result is not None and result.returncode == 0:
        val = result.stdout.strip().strip("'\"")
        if val == "prefer-dark":
            return True
        if val == "prefer-light":
            return False
        # 'default' means no preference — fall through to gtk-theme

    # GTK theme name (e.g. "Adwaita-dark", "Arc-Dark")
    result = _probe(["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"])
    if result is not None and result.returncode == 0 and result.stdout.strip():
        return "dark" in result.stdout.lower()

    # KDE plasma
    result = _probe(["kreadconfig5", "--group", "General", "--key", "ColorScheme"])
    if result is not None and result.returncode == 0 and result.stdout.strip():
        return "dark" in result.stdout.lower()

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
    BINDINGS = [
        # A focused text field types "?", so F1 opens the Keys screen too.  Both
        # run the same action, and the footer shows the first one that applies.
        Binding("question_mark", "show_keys", "Keys"),
        Binding("f1", "show_keys", "Keys", key_display="F1", priority=True),
        Binding("ctrl+t", "toggle_theme", "Dark/light theme", show=False, priority=True),
        # ctrl+c always quits (unless there is selected text to copy).  The
        # first binding puts it in the footer wherever q doesn't quit: while
        # typing, and on screens where q goes back.  Otherwise it is disabled
        # and the hidden second one quits.
        Binding("ctrl+c", "quit_ctrl_c", "Quit", priority=True),
        Binding("ctrl+c", "quit", "Quit", show=False),
    ]

    def __init__(self, dry_run: bool = False, entra: bool = False, demo_mode: bool = False) -> None:
        super().__init__()
        self.register_theme(FOMO_DARK)
        self.register_theme(FOMO_LIGHT)
        self.dry_run = dry_run
        self.entra = entra
        self.demo_mode = demo_mode
        self.backend: Backend = make_backend(dry_run=dry_run, demo_mode=demo_mode)
        override = _theme_override()
        # Dark until the system's colour scheme is known (see on_mount).
        self.theme = override or "fomo-dark"
        # Set by FOMO_THEME or ctrl+t: the system's colour scheme no longer applies.
        self._theme_chosen = override is not None
        self._color_scheme_proc: subprocess.Popen | None = None

    def on_mount(self) -> None:
        if self.demo_mode:
            self.title = "fomo  ·  Azure PIM  [DEMO]"
        elif self.dry_run:
            self.title = "fomo  ·  Azure PIM  [DRY RUN]"
        initial_tab = "tab-entra" if self.entra else "tab-azure"
        self.push_screen(ScopeScreen(initial_tab=initial_tab))
        if not self._theme_chosen:
            self.run_worker(self._detect_theme, thread=True)
            self._watch_color_scheme()
        self.run_worker(self._load_account_info, thread=True)

    def _detect_theme(self) -> None:
        """Thread worker: switch to the system's colour scheme once it is known."""
        theme = "fomo-dark" if _system_is_dark() else "fomo-light"
        self.call_from_thread(self._apply_system_theme, theme)

    def _apply_system_theme(self, theme: str) -> None:
        if not self._theme_chosen:  # ctrl+t while detection was running
            self.theme = theme

    def action_toggle_theme(self) -> None:
        """ctrl+t: switch between the dark and the light theme."""
        self._theme_chosen = True
        self.theme = "fomo-light" if self.theme == "fomo-dark" else "fomo-dark"

    def _load_account_info(self) -> None:
        if self.demo_mode:
            from fomo import demo as demo_data

            base = "fomo  ·  Azure PIM  [DEMO]"
            self.call_from_thread(
                setattr,
                self,
                "title",
                f"{base}  ·  {demo_data.DEMO_USER}  ·  {demo_data.DEMO_TENANT}",
            )
            return
        try:
            azure.check_auth()
            user, tenant = azure.get_account_info()
            base = "fomo  ·  Azure PIM  [DRY RUN]" if self.dry_run else "fomo  ·  Azure PIM"
            self.call_from_thread(setattr, self, "title", f"{base}  ·  {user}  ·  {tenant}")
        except Exception as exc:
            msg = str(exc)
            kind = azure.classify_auth_error(msg)
            if kind in ("expired", "not_logged_in", "mfa"):
                self.call_from_thread(self.show_auth_error, kind, msg, self._retry_session)

    def _retry_session(self) -> None:
        """Retry after re-login: reload the account, and an empty subscription list.

        A session that has no account yet can list zero subscriptions without
        failing, so the scope screen would never ask to retry on its own.
        """
        self.run_worker(self._load_account_info, thread=True)
        for screen in self.screen_stack:
            if isinstance(screen, ScopeScreen) and not screen.has_subscriptions:
                screen.reload_subscriptions()

    def show_auth_error(self, kind: azure.AuthErrorKind, message: str, on_retry: Callable[[], None]) -> None:
        """Open the AuthErrorModal; picking Retry calls *on_retry*.

        A loader that fails while the dialog is already open (the account
        check and the subscription list usually fail together) joins it
        instead of stacking a second dialog, and Retry runs every callback.
        """
        for screen in self.screen_stack:
            if isinstance(screen, AuthErrorModal):
                screen.retry_callbacks.append(on_retry)
                return
        modal = AuthErrorModal(kind, message)
        modal.retry_callbacks.append(on_retry)

        def _closed(retry: bool | None) -> None:
            if retry:
                for callback in modal.retry_callbacks:
                    callback()

        self.push_screen(modal, _closed)

    # ------------------------------------------------------------------
    # App-wide keys: ? / F1 (Keys) and ctrl+c (Quit)
    # ------------------------------------------------------------------

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "quit_ctrl_c":
            return not self._q_quits()
        return super().check_action(action, parameters)

    def _q_quits(self) -> bool:
        """Whether q quits right now: not typed into a field, and bound to quit on this screen."""
        screen = self.screen
        focused = screen.focused
        if focused is not None and focused.check_consume_key("q", "q"):
            return False
        for binding in Binding.make_bindings(type(screen).BINDINGS):
            # The first q binding that applies is the one q runs.
            if binding.key == "q" and screen.check_action(binding.action, ()) is True:
                return binding.action == "quit_app"
        return False

    def action_quit_ctrl_c(self) -> None:
        """ctrl+c: quit, unless there is selected text, which ctrl+c then copies."""
        focused = self.focused
        if getattr(focused, "selected_text", "") or self.screen.get_selected_text():
            raise SkipAction()
        self.exit()

    def action_show_keys(self) -> None:
        """? or F1: open the Keys screen for the current screen (F1 again closes it)."""
        screen = self.screen
        if isinstance(screen, KeysScreen):
            screen.dismiss()
            return
        self.push_screen(KeysScreen(screen_key_rows(screen), binding_rows(type(self).BINDINGS)))

    def on_unmount(self) -> None:
        if self._color_scheme_proc is not None:
            self._color_scheme_proc.terminate()

    def _watch_color_scheme(self) -> None:
        """Start background worker that listens for OS dark/light changes."""
        self.run_worker(self._dbus_color_scheme_watcher, thread=True)

    def _dbus_color_scheme_watcher(self) -> None:
        """Thread worker: tail dbus-monitor and update theme on changes."""
        worker = get_current_worker()
        try:
            proc = subprocess.Popen(
                [
                    "dbus-monitor",
                    "--session",
                    "type='signal',interface='org.freedesktop.portal.Settings',member='SettingChanged'",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError:  # no dbus-monitor (e.g. macOS)
            return
        self._color_scheme_proc = proc
        assert proc.stdout is not None  # stdout=PIPE always provides a stream
        state = _COLOR_SCHEME_IDLE
        try:
            for line in proc.stdout:
                if worker.is_cancelled:
                    break
                state, theme = _parse_color_scheme_line(state, line)
                if theme is not None:
                    self.call_from_thread(setattr, self, "theme", theme)
        finally:
            self._color_scheme_proc = None
            proc.wait()
