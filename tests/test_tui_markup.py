"""External text renders literally in the TUI (F01).

Subscription, role and scope names, Azure and Graph error messages and the
third-party tiering text used to be interpolated into Textual markup.  A name
such as ``Broken [/] sub`` crashed fomo at start-up, and ``[legacy]`` or
``[red]`` silently disappeared from names.  These tests run against the fake
Azure boundary with ``demo_mode=False`` and ``dry_run=True``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from textual.pilot import Pilot
from textual.widget import Widget
from textual.widgets import Button, DataTable, Label, RichLog

from fomo import app as app_module
from fomo import azure, tiering
from fomo.app import PimApp
from fomo.azure import (
    ActiveAssignment,
    ActiveEntraAssignment,
    EligibleRole,
    EntraEligibleRole,
    Subscription,
)
from fomo.screens._common import device_code_markup, safe_markup
from fomo.screens.activation_screen import ActivationScreen
from fomo.screens.assignments_screen import AssignmentsScreen
from fomo.screens.entra_screen import EntraActivationScreen
from fomo.screens.roles_screen import RolesScreen
from fomo.screens.scope_screen import ScopeScreen
from fomo.widgets import FomoSelectionList
from tests.test_tui_smoke import SIZE, _prompts, _status_cells, wait_for

TRICKY = ["[/]", "[bold]x[/bold]", "[legacy]", "\\", "a\\", "[Legacy]", "[ x ]", "[$var]", "a\\[b]", "$name"]

SUB_NAMES = ["Broken [/] sub", "Plain [bold]sub[/bold] name [legacy]", "Team [red] sandbox"]

KVA = EligibleRole(
    "Key Vault Administrator [preview]",
    "/subscriptions/s1/providers/Microsoft.Authorization/roleDefinitions/kva",
    "/subscriptions/s1/resourceGroups/rg-[x]",
    "rg-[x]",
    "u",
    "sched",
    "2030-01-31T00:00:00Z",
)
TIER_TEXT = "Assign roles at [/subscriptions/*] scope"


@pytest.fixture
def make_live_app(monkeypatch: pytest.MonkeyPatch, fake_azure: Any) -> Callable[[], PimApp]:
    """PimApp on the fake Azure boundary: not demo mode, dry run on."""
    monkeypatch.setattr(app_module, "_system_is_dark", lambda: True)
    monkeypatch.setattr(PimApp, "_watch_color_scheme", lambda self: None)
    return lambda: PimApp(demo_mode=False, dry_run=True)


def _serve_tiering(monkeypatch: pytest.MonkeyPatch, guid: str) -> None:
    """Serve one Tier 0 entry for *guid*, whose attack path is TIER_TEXT, as Azure and Entra data."""
    item = {"id": guid, "tier": "0", "assetName": f"{guid} [legacy]", "shortestPath": TIER_TEXT}
    monkeypatch.setattr(tiering, "_fetch_json", lambda url: [dict(item)])


def _text(label: Label) -> str:
    """Plain text a Label currently shows."""
    return str(label.visual)


def _rendered(widget: Widget) -> str:
    """Text of every rendered line of *widget*."""
    return "\n".join(widget.render_line(y).text for y in range(widget.size.height))


def _toasts(app: PimApp) -> list[str]:
    return [str(toast.render()) for toast in app.screen.query("Toast")]


async def _select_first_and_proceed(pilot: Pilot, selection_list: FomoSelectionList) -> None:
    selection_list.focus()
    selection_list.highlighted = 0
    await pilot.pause()
    await pilot.press("x")
    await wait_for(pilot, lambda: len(selection_list.selected) == 1)
    await pilot.press("enter")


async def _scope_ready(pilot: Pilot) -> ScopeScreen:
    await wait_for(pilot, lambda: isinstance(pilot.app.screen, ScopeScreen))
    screen = pilot.app.screen
    assert isinstance(screen, ScopeScreen)
    return screen


# ---------------------------------------------------------------------------
# The helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", TRICKY)
def test_safe_markup_inserts_values_literally(value: str) -> None:
    assert safe_markup("$v", v=value).plain == value
    content = safe_markup("[bold red]Error:[/bold red] $v [dim]tail[/dim]", v=value)
    assert content.plain == f"Error: {value} tail"
    # The template's own markup still applies.
    assert any(span.start == 0 and span.end == len("Error:") for span in content.spans)


def test_device_code_markup_is_literal() -> None:
    content = device_code_markup("https://example.test/[x]", "AB[/]CD")
    assert content.plain == (
        "Sign in to Microsoft Graph\n\n"
        "1. Open:  https://example.test/[x]\n"
        "2. Enter code:  AB[/]CD\n\n"
        "Waiting for authentication…"
    )


# ---------------------------------------------------------------------------
# Scope screen
# ---------------------------------------------------------------------------


def test_subscription_names_render_verbatim(make_live_app, fake_azure) -> None:
    fake_azure.subs = [Subscription(f"s{i}", name) for i, name in enumerate(SUB_NAMES)]

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE) as pilot:
            screen = await _scope_ready(pilot)
            sub_list = screen.query_one("#sub-list", FomoSelectionList)
            await wait_for(pilot, lambda: sub_list.option_count == 3)
            await pilot.pause()
            prompts = _prompts(sub_list)
            rendered = _rendered(sub_list)
            for i, name in enumerate(SUB_NAMES):
                assert f"{name}  s{i}" in prompts
                assert name in rendered
            assert app.return_code is None

    asyncio.run(scenario())


def test_account_user_and_tenant_render_verbatim_in_title(make_live_app, monkeypatch) -> None:
    monkeypatch.setattr(azure, "get_account_info", lambda: ("user [/]", "Contoso [legacy]"))

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE) as pilot:
            await _scope_ready(pilot)
            await wait_for(pilot, lambda: app.title.endswith("Contoso [legacy]"))
            await pilot.pause()
            header_title = app.screen.query_one("HeaderTitle")
            assert "[DRY RUN]  ·  user [/]  ·  Contoso [legacy]" in _rendered(header_title)

    asyncio.run(scenario())


def test_subscription_load_error_renders_verbatim(make_live_app, fake_azure) -> None:
    fake_azure.subs_err = RuntimeError("bad [/] thing")

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE) as pilot:
            screen = await _scope_ready(pilot)
            label = screen.query_one("#loading-label", Label)
            await wait_for(pilot, lambda: "Error:" in _text(label))
            assert "Error: bad [/] thing\n" in _text(label)
            assert app.return_code is None

    asyncio.run(scenario())


def test_entra_list_and_detail_render_verbatim(make_live_app, fake_azure, monkeypatch) -> None:
    fake_azure.entra = [EntraEligibleRole("Global Reader [legacy]", "gr", "u", "e1", None)]
    _serve_tiering(monkeypatch, "gr")

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE) as pilot:
            screen = await _scope_ready(pilot)
            screen.action_next_tab()
            entra_list = screen.query_one("#entra-role-list", FomoSelectionList)
            await wait_for(pilot, lambda: entra_list.option_count == 1)
            assert _prompts(entra_list) == ["Global Reader [legacy] - Permanent"]
            detail = _text(screen.query_one("#entra-detail", Label))
            assert "Global Reader [legacy]" in detail
            assert TIER_TEXT in detail

    asyncio.run(scenario())


def test_entra_load_error_renders_verbatim(make_live_app, fake_azure) -> None:
    fake_azure.entra_err = RuntimeError("Graph [/] failed")

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE) as pilot:
            screen = await _scope_ready(pilot)
            screen.action_next_tab()
            label = screen.query_one("#entra-loading-label", Label)
            await wait_for(pilot, lambda: "Error:" in _text(label))
            assert _text(label).endswith("Graph [/] failed")
            assert app.return_code is None

    asyncio.run(scenario())


def test_entra_blast_radius_toast_renders_tier_text_verbatim(make_live_app, fake_azure, monkeypatch) -> None:
    fake_azure.entra = [EntraEligibleRole("Global Reader", "gr", "u", "e1", None)]
    _serve_tiering(monkeypatch, "gr")

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE, notifications=True) as pilot:
            screen = await _scope_ready(pilot)
            screen.action_next_tab()
            entra_list = screen.query_one("#entra-role-list", FomoSelectionList)
            await wait_for(pilot, lambda: entra_list.option_count == 1)
            await _select_first_and_proceed(pilot, entra_list)
            await wait_for(pilot, lambda: isinstance(app.screen, EntraActivationScreen))
            await wait_for(pilot, lambda: _toasts(app))
            assert _toasts(app) == [f"Blast-radius warning: 1 high-risk role(s) selected\n🔴 gr [legacy]: {TIER_TEXT}"]

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Roles screen
# ---------------------------------------------------------------------------


def test_roles_screen_renders_role_scope_and_tier_text_verbatim(make_live_app, fake_azure, monkeypatch) -> None:
    fake_azure.roles = {"s1": [KVA]}
    _serve_tiering(monkeypatch, "kva")

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE) as pilot:
            await _scope_ready(pilot)
            screen = RolesScreen(["s1"])
            await app.push_screen(screen)
            role_list = screen.query_one("#role-list", FomoSelectionList)
            await wait_for(pilot, lambda: role_list.option_count == 1)
            assert _prompts(role_list) == ["Key Vault Administrator [preview]  —  rg-[x]  [expires 2030-01-31]"]
            detail = _text(screen.query_one("#detail", Label))
            assert "Key Vault Administrator [preview]" in detail
            assert "rg-[x]" in detail
            assert TIER_TEXT in detail
            assert app.return_code is None

    asyncio.run(scenario())


def test_roles_load_error_toast_renders_verbatim(make_live_app, fake_azure, monkeypatch) -> None:
    def _fail(subscription_id: str) -> list[EligibleRole]:
        raise RuntimeError("bad [/] thing")

    monkeypatch.setattr(azure, "list_eligible_roles", _fail)

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE, notifications=True) as pilot:
            await _scope_ready(pilot)
            await app.push_screen(RolesScreen(["abcdef12-0000"]))
            await wait_for(pilot, lambda: _toasts(app))
            assert "[abcdef12…] bad [/] thing" in _toasts(app)
            assert app.return_code is None

    asyncio.run(scenario())


def test_azure_blast_radius_toast_renders_tier_text_verbatim(make_live_app, fake_azure, monkeypatch) -> None:
    fake_azure.roles = {"s1": [KVA]}
    _serve_tiering(monkeypatch, "kva")

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE, notifications=True) as pilot:
            await _scope_ready(pilot)
            screen = RolesScreen(["s1"])
            await app.push_screen(screen)
            role_list = screen.query_one("#role-list", FomoSelectionList)
            await wait_for(pilot, lambda: role_list.option_count == 1)
            await _select_first_and_proceed(pilot, role_list)
            await wait_for(pilot, lambda: isinstance(app.screen, ActivationScreen))
            await wait_for(pilot, lambda: _toasts(app))
            assert _toasts(app) == [f"Blast-radius warning: 1 high-risk role(s) selected\n🔴 kva [legacy]: {TIER_TEXT}"]

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Activation screen
# ---------------------------------------------------------------------------


def test_activation_failure_renders_verbatim(make_live_app, fake_azure, monkeypatch) -> None:
    def _fail(role: EligibleRole, justification: str, duration: str, dry_run: bool = False) -> dict:
        raise RuntimeError("ERROR: [/x] (Boom)")

    monkeypatch.setattr(azure, "activate_role", _fail)

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE) as pilot:
            await _scope_ready(pilot)
            screen = ActivationScreen([KVA])
            await app.push_screen(screen)
            table = screen.query_one("#roles-table", DataTable)
            await pilot.pause()
            assert "Key Vault Administrator [preview]" in _rendered(table)
            assert "rg-[x]" in _rendered(table)

            await pilot.press(*"why")
            await pilot.click("#btn-activate")
            await wait_for(pilot, lambda: str(screen.query_one("#btn-back", Button).label) == "Done")
            assert _status_cells(table, 3) == ["✗ ERROR: [/x] (Boom)"]
            await pilot.pause()
            assert "✗ ERROR: [/x] (Boom)" in _rendered(table)

            error_log = screen.query_one("#error-log", RichLog)
            await wait_for(pilot, lambda: len(error_log.lines) >= 2)
            lines = [strip.text for strip in error_log.lines]
            assert lines[0] == "✗ Key Vault Administrator [preview]"
            assert lines[1] == "ERROR: [/x] (Boom)"
            assert app.return_code is None

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Assignments screen
# ---------------------------------------------------------------------------


def test_assignments_tables_render_verbatim_and_sort(make_live_app, fake_azure) -> None:
    fake_azure.arm_assignments = [
        ActiveAssignment("Reader [/]", "/subscriptions/s1", "rg-[x]", None, "Activated"),
        ActiveAssignment("Owner [legacy]", "/subscriptions/s1", "Team [red] sandbox", None, "Assigned"),
    ]
    fake_azure.entra_assignments = [ActiveEntraAssignment("Global [bold]Reader", "/[x]", None, "Activated")]

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE) as pilot:
            await _scope_ready(pilot)
            screen = AssignmentsScreen()
            await app.push_screen(screen)
            azure_table = screen.query_one("#azure-table", DataTable)
            entra_table = screen.query_one("#entra-table", DataTable)
            await wait_for(pilot, lambda: azure_table.row_count == 2 and entra_table.row_count == 1)
            await pilot.pause()
            assert _status_cells(azure_table, 0) == ["Owner [legacy]", "Reader [/]"]
            assert _status_cells(azure_table, 1) == ["Team [red] sandbox", "rg-[x]"]
            assert _status_cells(entra_table, 0) == ["Global [bold]Reader"]
            assert _status_cells(entra_table, 1) == ["/[x]"]
            rendered = _rendered(azure_table)
            assert "Reader [/]" in rendered
            assert "Team [red] sandbox" in rendered

            azure_table.focus()
            await pilot.press("1")
            await pilot.press("1")
            await pilot.pause()
            assert _status_cells(azure_table, 0) == ["Reader [/]", "Owner [legacy]"]
            assert app.return_code is None

    asyncio.run(scenario())


def test_assignments_errors_render_verbatim(make_live_app, fake_azure, monkeypatch) -> None:
    def _arm_fail() -> list[ActiveAssignment]:
        raise RuntimeError("arm [/] failed")

    def _entra_fail(**_: Any) -> list[ActiveEntraAssignment]:
        raise RuntimeError("graph [/] failed")

    monkeypatch.setattr(azure, "list_active_arm_assignments", _arm_fail)
    monkeypatch.setattr(azure, "list_active_entra_assignments", _entra_fail)

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE) as pilot:
            await _scope_ready(pilot)
            screen = AssignmentsScreen()
            await app.push_screen(screen)
            arm_label = screen.query_one("#azure-loading", Label)
            entra_label = screen.query_one("#entra-loading", Label)
            await wait_for(pilot, lambda: "Error:" in _text(arm_label) and "Error:" in _text(entra_label))
            assert _text(arm_label) == "Error: arm [/] failed"
            assert _text(entra_label) == "Error:\n\ngraph [/] failed"
            assert app.return_code is None

    asyncio.run(scenario())
