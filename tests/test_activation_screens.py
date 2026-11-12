"""Tests for the Azure and Entra activation screens.

They cover the behaviour shared through ``ActivationScreenBase``: failure rows,
the error log, error bookkeeping across the sub/global tables, the layout on
small terminals (F07), the keys of the reason field and the next steps after a
run (F10).  The layout and key tests run against the fake Azure boundary with
``dry_run=False``, so the fake ``activate_role`` records real (fake)
activations.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from textual.coordinate import Coordinate
from textual.pilot import Pilot
from textual.screen import Screen
from textual.widgets import Button, DataTable, Input, RichLog, Select

from fomo import app as app_module
from fomo.app import PimApp
from fomo.azure import EligibleRole, EntraEligibleRole
from fomo.screens._activation_base import (
    ActivationScreenBase,
    Outcome,
    fit_column_widths,
    status_outcome,
    summarize_activation_error,
    summarize_outcomes,
)
from fomo.screens.activation_screen import ActivationScreen
from fomo.screens.assignments_screen import AssignmentsScreen
from fomo.screens.entra_screen import EntraActivationScreen
from fomo.screens.roles_screen import RolesScreen
from fomo.screens.scope_screen import ScopeScreen
from fomo.widgets import FomoSelectionList
from tests.test_tui_markup import _rendered, _toasts
from tests.test_tui_smoke import SIZE, _status_cells, wait_for

SUB = "/subscriptions/11111111-1111-1111-1111-111111111111"
MG = "/providers/Microsoft.Management/managementGroups/root"
LONG_SCOPE = "rg-platform-networking-prod-westeurope"


@pytest.fixture
def make_app(monkeypatch: pytest.MonkeyPatch) -> Callable[..., PimApp]:
    """Demo-mode PimApp with theme detection and the dbus watcher stubbed, animations off."""
    monkeypatch.setattr(app_module, "_system_is_dark", lambda: True)
    monkeypatch.setattr(PimApp, "_watch_color_scheme", lambda self: None)

    def _make(**kw: Any) -> PimApp:
        app = PimApp(demo_mode=True, dry_run=True, **kw)
        app.animation_level = "none"
        return app

    return _make


@pytest.fixture
def make_live_app(monkeypatch: pytest.MonkeyPatch, fake_azure: Any) -> Callable[[], PimApp]:
    """PimApp on the fake Azure boundary with dry run off, animations off."""
    monkeypatch.setattr(app_module, "_system_is_dark", lambda: True)
    monkeypatch.setattr(PimApp, "_watch_color_scheme", lambda self: None)

    def _make() -> PimApp:
        app = PimApp(demo_mode=False, dry_run=False)
        app.animation_level = "none"
        return app

    return _make


def _arm(name: str, scope: str, disp: str = "disp") -> EligibleRole:
    return EligibleRole(name, f"{scope}/providers/x/roleDefinitions/{name}", scope, disp, "u", "s", None)


def _entra(name: str) -> EntraEligibleRole:
    return EntraEligibleRole(name, name.lower(), "u", "s", None)


FIVE_ROLES = [
    _arm(name, SUB, LONG_SCOPE)
    for name in ("Owner", "Storage Blob Data Contributor", "Contributor", "Key Vault Administrator", "Reader")
]


async def _open(pilot: Pilot, screen: Screen) -> None:
    """Push *screen* over the scope screen and wait until the reason field has focus."""
    app = pilot.app
    await wait_for(pilot, lambda: isinstance(app.screen, ScopeScreen))
    await app.push_screen(screen)
    await wait_for(pilot, lambda: isinstance(app.focused, Input))


async def _wait_done(pilot: Pilot, screen: Screen) -> None:
    await wait_for(pilot, lambda: str(screen.query_one("#btn-back", Button).label) == "Done")


def _assert_fully_on_screen(screen: Screen, *selectors: str) -> None:
    """Each widget is laid out, not clipped by its containers, and inside the screen."""
    for selector in selectors:
        geometry = screen.find_widget(screen.query_one(selector))
        assert geometry.region.height > 0, selector
        assert geometry.region.intersection(geometry.clip) == geometry.region, (selector, geometry)
        assert screen.region.contains_region(geometry.region), (selector, geometry)


def test_azure_activation_failure_rows_and_error_log(make_app, fake_azure) -> None:
    fake_azure.fail_on = {"Reader", "Owner"}
    roles = [_arm("Reader", SUB), _arm("Contributor", SUB), _arm("Owner", MG)]

    async def scenario() -> None:
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            await wait_for(pilot, lambda: isinstance(app.screen, ScopeScreen))
            app.push_screen(ActivationScreen(roles))
            await wait_for(pilot, lambda: isinstance(app.screen, ActivationScreen))
            screen = app.screen
            assert isinstance(screen, ActivationScreen)
            await pilot.press(*"why")
            await pilot.click("#btn-activate")
            await wait_for(pilot, lambda: str(screen.query_one("#btn-back", Button).label) == "Done")

            sub_cells = _status_cells(screen.query_one("#roles-table", DataTable), 3)
            global_cells = _status_cells(screen.query_one("#global-roles-table", DataTable), 3)
            assert sub_cells == ["✗ ERROR: (Boom) Reader failed", "✓ DryRun"]
            assert global_cells == ["✗ ERROR: (Boom) Owner failed"]
            # Global rows are keyed after the subscription rows.
            assert screen._errors == {0: "ERROR: (Boom) Reader failed", 2: "ERROR: (Boom) Owner failed"}
            error_log = screen.query_one("#error-log", RichLog)
            assert not error_log.has_class("hidden")
            assert len(error_log.lines) > 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("screen_cls", "roles"),
    [
        (ActivationScreen, [_arm("Reader", SUB)]),
        (EntraActivationScreen, [_entra("Global Reader")]),
    ],
    ids=["azure", "entra"],
)
def test_duration_can_never_be_blank(make_app, fake_azure, screen_cls, roles) -> None:
    async def scenario() -> None:
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            await wait_for(pilot, lambda: isinstance(app.screen, ScopeScreen))
            app.push_screen(screen_cls(roles))
            await wait_for(pilot, lambda: isinstance(app.focused, Input))
            screen = app.screen
            duration = screen.query_one("#duration", Select)

            # No blank row: every option is a real ISO 8601 duration.
            assert duration._allow_blank is False
            assert Select.NULL not in [value for _, value in duration._options]
            assert duration.value == "PT1H"

            # Keyboard: Tab in the justification focuses the duration.  Open
            # the menu and pick its top row, where the blank row used to be.
            await pilot.press(*"why", "tab")
            await wait_for(pilot, lambda: app.focused is duration)
            await pilot.press("enter")
            await wait_for(pilot, lambda: duration.expanded)
            await pilot.press("home", "enter")
            await wait_for(pilot, lambda: not duration.expanded)
            assert duration.value == "PT30M"
            assert not duration.is_blank()

            await pilot.click("#btn-activate")
            await wait_for(pilot, lambda: str(screen.query_one("#btn-back", Button).label) == "Done")
            assert [d for _, _, d, _ in fake_azure.activations] == ["PT30M"]

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Layout on small terminals (F07)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("available", "natural", "expected"),
    [
        # Room to spare: nothing shrinks and Status takes the rest.
        (100, [29, 38, 4, 17], [29, 38, 4, 29]),
        # Scope gives way first, down to its minimum.
        (60, [29, 38, 4, 17], [29, 10, 4, 17]),
        # Then Role.
        (50, [29, 38, 4, 17], [19, 10, 4, 17]),
        # Then Status is cut, but never below one cell.
        (40, [29, 38, 4, 17], [16, 10, 4, 10]),
        (20, [29, 38, 4, 17], [16, 10, 4, 1]),
    ],
)
def test_fit_column_widths(available: int, natural: list[int], expected: list[int]) -> None:
    assert fit_column_widths(available, natural, ((1, 10), (0, 16))) == expected


def test_form_stays_on_screen_at_80x24_and_duration_keeps_its_height(make_live_app, fake_azure) -> None:
    fake_azure.fail_on = {"Owner", "Contributor"}

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=(80, 24)) as pilot:
            screen = ActivationScreen(FIVE_ROLES)
            await _open(pilot, screen)
            await pilot.pause()
            _assert_fully_on_screen(screen, "#justification", "#duration", "#btn-activate", "#btn-back")

            screen.query_one("#justification", Input).value = "why"
            await pilot.click("#btn-activate")
            await _wait_done(pilot, screen)
            await pilot.pause()
            assert [name for name, *_ in fake_azure.activations] == [r.role_name for r in FIVE_ROLES]
            assert not screen.query_one("#error-log").has_class("hidden")
            _assert_fully_on_screen(screen, "#justification", "#duration", "#error-log", "#btn-activate", "#btn-back")

            # Status stays in view: the table never scrolls sideways, Scope gives way with "…".
            table = screen.query_one("#roles-table", DataTable)
            assert table.virtual_size.width <= table.scrollable_content_region.width
            rendered = _rendered(table)
            assert "Status" in rendered
            assert "✓ Provisioned" in rendered
            assert LONG_SCOPE not in rendered
            assert LONG_SCOPE[:8] in rendered
            assert "…" in rendered

            await pilot.resize_terminal(120, 36)
            await wait_for(pilot, lambda: screen.size.width == 120)
            await pilot.pause()
            _assert_fully_on_screen(screen, "#justification", "#duration", "#error-log", "#btn-activate")
            assert screen.query_one("#duration").region.height >= 3

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Status cells and error details (F36)
# ---------------------------------------------------------------------------

ARM_EXPIRY = (
    "ERROR: (RoleAssignmentRequestPolicyValidationFailed) The following policy rules failed: "
    '["ExpirationRule"]. The requested duration of PT8H exceeds the maximum allowed PT4H.'
)
GRAPH_EXPIRY = (
    'The following policy rules failed: ["ExpirationRule"]. '
    "The requested activation duration exceeds the maximum allowed PT4H for this role."
)


@pytest.mark.parametrize(
    ("message", "short"),
    [
        (ARM_EXPIRY, "Exceeds max duration (PT4H)"),
        (GRAPH_EXPIRY, "Exceeds max duration (PT4H)"),
        ("Policy says: MaximumDuration PT30M; ExpirationRule failed", "Exceeds max duration (PT30M)"),
        ('The following policy rules failed: ["ExpirationRule"]', "Exceeds max duration"),
        ('The following policy rules failed: ["JustificationRule"]', "Justification rejected by policy"),
        ('The following policy rules failed: ["MfaRule"]', "MFA required"),
        ("MFA is required to activate this role", "MFA required"),
        ("ERROR: (RoleAssignmentExists) The Role assignment already exists.", "Already active"),
        ("The role assignment Already Exists.", "Already active"),
        ("ERROR: (AuthorizationFailed) The client 'x' does not have authorization", "Not authorized"),
        ("ERROR: (Boom) Reader failed", "ERROR: (Boom) Reader failed"),
        # Anything else: the first 40 characters.
        ("ERROR: (InternalServerError) An unexpected error in PIM", "ERROR: (InternalServerError) An unexpect…"),
        ("\n  ERROR: (Boom) first line  \nCode: Boom\n", "ERROR: (Boom) first line"),
        ("", "Failed"),
        # Not MFA: the word only counts in capitals and on its own.
        ("Amfax said no", "Amfax said no"),
    ],
)
def test_summarize_activation_error(message: str, short: str) -> None:
    assert summarize_activation_error(message) == short


def test_entra_failure_shows_short_status_and_wrapped_details_at_80x24(make_live_app, fake_azure) -> None:
    fake_azure.fail_messages = {"Global Reader": GRAPH_EXPIRY}
    roles = [_entra(name) for name in ("Global Reader", "Security Reader", "Reports Reader")]

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=(80, 24)) as pilot:
            screen = EntraActivationScreen(roles)
            await _open(pilot, screen)
            screen.query_one("#justification", Input).value = "why"
            await pilot.click("#btn-activate")
            await _wait_done(pilot, screen)
            await pilot.pause()

            table = screen.query_one("#roles-table", DataTable)
            assert _status_cells(table, 2) == ["✗ Exceeds max duration (PT4H)", "✓ Provisioned", "✓ Provisioned"]
            assert screen._errors == {0: GRAPH_EXPIRY}
            failed = table.get_cell_at(Coordinate(0, 2))
            assert "red" in str(failed.style)
            assert "green" in str(table.get_cell_at(Coordinate(1, 2)).style)
            assert "✗ Exceeds max duration (PT4H)" in _rendered(table)

            # The full message, word for word, wrapped to the panel's width.
            error_log = screen.query_one("#error-log", RichLog)
            await wait_for(pilot, lambda: len(error_log.lines) >= 3)
            lines = [strip.text for strip in error_log.lines]
            assert lines[0] == "✗ Global Reader"
            assert len([line for line in lines if line.strip()]) >= 3  # the message wraps
            for word in GRAPH_EXPIRY.split():
                assert any(word in line for line in lines), (word, lines)
            assert max(strip.cell_length for strip in error_log.lines) <= error_log.scrollable_content_region.width
            _assert_fully_on_screen(screen, "#justification", "#duration", "#error-log")

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Keys in the reason field
# ---------------------------------------------------------------------------


def test_enter_in_reason_activates_unless_it_is_blank(make_live_app, fake_azure) -> None:
    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE, notifications=True) as pilot:
            screen = ActivationScreen([_arm("Reader", SUB)])
            await _open(pilot, screen)
            reason = screen.query_one("#justification", Input)

            # A blank (whitespace-only) reason only warns.
            await pilot.press("space", "enter")
            await wait_for(pilot, lambda: "Justification is required." in _toasts(app))
            assert fake_azure.activations == []
            assert app.focused is reason
            assert not screen.query_one("#btn-activate", Button).disabled

            await pilot.press("x", "enter")
            await _wait_done(pilot, screen)
            assert fake_azure.activations == [("Reader", SUB, "PT1H", False)]
            assert fake_azure.justifications == ["x"]

            # Once the run is over, Enter in the reason doesn't submit again.
            reason.focus()
            await pilot.press("enter")
            await pilot.pause()
            assert len(fake_azure.activations) == 1

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Escape and q (F32): the same rule on both screens
# ---------------------------------------------------------------------------


def _both_screens() -> list[Screen]:
    return [ActivationScreen([_arm("Reader", SUB)]), EntraActivationScreen([_entra("Global Reader")])]


def test_escape_leaves_a_filled_reason_first_then_goes_back(make_live_app, fake_azure) -> None:
    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE) as pilot:
            for screen in _both_screens():
                await _open(pilot, screen)
                reason = screen.query_one("#justification", Input)
                await pilot.press("q")  # typed into the reason, not Back
                assert reason.value == "q"
                assert app.screen is screen

                await pilot.press("escape")
                assert app.screen is screen, type(screen).__name__
                assert not isinstance(app.focused, Input)
                assert reason.value == "q"

                await pilot.press("escape")
                await wait_for(pilot, lambda: isinstance(app.screen, ScopeScreen))
            assert fake_azure.activations == []

    asyncio.run(scenario())


def test_escape_and_q_go_back_when_not_typing(make_live_app, fake_azure) -> None:
    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE) as pilot:
            for screen in _both_screens():
                # An empty reason: Escape goes straight back.
                await _open(pilot, screen)
                await pilot.press("escape")
                await wait_for(pilot, lambda: isinstance(app.screen, ScopeScreen))

            azure_screen, entra_screen = _both_screens()

            # Escape in the open Duration menu only closes the menu (Entra's
            # Escape used to be a priority binding that left the screen).
            await _open(pilot, entra_screen)
            duration = entra_screen.query_one("#duration", Select)
            await pilot.press("tab", "enter")
            await wait_for(pilot, lambda: duration.expanded)
            await pilot.press("escape")
            await wait_for(pilot, lambda: not duration.expanded)
            assert app.screen is entra_screen
            await pilot.press("q")
            await wait_for(pilot, lambda: isinstance(app.screen, ScopeScreen))

            # q goes back from the Azure screen too (it used to do nothing there).
            await _open(pilot, azure_screen)
            await pilot.press("tab", "q")
            await wait_for(pilot, lambda: isinstance(app.screen, ScopeScreen))
            assert fake_azure.activations == []

            # Once a run has finished, q quits (F10).
            screen = ActivationScreen([_arm("Reader", SUB)])
            await _open(pilot, screen)
            screen.query_one("#justification", Input).value = "why"
            await pilot.press("enter")
            await _wait_done(pilot, screen)
            await pilot.press("q")
            await wait_for(pilot, lambda: app.return_code == 0)

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# After a run (F10): summary, retry failed, assignments, Done
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "outcome", "cell"),
    [
        ("Provisioned", Outcome.ACTIVATED, "✓ Provisioned"),
        ("Granted", Outcome.ACTIVATED, "✓ Granted"),
        ("DryRun", Outcome.SIMULATED, "✓ DryRun"),
        ("PendingApproval", Outcome.PENDING_APPROVAL, "⏳ PendingApproval"),
        ("PendingApprovalProvisioning", Outcome.PENDING_APPROVAL, "⏳ PendingApprovalProvisioning"),
        ("PendingAdminDecision", Outcome.PENDING_APPROVAL, "⏳ PendingAdminDecision"),
        ("PendingProvisioning", Outcome.PENDING, "⏳ PendingProvisioning"),
        ("Accepted", Outcome.PENDING, "⏳ Accepted"),
        ("ScheduleCreated", Outcome.PENDING, "⏳ ScheduleCreated"),
        ("Denied", Outcome.FAILED, "✗ Denied"),
        ("TimedOut", Outcome.FAILED, "✗ TimedOut"),
        ("Submitted", Outcome.SUBMITTED, "Submitted"),
    ],
)
def test_status_outcome_and_cell(status: str, outcome: Outcome, cell: str) -> None:
    assert status_outcome(status) is outcome
    assert str(ActivationScreenBase._format_status(status)) == cell


A, D, PA, P, S, F = (
    Outcome.ACTIVATED,
    Outcome.SIMULATED,
    Outcome.PENDING_APPROVAL,
    Outcome.PENDING,
    Outcome.SUBMITTED,
    Outcome.FAILED,
)


@pytest.mark.parametrize(
    ("outcomes", "text", "severity"),
    [
        ([F, A, PA, A], "2 activated · 1 pending approval · 1 failed", "error"),
        ([F, F], "2 failed", "error"),
        ([A, PA], "1 activated · 1 pending approval", "warning"),
        ([P, A], "1 activated · 1 pending", "warning"),
        ([A, A, A], "3 activated", "information"),
        ([D, D], "2 activated (dry run)", "information"),
        ([S, A], "1 activated · 1 submitted", "information"),
    ],
)
def test_summarize_outcomes(outcomes: list[Outcome], text: str, severity: str) -> None:
    assert summarize_outcomes(outcomes) == (text, severity)


def test_retry_failed_assignments_and_done_after_a_run(make_live_app, fake_azure) -> None:
    fake_azure.fail_on = {"Key Vault Reader"}

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE, notifications=True) as pilot:
            await wait_for(pilot, lambda: isinstance(app.screen, ScopeScreen))
            scope = app.screen
            sub_list = scope.query_one("#sub-list", FomoSelectionList)
            await wait_for(pilot, lambda: sub_list.option_count == 2)
            sub_list.select("s1")
            await wait_for(pilot, lambda: scope._selected_ids == {"s1"})

            # Roles screen: select Reader and Key Vault Reader on s1, proceed.
            roles_screen = RolesScreen(["s1"])
            await app.push_screen(roles_screen)
            role_list = roles_screen.query_one("#role-list", FomoSelectionList)
            await wait_for(pilot, lambda: role_list.option_count > 0)
            for index, role in enumerate(roles_screen.all_roles):
                if role.role_name in ("Reader", "Key Vault Reader") and not role.is_global:
                    role_list.select(index)
            roles_screen.action_proceed()
            await wait_for(pilot, lambda: app.focused is app.screen.query_one("#justification"))
            screen = app.screen
            assert isinstance(screen, ActivationScreen)
            assert {"r", "i"}.isdisjoint(screen.active_bindings)  # only after a run

            screen.query_one("#justification", Input).value = "why"
            await pilot.press("enter")
            await _wait_done(pilot, screen)
            # In the roles list's order (by name), not the order they were loaded in.
            assert [name for name, *_ in fake_azure.activations] == ["Key Vault Reader", "Reader"]
            await wait_for(pilot, lambda: "1 activated · 1 failed — see Details below." in _toasts(app))
            btn_activate = screen.query_one("#btn-activate", Button)
            assert str(btn_activate.label) == "Retry failed (1)"
            assert not btn_activate.disabled
            actions = {key: active.binding.action for key, active in screen.active_bindings.items()}
            assert {key: actions.get(key) for key in ("enter", "r", "i", "q")} == {
                "enter": "done",
                "r": "retry_failed",
                "i": "assignments",
                "q": "quit_app",
            }

            # r retries only the failed role.
            fake_azure.fail_on = set()
            await pilot.press("r")
            await wait_for(pilot, lambda: len(fake_azure.activations) == 3 and not screen._activating)
            assert fake_azure.activations[2] == ("Key Vault Reader", "/subscriptions/s1", "PT1H", False)
            assert _status_cells(screen.query_one("#roles-table", DataTable), 3) == ["✓ Provisioned"] * 2
            await wait_for(pilot, lambda: "2 activated" in _toasts(app))
            assert btn_activate.disabled
            assert "r" not in screen.active_bindings
            assert screen.query_one("#error-log").has_class("hidden")

            # i shows the active assignments, loaded afresh.
            await pilot.press("i")
            await wait_for(pilot, lambda: isinstance(app.screen, AssignmentsScreen))
            await wait_for(pilot, lambda: ("list_active_arm_assignments",) in fake_azure.calls)
            await app.pop_screen()
            await wait_for(pilot, lambda: app.focused is screen.query_one("#btn-back"))

            # Enter (Done) returns to the scope screen, discarding the roles
            # screen; the subscription selection is kept.
            await pilot.press("enter")
            await wait_for(pilot, lambda: app.screen is scope)
            await wait_for(pilot, lambda: roles_screen not in app.screen_stack)
            assert scope._selected_ids == {"s1"}
            assert sub_list.selected == ["s1"]
            assert len(fake_azure.activations) == 3

    asyncio.run(scenario())
