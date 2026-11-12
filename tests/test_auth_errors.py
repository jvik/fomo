"""Auth-error classification and how the TUI routes each class (F15).

``is_auth_error`` used to match any ``aadsts``, ``unauthorized`` or ``please
run``, so an MFA or Conditional Access block was reported as "Azure session
expired… restart fomo".  ``classify_auth_error`` now tells expired and missing
sessions apart from MFA and consent errors, and only the former two open the
AuthErrorModal.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from textual.pilot import Pilot

from fomo import app as app_module
from fomo import azure
from fomo.app import AuthErrorModal, PimApp
from fomo.screens.roles_screen import RolesScreen
from fomo.screens.scope_screen import ScopeScreen
from fomo.widgets import FomoSelectionList
from tests.test_tui_smoke import SIZE, _prompts, wait_for

MFA_MSG = (
    "AADSTS50076: Due to a configuration change made by your administrator, or because you moved to a "
    "new location, you must use multi-factor authentication to access '797f4846-ba00-4fd7-ba43-dac1f8f63013'."
)

CLASSIFIER_CASES: list[tuple[str, azure.AuthErrorKind]] = [
    # expired: codes
    ("AADSTS700082: The refresh token has expired due to inactivity.", "expired"),
    (
        "ERROR: AADSTS70043: The refresh token has expired or is invalid due to sign-in frequency checks "
        "by conditional access.",
        "expired",
    ),
    ("AADSTS50173: The provided grant has expired due to it being revoked.", "expired"),
    ("AADSTS700084: The refresh token was issued to a single page app (SPA).", "expired"),
    ("AADSTS50133: Session is invalid due to expiration or recent password change.", "expired"),
    ("AADSTS700082: … Please run 'az login'", "expired"),
    # expired: phrases
    ("The refresh token has expired due to inactivity.", "expired"),
    ("ERROR: The access token is expired.", "expired"),
    # not logged in
    ("ERROR: Please run 'az login' to setup account.", "not_logged_in"),
    ('Please run "az login" to access your accounts.', "not_logged_in"),
    ("You are not logged in. Run az login first.", "not_logged_in"),
    ("No subscription found. Run 'az account set' to select a subscription.", "not_logged_in"),
    # MFA / Conditional Access: codes
    (MFA_MSG, "mfa"),
    ("AADSTS50079: Due to a configuration change, the user is required to use multi-factor auth.", "mfa"),
    ("AADSTS50158: External security challenge was not satisfied.", "mfa"),
    ("AADSTS53003: Access has been blocked by Conditional Access policies.", "mfa"),
    ("AADSTS50078: Presented multi-factor authentication has expired. Please run 'az login'", "mfa"),
    # MFA / Conditional Access: phrases
    ("You must use multi-factor authentication to access this resource.", "mfa"),
    ("The request was blocked by a conditional access policy.", "mfa"),
    # consent: is_scope_error tokens and codes
    ("PermissionScopeNotGranted: Authorization failed due to missing permission scope", "consent"),
    ("Authorization_RequestDenied", "consent"),
    ("Insufficient privileges to complete the operation.", "consent"),
    ("AADSTS65001: The user or administrator has not consented to use the application.", "consent"),
    ("AADSTS7000112: Application is disabled.", "consent"),
    # other
    ("(AuthorizationFailed) The client 'x' does not have authorization to perform action 'y'.", "other"),
    ("Unauthorized", "other"),
    ("AADSTS50020: User account from identity provider does not exist in tenant.", "other"),
    ("AADSTS500761: not one of the listed codes", "other"),
    ("AADSTS7000: prefix of a listed code", "other"),
    ("Please run the following command", "other"),
    ("Run az login --tenant 123", "other"),
    ("not logged in", "other"),
    ("role fetch failed for s1", "other"),
    ("", "other"),
]


@pytest.mark.parametrize(("msg", "kind"), CLASSIFIER_CASES)
def test_classify_auth_error(msg: str, kind: azure.AuthErrorKind) -> None:
    assert azure.classify_auth_error(msg) == kind


@pytest.mark.parametrize(("msg", "kind"), CLASSIFIER_CASES)
def test_is_auth_error_means_expired_or_not_logged_in(msg: str, kind: azure.AuthErrorKind) -> None:
    assert azure.is_auth_error(msg) is (kind in {"expired", "not_logged_in"})


def test_classify_auth_error_is_case_insensitive() -> None:
    assert azure.classify_auth_error("aadsts50076: mfa") == "mfa"
    assert azure.classify_auth_error("PLEASE RUN 'AZ LOGIN'") == "not_logged_in"


# ---------------------------------------------------------------------------
# Pilot
# ---------------------------------------------------------------------------


@pytest.fixture
def make_live_app(monkeypatch: pytest.MonkeyPatch, fake_azure: Any) -> Callable[[], PimApp]:
    """PimApp on the fake Azure boundary: not demo mode, dry run on."""
    monkeypatch.setattr(app_module, "_system_is_dark", lambda: True)
    monkeypatch.setattr(PimApp, "_watch_color_scheme", lambda self: None)
    return lambda: PimApp(demo_mode=False, dry_run=True)


def _toasts(app: PimApp) -> list[str]:
    return [str(toast.render()) for toast in app.screen.query("Toast")]


def _has_modal(app: PimApp) -> bool:
    return any(isinstance(screen, AuthErrorModal) for screen in app.screen_stack)


async def _scope_ready(pilot: Pilot) -> ScopeScreen:
    await wait_for(pilot, lambda: isinstance(pilot.app.screen, ScopeScreen))
    screen = pilot.app.screen
    assert isinstance(screen, ScopeScreen)
    return screen


def test_roles_screen_reports_mfa_error_for_that_subscription_only(make_live_app, fake_azure) -> None:
    fake_azure.roles_err["s1"] = MFA_MSG

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE, notifications=True) as pilot:
            await _scope_ready(pilot)
            await app.push_screen(RolesScreen(["s1", "s2"]))
            role_list = app.screen.query_one("#role-list", FomoSelectionList)
            await wait_for(pilot, lambda: role_list.option_count > 0 and _toasts(app))
            await pilot.pause()
            assert not _has_modal(app)
            assert isinstance(app.screen, RolesScreen)
            toasts = _toasts(app)
            assert toasts == [f"[s1…] {MFA_MSG}"]
            # s2 still loaded.
            assert _prompts(role_list) == ["Reader  —  s2"]

    asyncio.run(scenario())
