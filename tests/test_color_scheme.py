"""The dbus-monitor colour-scheme parser behind PimApp's live theme switching (F21)."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

from fomo import app as app_module
from fomo.app import _COLOR_SCHEME_IDLE, PimApp, _parse_color_scheme_line

ARMED = ("org.freedesktop.appearance", "color-scheme")

SIGNAL = [
    "signal time=1.0 sender=:1.2 -> destination=(null destination) serial=7 "
    "path=/org/freedesktop/portal/desktop; interface=org.freedesktop.portal.Settings; member=SettingChanged\n",
    '   string "org.freedesktop.appearance"\n',
    '   string "color-scheme"\n',
]


def _feed(lines: list[str]) -> tuple[tuple[str | None, str | None], list[str | None]]:
    state = _COLOR_SCHEME_IDLE
    themes = []
    for line in lines:
        state, theme = _parse_color_scheme_line(state, line)
        themes.append(theme)
    return state, themes


def test_signal_lines_arm_the_parser() -> None:
    state, themes = _feed(SIGNAL)
    assert state == ARMED
    assert themes == [None, None, None]


@pytest.mark.parametrize(
    ("line", "theme"),
    [("   uint32 1\n", "fomo-dark"), ("   uint32 2\n", "fomo-light"), ("uint32 0", None)],
)
def test_uint32_value_sets_theme_and_resets(line: str, theme: str | None) -> None:
    assert _parse_color_scheme_line(ARMED, line) == (_COLOR_SCHEME_IDLE, theme)


@pytest.mark.parametrize(
    "line",
    ["uint32", "   uint32\n", "uint32 abc", "uint32 -1", "uint32 ²", "", "garbage"],
)
def test_malformed_value_line_is_ignored_and_keeps_waiting(line: str) -> None:
    assert _parse_color_scheme_line(ARMED, line) == (ARMED, None)


@pytest.mark.parametrize("line", ["uint32", "uint32 1", "garbage", '   string "other"\n'])
def test_unrelated_line_while_idle_stays_idle(line: str) -> None:
    assert _parse_color_scheme_line(_COLOR_SCHEME_IDLE, line) == (_COLOR_SCHEME_IDLE, None)


def test_color_scheme_key_needs_the_appearance_namespace_first() -> None:
    state, themes = _feed(['   string "color-scheme"\n', "uint32 1"])
    assert state == _COLOR_SCHEME_IDLE
    assert themes == [None, None]


def test_bare_uint32_then_value() -> None:
    state, themes = _feed([*SIGNAL, "uint32", "uint32 2"])
    assert state == _COLOR_SCHEME_IDLE
    assert themes == [None, None, None, None, "fomo-light"]


class _FakeProc:
    def __init__(self, lines: list[str]) -> None:
        self.stdout = iter(lines)
        self.waited = False

    def wait(self) -> int:
        self.waited = True
        return 0


def test_watcher_survives_bare_uint32_line(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _FakeProc([*SIGNAL, "   uint32\n", "   uint32 1\n"])
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: proc)
    monkeypatch.setattr(app_module, "get_current_worker", lambda: SimpleNamespace(is_cancelled=False))
    calls: list[tuple[Any, ...]] = []
    stub = SimpleNamespace(_color_scheme_proc=None, call_from_thread=lambda *args: calls.append(args))

    PimApp._dbus_color_scheme_watcher(stub)  # type: ignore[arg-type]

    assert calls == [(setattr, stub, "theme", "fomo-dark")]
    assert proc.waited
    assert stub._color_scheme_proc is None
