"""Shared fixtures: hermetic kill switch, fake Azure boundary and a CLI runner.

Every test is hermetic by default.  The autouse ``_hermetic`` fixture makes any
attempt at real I/O (``subprocess.run``, ``urllib.request.urlopen``,
``webbrowser.open``) fail loudly, and points every on-disk cache at
``tmp_path``.  Tests that need Azure data opt in to ``fake_azure``, which
replaces the public functions of ``fomo.azure`` with in-memory fakes.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import urllib.request
import webbrowser
from collections.abc import Callable
from typing import Any

import pytest

from fomo import azure, tiering
from fomo.azure import (
    ActiveAssignment,
    ActiveEntraAssignment,
    EligibleRole,
    EntraEligibleRole,
    ManagementGroup,
    Subscription,
)

# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------


def _blocked(name: str) -> Callable[..., Any]:
    def _raise(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"real I/O in tests: {name}{args!r}")

    return _raise


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    """Block real I/O and isolate every cache under ``tmp_path``."""
    monkeypatch.setattr(subprocess, "run", _blocked("subprocess.run"))
    monkeypatch.setattr(urllib.request, "urlopen", _blocked("urllib.request.urlopen"))
    monkeypatch.setattr(webbrowser, "open", _blocked("webbrowser.open"))

    monkeypatch.setattr(azure, "_TOKEN_CACHE_PATH", str(tmp_path / "graph_token.json"))
    monkeypatch.setattr(azure, "_graph_token_cache", None)

    monkeypatch.setattr(tiering, "_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(tiering, "_azure_index", {})
    monkeypatch.setattr(tiering, "_entra_index", {})
    monkeypatch.setattr(tiering, "_fetch_json", lambda url: None)

    yield

    # main() calls logging.disable(CRITICAL) globally; undo it.
    logging.disable(logging.NOTSET)


# Small tiering data keyed by the trailing segment of the fake role IDs below.
TIERING_AZURE = [
    {"id": "Owner", "tier": "0", "assetName": "Owner", "shortestPath": "Owns everything"},
    {"id": "Contributor", "tier": "1", "assetName": "Contributor", "shortestPath": "Writes"},
    {"id": "Reader", "tier": "3", "assetName": "Reader", "worstCaseScenario": "Reads"},
]
TIERING_ENTRA = [
    {"id": "gr", "tier": "2", "assetName": "Global Reader", "worstCaseScenario": "Reads all"},
    {"id": "sr", "tier": "2", "assetName": "Security Reader", "worstCaseScenario": "Reads sec"},
]


@pytest.fixture
def tiering_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opt in to small tiering data instead of the empty default."""

    def _fetch(url: str) -> list | None:
        if url == tiering._AZURE_URL:
            return [dict(item) for item in TIERING_AZURE]
        if url == tiering._ENTRA_URL:
            return [dict(item) for item in TIERING_ENTRA]
        return None

    monkeypatch.setattr(tiering, "_fetch_json", _fetch)


# ---------------------------------------------------------------------------
# Fake Azure boundary
# ---------------------------------------------------------------------------

ROOT_MG = "/providers/Microsoft.Management/managementGroups/root"


def role(name: str, scope: str, active: bool = False, disp: str | None = None) -> EligibleRole:
    return EligibleRole(
        name,
        f"{scope}/providers/x/roleDefinitions/{name}",
        scope,
        disp or scope.rsplit("/", 1)[-1],
        "u",
        "sched",
        None,
        active,
    )


def make_subs() -> list[Subscription]:
    return [Subscription("s1", "Contoso Production"), Subscription("s2", "Contoso Dev")]


def make_mgs() -> list[ManagementGroup]:
    return [
        ManagementGroup("platform", "Platform"),
        ManagementGroup("platform-dev", "Platform Dev"),
        ManagementGroup("corp", "Corp"),
    ]


def make_roles() -> dict[str, list[EligibleRole]]:
    return {
        "s1": [
            role("Reader", "/subscriptions/s1"),
            role("Key Vault Reader", "/subscriptions/s1"),
            role("Contributor", "/subscriptions/s1", active=True),
            role("Reader", ROOT_MG, disp="Tenant Root"),
        ],
        "s2": [role("Reader", "/subscriptions/s2")],
    }


def make_mg_roles() -> dict[str, list[EligibleRole]]:
    return {
        "corp": [
            role("Reader", "/providers/Microsoft.Management/managementGroups/corp"),
            role("Owner", ROOT_MG, disp="Tenant Root"),
        ]
    }


def make_entra() -> list[EntraEligibleRole]:
    return [
        EntraEligibleRole("Global Reader", "gr", "u", "e1", None),
        EntraEligibleRole("Security Reader", "sr", "u", "e2", None),
        EntraEligibleRole("Reports Reader", "rr", "u", "e3", None, is_active=True),
    ]


DEVICE_CODE_MESSAGE = "https://microsoft.com/devicelogin\nABCD-1234"


def _exc(err: BaseException | str) -> BaseException:
    return err if isinstance(err, BaseException) else RuntimeError(err)


class FakeAzure:
    """In-memory stand-in for the public functions of ``fomo.azure``.

    Data attributes (``subs``, ``mgs``, ``roles``, ``mg_roles``, ``entra``,
    ``arm_assignments``, ``entra_assignments``) are fresh per test and may be
    replaced.  Failure toggles are ``None`` (off), a message string (raised as
    ``RuntimeError``) or an exception instance (raised as-is).
    """

    def __init__(self) -> None:
        self.subs = make_subs()
        self.mgs = make_mgs()
        self.roles = make_roles()
        self.mg_roles = make_mg_roles()
        self.entra = make_entra()
        self.arm_assignments = [
            ActiveAssignment("Reader", "/subscriptions/s1", "Contoso Production", None, "Assigned"),
        ]
        self.entra_assignments = [
            ActiveEntraAssignment("Global Reader", "/", None, "Activated"),
        ]

        # Failure toggles
        self.subs_err: BaseException | str | None = None
        self.mg_err: BaseException | str | None = None
        self.mg_roles_err: BaseException | str | None = None
        self.entra_err: BaseException | str | None = None
        self.auth_err: BaseException | str | None = None
        self.roles_err_sub: str | None = None
        self.fail_on: set[str] = set()
        self.device_code = False

        # Recordings
        self.calls: list[tuple[str, ...]] = []
        self.activations: list[tuple[str, str, str, bool]] = []
        self.justifications: list[str] = []

    # -- ARM listings ------------------------------------------------------

    def list_subscriptions(self) -> list[Subscription]:
        self.calls.append(("list_subscriptions",))
        if self.subs_err is not None:
            raise _exc(self.subs_err)
        return list(self.subs)

    def list_eligible_roles(self, subscription_id: str) -> list[EligibleRole]:
        self.calls.append(("list_eligible_roles", subscription_id))
        if self.roles_err_sub == subscription_id:
            raise RuntimeError(f"role fetch failed for {subscription_id}")
        return list(self.roles.get(subscription_id, []))

    def list_management_groups(self) -> list[ManagementGroup]:
        self.calls.append(("list_management_groups",))
        if self.mg_err is not None:
            raise _exc(self.mg_err)
        return list(self.mgs)

    def list_eligible_roles_mg(self, mg_id: str) -> list[EligibleRole]:
        self.calls.append(("list_eligible_roles_mg", mg_id))
        if self.mg_roles_err is not None:
            raise _exc(self.mg_roles_err)
        return list(self.mg_roles.get(mg_id, []))

    # -- Entra listings ----------------------------------------------------

    def list_entra_eligible_roles(
        self,
        on_device_code: Callable[[str], None] | None = None,
        stop_event: Any = None,
    ) -> list[EntraEligibleRole]:
        self.calls.append(("list_entra_eligible_roles",))
        if self.device_code and on_device_code is not None:
            on_device_code(DEVICE_CODE_MESSAGE)
        if self.entra_err is not None:
            raise _exc(self.entra_err)
        return list(self.entra)

    # -- Activation --------------------------------------------------------

    def activate_role(
        self,
        role: EligibleRole,
        justification: str,
        duration: str,
        dry_run: bool = False,
    ) -> dict:
        self.activations.append((role.role_name, role.scope, duration, dry_run))
        self.justifications.append(justification)
        if role.role_name in self.fail_on:
            raise RuntimeError(f"ERROR: (Boom) {role.role_name} failed")
        return {"properties": {"status": "DryRun" if dry_run else "Provisioned"}}

    def activate_entra_role(
        self,
        role: EntraEligibleRole,
        justification: str,
        duration: str,
        dry_run: bool = False,
    ) -> dict:
        self.activations.append((role.role_name, role.directory_scope_id, duration, dry_run))
        self.justifications.append(justification)
        if role.role_name in self.fail_on:
            raise RuntimeError("Graph says no")
        return {"status": "DryRun" if dry_run else "Provisioned"}

    # -- Session / assignments --------------------------------------------

    def check_auth(self) -> None:
        self.calls.append(("check_auth",))
        if self.auth_err is not None:
            raise _exc(self.auth_err)

    def get_account_info(self) -> tuple[str, str]:
        self.calls.append(("get_account_info",))
        return ("user@contoso.com", "Contoso")

    def list_active_arm_assignments(self) -> list[ActiveAssignment]:
        self.calls.append(("list_active_arm_assignments",))
        return list(self.arm_assignments)

    def list_active_entra_assignments(
        self,
        on_device_code: Callable[[str], None] | None = None,
        stop_event: Any = None,
    ) -> list[ActiveEntraAssignment]:
        self.calls.append(("list_active_entra_assignments",))
        return list(self.entra_assignments)


_PATCHED = (
    "list_subscriptions",
    "list_eligible_roles",
    "list_management_groups",
    "list_eligible_roles_mg",
    "list_entra_eligible_roles",
    "activate_role",
    "activate_entra_role",
    "check_auth",
    "get_account_info",
    "list_active_arm_assignments",
    "list_active_entra_assignments",
)


@pytest.fixture
def fake_azure(monkeypatch: pytest.MonkeyPatch) -> FakeAzure:
    """Replace the ``fomo.azure`` I/O functions with in-memory fakes."""
    fake = FakeAzure()
    for name in _PATCHED:
        monkeypatch.setattr(azure, name, getattr(fake, name))
    return fake


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------

CliResult = tuple[int, list[str], list[str]]


@pytest.fixture
def run_cli(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> Callable[[list[str]], CliResult]:
    """Run ``fomo.__main__.main()`` with *argv*; return (code, stdout, stderr) lines."""
    from fomo.__main__ import main

    # argparse wraps the usage line to the terminal width; pin it.
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setenv("NO_COLOR", "1")

    def _run(argv: list[str]) -> CliResult:
        monkeypatch.setattr(sys, "argv", ["fomo", *argv])
        capsys.readouterr()
        code: int
        try:
            main()
            code = 0
        except SystemExit as exc:
            if exc.code is None:
                code = 0
            elif isinstance(exc.code, int):
                code = exc.code
            else:
                code = 1
        out, err = capsys.readouterr()
        return code, out.splitlines(), err.splitlines()

    return _run
