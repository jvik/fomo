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
from textual.geometry import Region
from textual.pilot import Pilot
from textual.widgets import DataTable, Label

from fomo import app as app_module
from fomo import azure
from fomo.app import AuthErrorModal, PimApp
from fomo.azure import ActiveAssignment
from fomo.screens.assignments_screen import AssignmentsScreen
from fomo.screens.roles_screen import RolesScreen
from fomo.screens.scope_screen import ScopeScreen
from fomo.widgets import FomoSelectionList
from tests.conftest import make_subs
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


# ---------------------------------------------------------------------------
# AuthErrorModal: readable text and Retry
# ---------------------------------------------------------------------------

EXPIRED_MSG = (
    "ERROR: AADSTS700082: The refresh token has expired due to inactivity. The token was issued on "
    "2026-01-01T00:00:00.0000000Z and was inactive for 90.00:00:00. Trace ID: 0b0c1d2e-aaaa-bbbb-cccc-"
    "1234567890ab Correlation ID: 11112222-3333-4444-5555-666677778888 Timestamp: 2026-04-01 00:00:00Z\n"
    "Please run 'az login' to setup account."
)
NOT_LOGGED_IN_MSG = "ERROR: Please run 'az login' to setup account."
SMALL = (80, 24)


def _screen_lines(app: PimApp) -> list[str]:
    """Every line of the active screen as rendered."""
    return [strip.text for strip in app.screen._compositor.render_strips()]


def _label_lines(app: PimApp, selector: str) -> list[str]:
    """The rendered lines of one label, stripped."""
    label = app.screen.query_one(selector, Label)
    return [label.render_line(y).text.strip() for y in range(label.size.height)]


def _words(text: str) -> list[str]:
    return text.split()


async def _modal_ready(pilot: Pilot) -> AuthErrorModal:
    await wait_for(pilot, lambda: isinstance(pilot.app.screen, AuthErrorModal))
    await pilot.pause()
    modal = pilot.app.screen
    assert isinstance(modal, AuthErrorModal)
    return modal


def _assert_fits(app: PimApp) -> None:
    """The dialog and every label in it lie inside the 80x24 screen, unclipped."""
    screen_region = Region(0, 0, *SMALL)
    dialog = app.screen.query_one("#auth-error-dialog")
    assert screen_region.contains_region(dialog.region), dialog.region
    for label in dialog.query(Label):
        assert dialog.region.contains_region(label.region), (label.id, label.region)
        rendered = [label.render_line(y).text for y in range(label.size.height)]
        assert _words(" ".join(rendered)) == _words(str(label.visual)), label.id


def test_expired_dialog_shows_the_whole_body_at_80x24(make_live_app, fake_azure) -> None:
    fake_azure.auth_err = EXPIRED_MSG

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SMALL) as pilot:
            modal = await _modal_ready(pilot)
            assert modal.kind == "expired"
            lines = _screen_lines(app)
            text = "\n".join(lines)
            assert "Azure session expired" in text
            assert any("Run az login in another terminal, then press Retry." in line for line in lines), text
            assert "restart fomo" not in text
            # The first line of the raw error, shortened; never the second line.
            message = " ".join(_label_lines(app, "#auth-error-message"))
            assert message.startswith("ERROR: AADSTS700082: The refresh token has expired due to inactivity.")
            assert message.endswith("…")
            assert "setup account" not in text
            assert any(all(b in line for b in ("Retry", "Dismiss", "Quit")) for line in lines), text
            _assert_fits(app)

    asyncio.run(scenario())


def test_mfa_from_the_session_check_explains_how_to_sign_in(make_live_app, fake_azure) -> None:
    fake_azure.auth_err = MFA_MSG

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SMALL) as pilot:
            modal = await _modal_ready(pilot)
            assert modal.kind == "mfa"
            title = " ".join(_label_lines(app, "#auth-error-title"))
            body = " ".join(_label_lines(app, "#auth-error-body"))
            assert title == "MFA or compliant device required"
            assert _words(body) == _words(
                "Your tenant requires MFA or a compliant device for this request. "
                "Run az login --scope https://management.azure.com/.default "
                "(or az login --tenant <id>), then Retry."
            )
            assert "expired" not in "\n".join(_screen_lines(app))
            _assert_fits(app)

    asyncio.run(scenario())


def test_dialog_message_is_literal(make_live_app, fake_azure) -> None:
    fake_azure.auth_err = "AADSTS700082: token [/] expired [bold]x[/bold]"

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SMALL) as pilot:
            await _modal_ready(pilot)
            message = app.screen.query_one("#auth-error-message", Label)
            assert str(message.visual) == "AADSTS700082: token [/] expired [bold]x[/bold]"

    asyncio.run(scenario())


def test_dialog_buttons_cycle_with_arrows_and_retry_has_focus(make_live_app, fake_azure) -> None:
    fake_azure.auth_err = EXPIRED_MSG

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SMALL) as pilot:
            await _modal_ready(pilot)
            seen = [app.focused.id if app.focused else None]
            for key in ("right", "right", "right", "left"):
                await pilot.press(key)
                seen.append(app.focused.id if app.focused else None)
            assert seen == [
                "auth-error-retry",
                "auth-error-ok",
                "auth-error-quit",
                "auth-error-retry",
                "auth-error-quit",
            ]

    asyncio.run(scenario())


def test_retry_reloads_account_and_subscriptions(make_live_app, fake_azure) -> None:
    fake_azure.auth_err = EXPIRED_MSG
    fake_azure.subs_err = EXPIRED_MSG

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SMALL) as pilot:
            await _modal_ready(pilot)
            scope = app.screen_stack[1]
            assert isinstance(scope, ScopeScreen)
            label = scope.query_one("#loading-label", Label)
            await wait_for(pilot, lambda: "session expired" in str(label.visual))
            # Both loaders failed, but they share one dialog.
            assert sum(isinstance(s, AuthErrorModal) for s in app.screen_stack) == 1
            assert "user@contoso.com" not in app.title

            fake_azure.auth_err = None
            fake_azure.subs_err = None
            await pilot.press("enter")  # Retry has the focus

            sub_list = scope.query_one("#sub-list", FomoSelectionList)
            await wait_for(pilot, lambda: "user@contoso.com" in app.title and sub_list.option_count == 2)
            assert not _has_modal(app)
            assert app.title.endswith("·  user@contoso.com  ·  Contoso")
            assert fake_azure.calls.count(("check_auth",)) == 2
            assert fake_azure.calls.count(("list_subscriptions",)) == 2

    asyncio.run(scenario())


def test_retry_after_login_reloads_an_empty_subscription_list(make_live_app, fake_azure) -> None:
    # Without a session, `az account list` succeeds with no subscriptions.
    fake_azure.auth_err = NOT_LOGGED_IN_MSG
    fake_azure.subs = []

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SMALL) as pilot:
            modal = await _modal_ready(pilot)
            assert modal.kind == "not_logged_in"
            assert "Not logged in to Azure" in "\n".join(_screen_lines(app))
            scope = app.screen_stack[1]
            assert isinstance(scope, ScopeScreen)
            await wait_for(pilot, lambda: ("list_subscriptions",) in fake_azure.calls)

            fake_azure.auth_err = None
            fake_azure.subs = make_subs()
            await pilot.press("r")

            sub_list = scope.query_one("#sub-list", FomoSelectionList)
            await wait_for(pilot, lambda: "user@contoso.com" in app.title and sub_list.option_count == 2)
            assert not _has_modal(app)

    asyncio.run(scenario())


def test_dismiss_closes_the_dialog_without_retrying(make_live_app, fake_azure) -> None:
    fake_azure.auth_err = EXPIRED_MSG

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SMALL) as pilot:
            await _modal_ready(pilot)
            await pilot.press("escape")
            await wait_for(pilot, lambda: isinstance(app.screen, ScopeScreen))
            await pilot.pause(0.1)
            assert fake_azure.calls.count(("check_auth",)) == 1
            assert app.return_code is None

    asyncio.run(scenario())


def test_roles_screen_retry_reloads_only_the_failed_subscriptions(make_live_app, fake_azure) -> None:
    fake_azure.roles_err["s1"] = EXPIRED_MSG

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE, notifications=True) as pilot:
            await _scope_ready(pilot)
            roles_screen = RolesScreen(["s1", "s2"])
            await app.push_screen(roles_screen)
            await _modal_ready(pilot)
            role_list = roles_screen.query_one("#role-list", FomoSelectionList)
            await wait_for(pilot, lambda: role_list.option_count > 0)
            assert _prompts(role_list) == ["Reader  —  s2"]
            assert sum(isinstance(s, AuthErrorModal) for s in app.screen_stack) == 1

            del fake_azure.roles_err["s1"]
            await pilot.press("enter")

            await wait_for(pilot, lambda: len(_prompts(role_list)) > 1)
            assert app.screen is roles_screen
            prompts = _prompts(role_list)
            assert "Reader  —  s1" in prompts
            assert "Reader  —  s2" in prompts
            assert fake_azure.calls.count(("list_eligible_roles", "s1")) == 2
            assert fake_azure.calls.count(("list_eligible_roles", "s2")) == 1
            assert not _toasts(app)

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Assignments: re-authentication hints and the r (reload) key
# ---------------------------------------------------------------------------


async def _open_assignments(pilot: Pilot) -> AssignmentsScreen:
    await _scope_ready(pilot)
    screen = AssignmentsScreen()
    await pilot.app.push_screen(screen)
    return screen


def test_assignments_r_reloads_both_tabs(make_live_app, fake_azure, monkeypatch) -> None:
    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE) as pilot:
            screen = await _open_assignments(pilot)
            azure_table = screen.query_one("#azure-table", DataTable)
            entra_table = screen.query_one("#entra-table", DataTable)
            await wait_for(pilot, lambda: azure_table.row_count == 1 and entra_table.row_count == 1)
            monkeypatch.setattr(azure, "_graph_token_cache", ("token", 9e9))
            fake_azure.arm_assignments.append(
                ActiveAssignment("Owner", "/subscriptions/s2", "Contoso Dev", None, "Activated")
            )

            await pilot.press("r")

            await wait_for(
                pilot,
                lambda: (
                    azure_table.row_count == 2
                    and fake_azure.calls.count(("list_active_entra_assignments",)) == 2
                    and entra_table.display
                ),
            )
            assert fake_azure.calls.count(("list_active_arm_assignments",)) == 2
            assert fake_azure.calls.count(("list_active_entra_assignments",)) == 2
            # The rows are replaced, not appended.
            assert entra_table.row_count == 1
            # The Entra tab had loaded, so its Graph access token is kept.
            assert azure._graph_token_cache == ("token", 9e9)

    asyncio.run(scenario())


def test_assignments_graph_scope_error_tells_how_to_sign_in_again(make_live_app, fake_azure, monkeypatch) -> None:
    fake_azure.entra_assignments_err = "Insufficient privileges to complete the operation."

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE) as pilot:
            screen = await _open_assignments(pilot)
            label = screen.query_one("#entra-loading", Label)
            await wait_for(pilot, lambda: "Missing Graph permissions" in str(label.visual))
            assert str(label.visual) == (
                "Missing Graph permissions.\n\n"
                "Sign in to Graph again: delete ~/.cache/fomo/graph_token.json and press r to retry."
            )
            # The user deletes the token cache; the access token in memory must go too.
            monkeypatch.setattr(azure, "_graph_token_cache", ("stale", 9e9))
            fake_azure.entra_assignments_err = None

            await pilot.press("r")

            entra_table = screen.query_one("#entra-table", DataTable)
            await wait_for(pilot, lambda: entra_table.display and entra_table.row_count == 1)
            assert str(label.visual) == "Entra assignments  (1 found)"
            assert azure._graph_token_cache is None

    asyncio.run(scenario())


def test_assignments_session_error_offers_r_to_retry(make_live_app, fake_azure, monkeypatch) -> None:
    failures = [NOT_LOGGED_IN_MSG]
    real = fake_azure.list_active_arm_assignments

    def _arm() -> list[ActiveAssignment]:
        if failures:
            raise RuntimeError(failures.pop())
        return real()

    monkeypatch.setattr(azure, "list_active_arm_assignments", _arm)

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE) as pilot:
            screen = await _open_assignments(pilot)
            label = screen.query_one("#azure-loading", Label)
            await wait_for(pilot, lambda: "session expired" in str(label.visual))
            assert str(label.visual) == (
                "Azure session expired.\n\nRun az login in another terminal, then press r to retry."
            )

            await pilot.press("r")

            azure_table = screen.query_one("#azure-table", DataTable)
            await wait_for(pilot, lambda: azure_table.display and azure_table.row_count == 1)
            assert str(label.visual) == "Azure assignments  (1 found)"

    asyncio.run(scenario())
