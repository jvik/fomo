"""``fomo.azure`` under load and on bad answers (F13, F16, F17).

- F16: the signed-in user's ID is looked up once per process, not once per
  subscription (each lookup is an ``az`` process), and the roles screen loads
  at most four subscriptions at a time instead of all of them at once.
- F17: a failed lookup of the active assignments still lists every role as
  not active, but now says so in the log.
- F13: the Graph device-code sign-in opens a browser only where one can be
  seen (never a text-mode one), and survives proxy pages, rate limits and
  server errors instead of crashing with a ``JSONDecodeError`` or a raw
  ``HTTPError``.
"""

from __future__ import annotations

import asyncio
import email.message
import io
import json
import logging
import subprocess
import threading
import time
import urllib.error
import webbrowser
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from textual.widgets import Label

from fomo import app as app_module
from fomo import azure
from fomo.app import PimApp
from fomo.azure import EligibleRole
from fomo.screens.roles_screen import MAX_PARALLEL_LOADS, RolesScreen
from fomo.screens.scope_screen import ScopeScreen
from fomo.widgets import FomoSelectionList
from tests.conftest import role
from tests.test_tui_smoke import SIZE, wait_for

USER_ID = "00000000-0000-0000-0000-00000000c0de"
USER_SHOW = ["ad", "signed-in-user", "show"]


def _fake_az(
    monkeypatch: pytest.MonkeyPatch,
    respond: Callable[[list[str]], tuple[int, Any, str]],
) -> list[list[str]]:
    """Fake ``subprocess.run`` at the ``fomo.azure.subprocess`` boundary; return the recorded argv."""
    calls: list[list[str]] = []
    lock = threading.Lock()

    def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        with lock:
            calls.append(cmd)
        code, out, err = respond(cmd)
        return subprocess.CompletedProcess(cmd, code, stdout=json.dumps(out), stderr=err)

    monkeypatch.setattr(azure.subprocess, "run", _run)
    return calls


def _eligibility(scope: str) -> dict:
    return {
        "name": "inst-1",
        "properties": {
            "roleDefinitionId": f"{scope}/providers/Microsoft.Authorization/roleDefinitions/reader",
            "roleEligibilityScheduleId": f"{scope}/providers/Microsoft.Authorization/roleEligibilitySchedules/s1",
            "expandedProperties": {
                "roleDefinition": {"displayName": "Reader"},
                "scope": {"id": scope, "displayName": scope.rsplit("/", 1)[-1]},
            },
        },
    }


def _arm(cmd: list[str]) -> tuple[int, Any, str]:
    """Answer the ``az`` calls of the eligible-role listings."""
    if cmd[1:4] == USER_SHOW:
        return 0, USER_ID, ""
    if cmd[1] == "rest":
        url = cmd[cmd.index("--url") + 1]
        scope = url.removeprefix("https://management.azure.com").split("/providers/Microsoft.Authorization/")[0]
        if "/roleAssignmentScheduleInstances" in url:
            return 0, {"value": []}, ""
        if "/roleEligibilityScheduleInstances" in url:
            return 0, {"value": [_eligibility(scope)]}, ""
    raise AssertionError(f"unexpected az call {cmd!r}")


def _user_lookups(calls: list[list[str]]) -> int:
    return sum(1 for cmd in calls if cmd[1:4] == USER_SHOW)


# ---------------------------------------------------------------------------
# F16: user lookup once
# ---------------------------------------------------------------------------


def test_user_is_looked_up_once_across_subscriptions(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_az(monkeypatch, _arm)

    for sub in ("s1", "s2", "s3"):
        roles = azure.list_eligible_roles(sub)
        assert [(r.scope, r.principal_id) for r in roles] == [(f"/subscriptions/{sub}", USER_ID)]
    mg_roles = azure.list_eligible_roles_mg("corp")
    assert [r.principal_id for r in mg_roles] == [USER_ID]

    assert _user_lookups(calls) == 1


def test_parallel_loads_share_one_user_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    def _slow_user(cmd: list[str]) -> tuple[int, Any, str]:
        if cmd[1:4] == USER_SHOW:
            time.sleep(0.05)  # the other loads arrive while the first lookup runs
        return _arm(cmd)

    calls = _fake_az(monkeypatch, _slow_user)
    results: list[Any] = []

    def _load(sub: str) -> None:
        try:
            results.append(azure.list_eligible_roles(sub)[0].principal_id)
        except Exception as exc:
            results.append(exc)

    threads = [threading.Thread(target=_load, args=(sub,)) for sub in ("s1", "s2", "s3")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert results == [USER_ID] * 3
    assert _user_lookups(calls) == 1


def test_failed_user_lookup_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter([(1, None, "ERROR: Please run 'az login' to setup account."), (0, USER_ID, "")])
    calls = _fake_az(monkeypatch, lambda cmd: next(answers))

    with pytest.raises(RuntimeError, match="az login"):
        azure.get_current_user()
    assert azure.get_current_user() == USER_ID
    assert azure.get_current_user() == USER_ID

    assert _user_lookups(calls) == 2


def test_reset_caches_forgets_the_user(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_az(monkeypatch, _arm)

    azure.get_current_user()
    azure.reset_caches()
    azure.get_current_user()

    assert _user_lookups(calls) == 2


# ---------------------------------------------------------------------------
# F16: bounded parallel loads
# ---------------------------------------------------------------------------


class _GatedLoader:
    """A role loader that records how many calls run at once and finishes one call per ``release()``."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.inside = 0
        self.max_inside = 0
        self.calls: list[str] = []
        self.gate = threading.Semaphore(0)

    def __call__(self, sub_id: str) -> list[EligibleRole]:
        with self.lock:
            self.calls.append(sub_id)
            self.inside += 1
            self.max_inside = max(self.max_inside, self.inside)
        try:
            assert self.gate.acquire(timeout=5), "loader never released"
        finally:
            with self.lock:
                self.inside -= 1
        return [role("Reader", f"/subscriptions/{sub_id}")]

    def release(self, n: int = 1) -> None:
        self.gate.release(n)


def test_roles_screen_loads_at_most_four_subscriptions_at_once(
    fake_azure: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "_system_is_dark", lambda: True)
    monkeypatch.setattr(PimApp, "_watch_color_scheme", lambda self: None)
    loader = _GatedLoader()
    monkeypatch.setattr(azure, "list_eligible_roles", loader)
    subs = [f"sub-{i:02d}" for i in range(10)]

    async def scenario() -> None:
        app = PimApp(demo_mode=False, dry_run=True)
        async with app.run_test(size=SIZE) as pilot:
            await wait_for(pilot, lambda: isinstance(app.screen, ScopeScreen))
            screen = RolesScreen(subs)
            await app.push_screen(screen)
            label = screen.query_one("#loading-label", Label)
            try:
                await wait_for(pilot, lambda: loader.inside == MAX_PARALLEL_LOADS)
                await pilot.pause(0.05)  # room for a fifth load to (wrongly) start
                assert loader.inside == MAX_PARALLEL_LOADS
                assert str(label.visual) == "Loading roles from 10 subscription(s)…"

                # Progress still moves one subscription at a time, and a freed
                # slot goes to the next subscription.
                loader.release()
                await wait_for(pilot, lambda: str(label.visual) == "Loading roles… 1/10")
                await wait_for(pilot, lambda: len(loader.calls) == MAX_PARALLEL_LOADS + 1)
            finally:
                loader.release(len(subs))
            role_list = screen.query_one("#role-list", FomoSelectionList)
            await wait_for(pilot, lambda: role_list.option_count == len(subs))

    asyncio.run(scenario())
    assert MAX_PARALLEL_LOADS == 4
    assert loader.max_inside == 4
    assert sorted(loader.calls) == subs


# ---------------------------------------------------------------------------
# F17: logged active-assignment lookups
# ---------------------------------------------------------------------------

ARM_DENIED = "ERROR: (AuthorizationFailed) The client does not have authorization to perform action 'read'."


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "fomo.azure" and r.levelno == logging.WARNING]


@pytest.mark.parametrize(
    ("load", "scope"),
    [
        (lambda: azure.list_eligible_roles("s1"), "/subscriptions/s1"),
        (lambda: azure.list_eligible_roles_mg("corp"), "/providers/Microsoft.Management/managementGroups/corp"),
    ],
    ids=["subscription", "management-group"],
)
def test_failed_arm_active_lookup_is_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    load: Callable[[], list[EligibleRole]],
    scope: str,
) -> None:
    def _respond(cmd: list[str]) -> tuple[int, Any, str]:
        if cmd[1] == "rest" and "/roleAssignmentScheduleInstances" in cmd[cmd.index("--url") + 1]:
            return 1, None, ARM_DENIED
        return _arm(cmd)

    _fake_az(monkeypatch, _respond)
    caplog.set_level(logging.WARNING, logger="fomo.azure")

    roles = load()

    assert [(r.role_name, r.scope, r.is_active) for r in roles] == [("Reader", scope, False)]
    assert _warnings(caplog) == [f"could not read active assignments for {scope}: {ARM_DENIED}"]


class _Response(io.BytesIO):
    """What ``urlopen`` returns for a 2xx answer: a readable context manager."""

    status = 200


def _http_error(url: str, code: int, body: bytes, reason: str = "error") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, reason, email.message.Message(), io.BytesIO(body))


def test_failed_entra_active_lookup_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _fake_az(monkeypatch, _arm)
    monkeypatch.setattr(azure, "_get_graph_token", lambda *a, **k: "tok")
    eligible = {"value": [{"roleDefinitionId": "gr", "id": "e1", "roleDefinition": {"displayName": "Global Reader"}}]}

    def _urlopen(req: Any, *args: Any, **kwargs: Any) -> _Response:
        if "/roleAssignmentScheduleInstances" in req.full_url:
            raise _http_error(req.full_url, 403, b'{"error": {"message": "Insufficient privileges."}}')
        return _Response(json.dumps(eligible).encode())

    monkeypatch.setattr(azure.urllib.request, "urlopen", _urlopen)
    caplog.set_level(logging.WARNING, logger="fomo.azure")

    roles = azure.list_entra_eligible_roles()

    assert [(r.role_name, r.is_active) for r in roles] == [("Global Reader", False)]
    assert _warnings(caplog) == ["could not read active assignments for Entra roles: Insufficient privileges."]


# ---------------------------------------------------------------------------
# F13: when to open a browser
# ---------------------------------------------------------------------------

SSH = "10.0.0.1 50000 10.0.0.2 22"


def _executable(path: Path, target: Path | None = None) -> Path:
    if target is not None:
        path.symlink_to(target)
    else:
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755)
    return path


@pytest.fixture
def bin_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """An otherwise empty ``PATH`` and no display, SSH or ``BROWSER`` variables."""
    for name in ("DISPLAY", "WAYLAND_DISPLAY", "SSH_CONNECTION", "SSH_TTY", "BROWSER"):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / "bin"
    path.mkdir()
    monkeypatch.setenv("PATH", str(path))
    return path


@pytest.mark.parametrize(
    ("kind", "env", "wslview", "expected"),
    [
        ("unix", {"DISPLAY": ":0"}, False, True),
        ("unix", {"WAYLAND_DISPLAY": "wayland-0"}, False, True),
        ("unix", {}, False, False),
        ("unix", {"BROWSER": "firefox"}, False, False),
        ("unix", {"DISPLAY": "localhost:10.0", "SSH_CONNECTION": SSH}, False, False),
        ("unix", {"WAYLAND_DISPLAY": "wayland-0", "SSH_TTY": "/dev/pts/3"}, False, False),
        ("macos", {}, False, True),
        ("macos", {"SSH_CONNECTION": SSH, "SSH_TTY": "/dev/ttys001"}, False, True),
        ("windows", {}, False, True),
        ("wsl", {}, False, False),
        ("wsl", {}, True, True),
        ("wsl", {"BROWSER": "/mnt/c/Program Files/Mozilla Firefox/firefox.exe"}, False, True),
    ],
)
def test_can_open_browser(
    monkeypatch: pytest.MonkeyPatch, bin_dir: Path, kind: str, env: dict[str, str], wslview: bool, expected: bool
) -> None:
    monkeypatch.setattr(azure, "_platform", lambda: kind)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    if wslview:
        _executable(bin_dir / "wslview")

    assert azure._can_open_browser() is expected


def test_wsl_is_detected_from_the_environment_or_the_kernel(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("WSL_DISTRO_NAME", "WSL_INTEROP"):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setattr(azure.os, "uname", lambda: SimpleNamespace(release="7.2.15-300.fc45.x86_64"))
    assert not azure._is_wsl()
    monkeypatch.setattr(azure.os, "uname", lambda: SimpleNamespace(release="6.6.87.2-microsoft-standard-WSL2"))
    assert azure._is_wsl()
    monkeypatch.setattr(azure.os, "uname", lambda: SimpleNamespace(release="7.2.15-300.fc45.x86_64"))
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    assert azure._is_wsl()


@pytest.mark.parametrize(
    "browser",
    [
        webbrowser.GenericBrowser("lynx"),
        webbrowser.GenericBrowser("w3m"),
        webbrowser.GenericBrowser("links"),
        webbrowser.GenericBrowser("elinks"),
        webbrowser.GenericBrowser("www-browser"),
        webbrowser.GenericBrowser("/usr/bin/w3m"),
        webbrowser.GenericBrowser(["lynx", "-accept_all_cookies", "%s"]),  # BROWSER="lynx … %s"
        webbrowser.GenericBrowser("lynx %s"),
    ],
    ids=lambda b: str(b.name),
)
def test_console_browsers_are_recognised(bin_dir: Path, browser: webbrowser.BaseBrowser) -> None:
    assert azure._is_console_browser(browser)


@pytest.mark.parametrize(
    "browser",
    [
        webbrowser.BackgroundBrowser("firefox"),
        webbrowser.BackgroundBrowser("xdg-open"),
        webbrowser.GenericBrowser("/opt/google/chrome/google-chrome"),
        webbrowser.BaseBrowser(),
    ],
    ids=lambda b: str(b.name) or "unnamed",
)
def test_graphical_browsers_are_not_console_browsers(bin_dir: Path, browser: webbrowser.BaseBrowser) -> None:
    assert not azure._is_console_browser(browser)


def test_a_link_to_a_console_browser_is_a_console_browser(bin_dir: Path) -> None:
    w3m = _executable(bin_dir / "w3m")
    _executable(bin_dir / "my-browser", target=w3m)

    assert azure._is_console_browser(webbrowser.GenericBrowser("my-browser"))


class _FakeBrowser(webbrowser.BaseBrowser):
    def __init__(self, name: str, fail: bool = False) -> None:
        super().__init__(name)
        self.opened: list[str] = []
        self.fail = fail

    def open(self, url: str, new: int = 0, autoraise: bool = True) -> bool:
        if self.fail:
            raise OSError("cannot launch")
        self.opened.append(url)
        return True


URL = "https://microsoft.com/devicelogin?otc=ABCD-1234"


def _default_browser(monkeypatch: pytest.MonkeyPatch, browser: webbrowser.BaseBrowser | Exception) -> list[str]:
    """Make ``webbrowser.get()`` return (or raise) *browser*; return a record of its calls."""
    calls: list[str] = []

    def _get(using: str | None = None) -> webbrowser.BaseBrowser:
        calls.append(str(using))
        if isinstance(browser, Exception):
            raise browser
        return browser

    monkeypatch.setattr(webbrowser, "get", _get)
    return calls


def test_open_browser_opens_a_graphical_browser(monkeypatch: pytest.MonkeyPatch, bin_dir: Path) -> None:
    monkeypatch.setattr(azure, "_platform", lambda: "unix")
    monkeypatch.setenv("DISPLAY", ":0")
    firefox = _FakeBrowser("firefox")
    _default_browser(monkeypatch, firefox)

    azure._open_browser(URL)

    assert firefox.opened == [URL]


def test_open_browser_skips_a_console_browser(monkeypatch: pytest.MonkeyPatch, bin_dir: Path) -> None:
    monkeypatch.setattr(azure, "_platform", lambda: "unix")
    monkeypatch.setenv("DISPLAY", ":0")
    lynx = _FakeBrowser("lynx")
    _default_browser(monkeypatch, lynx)

    azure._open_browser(URL)

    assert lynx.opened == []


def test_open_browser_does_nothing_over_ssh(monkeypatch: pytest.MonkeyPatch, bin_dir: Path) -> None:
    monkeypatch.setattr(azure, "_platform", lambda: "unix")
    monkeypatch.setenv("DISPLAY", "localhost:10.0")
    monkeypatch.setenv("SSH_CONNECTION", SSH)
    calls = _default_browser(monkeypatch, _FakeBrowser("firefox"))

    azure._open_browser(URL)

    assert calls == []


@pytest.mark.parametrize(
    "browser",
    [webbrowser.Error("could not locate runnable browser"), _FakeBrowser("firefox", fail=True)],
    ids=["no-browser", "launch-fails"],
)
def test_open_browser_never_raises(
    monkeypatch: pytest.MonkeyPatch, bin_dir: Path, browser: webbrowser.BaseBrowser | Exception
) -> None:
    monkeypatch.setattr(azure, "_platform", lambda: "macos")
    _default_browser(monkeypatch, browser)

    azure._open_browser(URL)  # no exception


def test_wsl_opens_wslview_unless_browser_is_set(monkeypatch: pytest.MonkeyPatch, bin_dir: Path) -> None:
    monkeypatch.setattr(azure, "_platform", lambda: "wsl")
    wslview = _executable(bin_dir / "wslview")
    calls = _default_browser(monkeypatch, _FakeBrowser("firefox.exe"))

    picked = azure._pick_browser()
    assert isinstance(picked, webbrowser.BackgroundBrowser)
    assert picked.name == str(wslview)
    assert calls == []

    monkeypatch.setenv("BROWSER", "firefox.exe")
    assert azure._pick_browser().name == "firefox.exe"
    assert calls == ["None"]


# ---------------------------------------------------------------------------
# F13: device-code request and polling
# ---------------------------------------------------------------------------

TENANT = "tenant-1"
DEVICE_CODE = {
    "device_code": "DC",
    "user_code": "ABCD-1234",
    "verification_uri": "https://microsoft.com/devicelogin",
    "verification_uri_complete": URL,
    "interval": 5,
    "expires_in": 900,
}
TOKEN = {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600}
BAD_GATEWAY = (502, b"<html><body><h1>502 Bad Gateway</h1></body></html>")
PENDING = (400, {"error": "authorization_pending", "error_description": "AADSTS70016: pending"})
OK = (200, TOKEN)

Answer = tuple[int, "dict | bytes"]


class _Login:
    """Fake ``login.microsoftonline.com``: the device code, then one scripted answer per token poll."""

    def __init__(self, polls: list[Answer], device_code: Answer = (200, DEVICE_CODE)) -> None:
        self.polls = list(polls)
        self.device_code = device_code
        self.token_polls = 0

    def urlopen(self, req: Any, *args: Any, **kwargs: Any) -> _Response:
        if req.full_url.endswith("/oauth2/v2.0/devicecode"):
            code, body = self.device_code
        else:
            assert req.full_url == azure._token_endpoint(TENANT)
            self.token_polls += 1
            code, body = self.polls.pop(0)
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        if code >= 400:
            raise _http_error(req.full_url, code, raw, reason="Bad Gateway" if code == 502 else "error")
        response = _Response(raw)
        response.status = code
        return response


@pytest.fixture
def login(monkeypatch: pytest.MonkeyPatch) -> Callable[..., tuple[_Login, list[float], list[str]]]:
    """Install a fake login endpoint; return it, the poll sleeps and the URLs handed to the browser."""

    def _install(polls: list[Answer], **kwargs: Any) -> tuple[_Login, list[float], list[str]]:
        fake = _Login(polls, **kwargs)
        sleeps: list[float] = []
        opened: list[str] = []
        monkeypatch.setattr(azure.urllib.request, "urlopen", fake.urlopen)
        monkeypatch.setattr(azure.time, "sleep", sleeps.append)
        monkeypatch.setattr(azure, "_open_browser", opened.append)
        return fake, sleeps, opened

    return _install


def test_device_code_is_shown_and_opened_then_polled(login: Callable[..., Any]) -> None:
    fake, sleeps, opened = login([PENDING, OK])
    shown: list[str] = []

    assert azure._device_code_flow(TENANT, on_device_code=shown.append) == TOKEN

    assert shown == ["https://microsoft.com/devicelogin\nABCD-1234"]
    assert opened == [URL]
    assert sleeps == [5, 5]


def test_gateway_errors_are_retried(login: Callable[..., Any]) -> None:
    fake, sleeps, _ = login([BAD_GATEWAY, BAD_GATEWAY, OK])

    assert azure._device_code_flow(TENANT) == TOKEN
    assert fake.token_polls == 3
    assert sleeps == [5, 5, 5]


def test_three_non_json_answers_in_a_row_end_the_sign_in(login: Callable[..., Any]) -> None:
    fake, _, _ = login([BAD_GATEWAY, BAD_GATEWAY, BAD_GATEWAY, OK])

    with pytest.raises(RuntimeError) as excinfo:
        azure._device_code_flow(TENANT)

    assert type(excinfo.value) is RuntimeError
    assert str(excinfo.value) == "Graph sign-in failed: HTTP 502"
    assert fake.token_polls == 3


def test_only_consecutive_non_json_answers_count(login: Callable[..., Any]) -> None:
    html_200 = (200, b"<html>captive portal</html>")
    fake, _, _ = login([BAD_GATEWAY, html_200, PENDING, BAD_GATEWAY, BAD_GATEWAY, OK])

    assert azure._device_code_flow(TENANT) == TOKEN
    assert fake.token_polls == 6


def test_rate_limits_and_server_errors_are_retried(login: Callable[..., Any]) -> None:
    fake, _, _ = login(
        [
            (429, {"error": "too_many_requests"}),
            (503, {"error": "temporarily_unavailable", "error_description": "AADSTS90033: busy"}),
            (500, {"error": "server_error"}),
            (504, b""),
            OK,
        ]
    )

    assert azure._device_code_flow(TENANT) == TOKEN
    assert fake.token_polls == 5


@pytest.mark.parametrize(
    ("interval", "polls", "expected"),
    [
        (60, [OK], [30]),
        (28, [(400, {"error": "slow_down"}), PENDING, OK], [28, 30, 30]),
        (5, [(400, {"error": "slow_down"}), OK], [5, 10]),
    ],
    ids=["server-asks-60", "slow-down-hits-the-cap", "slow-down-below-the-cap"],
)
def test_poll_interval_is_capped_at_30_seconds(
    login: Callable[..., Any], interval: int, polls: list[Answer], expected: list[float]
) -> None:
    _, sleeps, _ = login(polls, device_code=(200, {**DEVICE_CODE, "interval": interval}))

    assert azure._device_code_flow(TENANT) == TOKEN
    assert sleeps == expected


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        ((400, {"error": "access_denied"}), "Graph authentication was denied."),
        ((400, {"error": "expired_token"}), "Device code expired — please try again."),
        (
            (400, {"error": "invalid_grant", "error_description": "AADSTS50126: bad"}),
            "Graph authentication failed: invalid_grant: AADSTS50126: bad",
        ),
    ],
    ids=["access_denied", "expired_token", "other"],
)
def test_oauth_errors_still_end_the_sign_in(login: Callable[..., Any], answer: Answer, message: str) -> None:
    login([answer])

    with pytest.raises(RuntimeError) as excinfo:
        azure._device_code_flow(TENANT)
    assert str(excinfo.value) == message


TENANT_NOT_FOUND = (
    400,
    {"error": "invalid_request", "error_description": "AADSTS90002: Tenant 'tenant-1' not found."},
)


@pytest.mark.parametrize(
    ("device_code", "message"),
    [
        (TENANT_NOT_FOUND, "Could not start Graph sign-in: HTTP 400 AADSTS90002: Tenant 'tenant-1' not found."),
        (BAD_GATEWAY, "Could not start Graph sign-in: HTTP 502 Bad Gateway"),
        ((200, b"<html>captive portal</html>"), "Could not start Graph sign-in: HTTP 200 unexpected response"),
    ],
    ids=["oauth-error", "gateway-error", "not-json"],
)
def test_device_code_request_errors_are_readable(login: Callable[..., Any], device_code: Answer, message: str) -> None:
    fake, _, opened = login([], device_code=device_code)

    with pytest.raises(RuntimeError) as excinfo:
        azure._device_code_flow(TENANT)

    assert type(excinfo.value) is RuntimeError  # not urllib's HTTPError or a JSONDecodeError
    assert str(excinfo.value) == message
    assert fake.token_polls == 0
    assert opened == []


def test_cli_reports_a_failed_sign_in_start(
    monkeypatch: pytest.MonkeyPatch, login: Callable[..., Any], run_cli: Callable[[list[str]], Any]
) -> None:
    def _respond(cmd: list[str]) -> tuple[int, Any, str]:
        if cmd[1:4] == USER_SHOW:
            return 0, USER_ID, ""
        if cmd[1:3] == ["account", "show"]:
            return 0, {"tenantId": TENANT}, ""
        raise AssertionError(f"unexpected az call {cmd!r}")

    _fake_az(monkeypatch, _respond)
    login([], device_code=TENANT_NOT_FOUND)

    code, out, err = run_cli(["--entra", "Global Reader", "-r", "x"])

    assert (code, out) == (1, ["Fetching Entra eligible roles…"])
    assert err == [
        "Error fetching Entra roles: Could not start Graph sign-in: HTTP 400 AADSTS90002: Tenant 'tenant-1' not found."
    ]
