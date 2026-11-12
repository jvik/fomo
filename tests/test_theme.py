"""Theme override, ctrl+t and non-blocking colour-scheme detection (F37).

The system's colour scheme used to be detected in ``PimApp.__init__`` with
up to four subprocesses of 1 s each, so startup could stall for seconds,
there was no override, and macOS always got the dark theme.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import threading
import time
from typing import Any

import pytest
from textual.widgets import Input

from fomo import app as app_module
from fomo.app import PimApp, _system_is_dark, _theme_override
from tests.test_tui_smoke import _subs_loaded, wait_for

_Answer = tuple[int, str] | BaseException


class _Probes:
    """Fake ``subprocess.run`` that records each probe.

    *answers* maps a probe's last argument to its (exit status, stdout), or
    to an exception to raise; a probe without an answer isn't installed.
    """

    def __init__(self, answers: dict[str, _Answer]) -> None:
        self.answers = answers
        self.calls: list[list[str]] = []
        self.timeouts: list[float] = []

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        self.timeouts.append(kwargs["timeout"])
        answer = self.answers.get(args[-1], FileNotFoundError(args[0]))
        if isinstance(answer, BaseException):
            raise answer
        returncode, stdout = answer
        return subprocess.CompletedProcess(args, returncode, stdout, "")


@pytest.fixture
def linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("GTK_THEME", raising=False)


@pytest.mark.parametrize(
    ("value", "theme"),
    [("light", "fomo-light"), (" Dark ", "fomo-dark"), ("blue", None), ("", None)],
)
def test_fomo_theme_override(monkeypatch: pytest.MonkeyPatch, value: str, theme: str | None) -> None:
    monkeypatch.setenv("FOMO_THEME", value)
    assert _theme_override() == theme


def test_detection_stops_at_the_first_decisive_answer_with_short_timeouts(
    monkeypatch: pytest.MonkeyPatch,
    linux: None,
) -> None:
    probes = _Probes({"string:color-scheme": (0, "   variant       uint32 2\n")})
    monkeypatch.setattr(subprocess, "run", probes)
    assert _system_is_dark() is False
    assert [args[0] for args in probes.calls] == ["dbus-send"]
    assert probes.timeouts == [0.3]


def test_detection_falls_through_undecided_probes(monkeypatch: pytest.MonkeyPatch, linux: None) -> None:
    probes = _Probes(
        {
            "string:color-scheme": (0, "   variant       uint32 0\n"),  # portal: no preference
            "color-scheme": (0, "'default'\n"),
            "gtk-theme": subprocess.TimeoutExpired("gsettings", 0.3),
            "ColorScheme": (0, "BreezeLight\n"),
        }
    )
    monkeypatch.setattr(subprocess, "run", probes)
    assert _system_is_dark() is False
    assert [args[0] for args in probes.calls] == ["dbus-send", "gsettings", "gsettings", "kreadconfig5"]
    assert set(probes.timeouts) == {0.3}


@pytest.mark.parametrize(
    ("answer", "dark"),
    [
        ((0, "Dark\n"), True),
        ((1, ""), False),  # light mode: the key doesn't exist
        (FileNotFoundError("defaults"), True),
        (subprocess.TimeoutExpired("defaults", 0.3), True),
    ],
)
def test_macos_asks_apple_interface_style(monkeypatch: pytest.MonkeyPatch, answer: _Answer, dark: bool) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    probes = _Probes({"AppleInterfaceStyle": answer})
    monkeypatch.setattr(subprocess, "run", probes)
    assert _system_is_dark() is dark
    assert probes.calls == [["defaults", "read", "-g", "AppleInterfaceStyle"]]


def test_fomo_theme_skips_detection_and_ctrl_t_toggles_while_typing(monkeypatch: pytest.MonkeyPatch) -> None:
    detections: list[str] = []

    def _detect() -> bool:
        detections.append("_system_is_dark")
        raise AssertionError("detection must not run with FOMO_THEME set")

    monkeypatch.setenv("FOMO_THEME", "light")
    monkeypatch.setattr(app_module, "_system_is_dark", _detect)
    monkeypatch.setattr(PimApp, "_watch_color_scheme", lambda self: detections.append("watch"))

    async def scenario() -> None:
        app = PimApp(demo_mode=True, dry_run=True)
        app.animation_level = "none"
        async with app.run_test(size=(80, 24)) as pilot:
            await _subs_loaded(pilot)
            assert app.theme == "fomo-light"
            await pilot.press("ctrl+t")
            assert app.theme == "fomo-dark"
            # A priority binding: it works while typing, and types nothing.
            field = app.screen.query_one("#filter", Input)
            field.focus()
            await pilot.pause()
            await pilot.press("ctrl+t")
            assert app.theme == "fomo-light"
            assert app.focused is field and field.value == ""
        assert detections == []

    asyncio.run(scenario())


def test_detection_runs_after_startup_in_a_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """With every probe hanging for 2 s, the app still starts at once, dark, and turns light later."""
    release = threading.Event()
    probes: list[tuple[str, bool]] = []

    def _slow_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        probes.append((args[0], threading.current_thread() is threading.main_thread()))
        release.wait(2)
        return subprocess.CompletedProcess(args, 0, "   variant       uint32 2\n", "")

    def _no_dbus_monitor(*args: Any, **kwargs: Any) -> None:
        raise FileNotFoundError("dbus-monitor")

    monkeypatch.delenv("FOMO_THEME", raising=False)
    monkeypatch.setattr(subprocess, "run", _slow_run)
    monkeypatch.setattr(subprocess, "Popen", _no_dbus_monitor)

    async def scenario() -> None:
        app = PimApp(demo_mode=True, dry_run=True)
        app.animation_level = "none"
        started = time.monotonic()
        try:
            async with app.run_test(size=(80, 24)) as pilot:
                assert time.monotonic() - started < 1
                assert app.theme == "fomo-dark"
                await wait_for(pilot, lambda: probes)
                release.set()
                await wait_for(pilot, lambda: app.theme == "fomo-light")
        finally:
            release.set()
        assert probes and not any(on_main_thread for _, on_main_thread in probes)

    asyncio.run(scenario())
