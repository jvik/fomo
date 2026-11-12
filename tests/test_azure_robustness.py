"""``fomo.azure`` under load and on bad answers (F13, F16, F17).

- F16: the signed-in user's ID is looked up once per process, not once per
  subscription (each lookup is an ``az`` process), and the roles screen loads
  at most four subscriptions at a time instead of all of them at once.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import threading
import time
from collections.abc import Callable
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
