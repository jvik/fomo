"""Time left on active roles and assignments (F33).

Active roles show how long their activation still runs ("● active · 47m
left"), eligible roles when their eligibility ends ("eligible until
2026-12-31"), and the Assignments screen shows near expiries as a local time
plus the time left, sorted by the time itself.  The Entra directory scope "/"
reads "Directory".
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from textual.widgets import DataTable

from fomo import azure, timefmt
from fomo.azure import ActiveAssignment, ActiveEntraAssignment, EntraEligibleRole
from fomo.screens._common import role_detail_state, role_state_tag
from fomo.screens.assignments_screen import AssignmentsScreen
from fomo.screens.roles_screen import RolesScreen
from fomo.widgets import FomoSelectionList
from tests.conftest import role
from tests.test_azure_robustness import USER_ID, USER_SHOW, _eligibility, _fake_az, _Response
from tests.test_tui_markup import _scope_ready, make_live_app  # noqa: F401
from tests.test_tui_smoke import SIZE, _prompts, _status_cells, wait_for

NOW = datetime(2026, 11, 12, 13, 45, tzinfo=UTC)  # a Thursday


def _iso(when: datetime) -> str:
    """An end time the way Azure writes it."""
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f0Z")


# ---------------------------------------------------------------------------
# timefmt
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("iso", "expected"),
    [
        (_iso(NOW + timedelta(minutes=47)), "47m left"),
        (_iso(NOW + timedelta(minutes=46, seconds=1)), "47m left"),  # minutes round up
        (_iso(NOW + timedelta(seconds=20)), "1m left"),
        (_iso(NOW + timedelta(minutes=59, seconds=30)), "1h 00m left"),
        (_iso(NOW + timedelta(hours=3, minutes=5)), "3h 05m left"),
        (_iso(NOW + timedelta(hours=23, minutes=59)), "23h 59m left"),
        (_iso(NOW + timedelta(days=2, hours=3)), "2d 03h left"),
        ("2026-11-12T14:32:00Z", "47m left"),
        ("2026-11-12T14:32:00+00:00", "47m left"),
        ("2026-11-12T15:32:00+01:00", "47m left"),
        ("2026-11-12T14:32:00", "47m left"),  # no zone: UTC
        (_iso(NOW), "expired"),
        ("2026-11-12T13:00:00Z", "expired"),
        (None, "permanent"),
        ("", "permanent"),
        ("not a date", ""),
    ],
)
def test_format_remaining(iso: str | None, expected: str) -> None:
    assert timefmt.format_remaining(iso, NOW) == expected


@pytest.mark.parametrize(
    ("iso", "now", "expected"),
    [
        ("2026-11-12T14:32:00Z", NOW, "14:32 (47m left)"),
        # Shown in now's time zone.
        ("2026-11-12T14:32:00Z", NOW.astimezone(timezone(timedelta(hours=2))), "16:32 (47m left)"),
        ("2026-11-13T09:30:00Z", NOW, "Fri 09:30 (19h 45m left)"),
        ("2026-11-19T13:44:00Z", NOW, "Thu 13:44 (6d 23h left)"),
        ("2026-11-19T13:45:00Z", NOW, "2026-11-19"),  # 7 days away: the date
        ("2026-12-31T00:00:00Z", NOW, "2026-12-31"),
        ("2026-11-12T13:00:00Z", NOW, "2026-11-12 (expired)"),
        (None, NOW, "Permanent"),
        ("garbage", NOW, "garbage"),
    ],
)
def test_format_end(iso: str | None, now: datetime, expected: str) -> None:
    assert timefmt.format_end(iso, now) == expected


def test_end_sort_key_orders_by_time_then_malformed_then_permanent() -> None:
    ends = [None, "2026-12-31T00:00:00Z", "junk", "2026-11-12T15:32:00+01:00", "2026-11-12T14:40:00Z"]
    assert sorted(ends, key=timefmt.end_sort_key) == [
        "2026-11-12T15:32:00+01:00",
        "2026-11-12T14:40:00Z",
        "2026-12-31T00:00:00Z",
        "junk",
        None,
    ]


def test_role_state_tag_and_detail() -> None:
    active = role("Reader", "/subscriptions/s1", active=True)
    active.active_until = "2026-11-12T14:32:00Z"
    active.expiry = "2026-12-31T00:00:00Z"
    assert role_state_tag(active, NOW) == "● active · 47m left"
    assert role_detail_state(active, NOW) == ("Active until 14:32 (47m left)", "Eligible until 2026-12-31")

    # Activated in this session: the end isn't known.
    just_activated = role("Reader", "/subscriptions/s1", active=True)
    assert role_state_tag(just_activated, NOW) == "● active"
    assert role_detail_state(just_activated, NOW) == ("Currently active", "Eligible permanently")

    eligible = EntraEligibleRole("Global Reader", "gr", "u", "e1", "2026-12-31T00:00:00Z")
    assert role_state_tag(eligible, NOW) == "eligible until 2026-12-31"
    assert role_detail_state(eligible, NOW) == ("", "Eligible until 2026-12-31")
    assert role_state_tag(EntraEligibleRole("Global Reader", "gr", "u", "e1", None), NOW) == ""


# ---------------------------------------------------------------------------
# fomo.azure: the activation's end comes with the role
# ---------------------------------------------------------------------------


def test_arm_roles_carry_the_activation_end(monkeypatch: pytest.MonkeyPatch) -> None:
    scope = "/subscriptions/s1"
    reader = _eligibility(scope)
    owner = _eligibility(scope)
    owner["properties"]["roleDefinitionId"] = f"{scope}/providers/Microsoft.Authorization/roleDefinitions/owner"
    active = [
        {
            "properties": {
                "assignmentType": "Activated",
                "roleDefinitionId": reader["properties"]["roleDefinitionId"],
                "endDateTime": "2026-11-12T14:32:00Z",
                "expandedProperties": {"scope": {"id": scope}},
            }
        },
        {  # a permanent assignment of the same role is not an activation
            "properties": {
                "assignmentType": "Assigned",
                "roleDefinitionId": owner["properties"]["roleDefinitionId"],
                "expandedProperties": {"scope": {"id": scope}},
            }
        },
    ]

    def _respond(cmd: list[str]) -> tuple[int, Any, str]:
        if cmd[1:4] == USER_SHOW:
            return 0, USER_ID, ""
        url = cmd[cmd.index("--url") + 1]
        if "/roleAssignmentScheduleInstances" in url:
            return 0, {"value": active}, ""
        return 0, {"value": [reader, owner]}, ""

    _fake_az(monkeypatch, _respond)

    assert azure._list_active_role_keys(scope) == {
        (reader["properties"]["roleDefinitionId"], scope): "2026-11-12T14:32:00Z"
    }
    roles = azure.list_eligible_roles("s1")
    assert [(r.role_definition_id.rsplit("/", 1)[-1], r.is_active, r.active_until) for r in roles] == [
        ("reader", True, "2026-11-12T14:32:00Z"),
        ("owner", False, None),
    ]


def test_entra_roles_carry_the_activation_end(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(azure, "get_current_user", lambda: USER_ID)
    monkeypatch.setattr(azure, "_get_graph_token", lambda *a, **k: "tok")
    eligible = {
        "value": [
            {"roleDefinitionId": "gr", "id": "e1", "roleDefinition": {"displayName": "Global Reader"}},
            {"roleDefinitionId": "sr", "id": "e2", "roleDefinition": {"displayName": "Security Reader"}},
        ]
    }
    active = {"value": [{"roleDefinitionId": "gr", "endDateTime": "2026-11-12T14:32:00Z"}]}

    def _urlopen(req: Any, *args: Any, **kwargs: Any) -> _Response:
        body = active if "/roleAssignmentScheduleInstances" in req.full_url else eligible
        return _Response(json.dumps(body).encode())

    monkeypatch.setattr(azure.urllib.request, "urlopen", _urlopen)

    roles = azure.list_entra_eligible_roles()

    assert [(r.role_name, r.is_active, r.active_until) for r in roles] == [
        ("Global Reader", True, "2026-11-12T14:32:00Z"),
        ("Security Reader", False, None),
    ]


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------


def test_roles_list_shows_time_left_and_eligibility_end(make_live_app, fake_azure) -> None:  # noqa: F811
    reader = role("Reader", "/subscriptions/s1", active=True, disp="Contoso Production")
    reader.active_until = _iso(datetime.now(UTC) + timedelta(minutes=47))
    kv = role("Key Vault Reader", "/subscriptions/s1", disp="Contoso Production")
    kv.expiry = "2026-12-31T00:00:00Z"
    fake_azure.roles = {"s1": [reader, kv]}

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE) as pilot:
            await _scope_ready(pilot)
            screen = RolesScreen(["s1"])
            await app.push_screen(screen)
            role_list = screen.query_one("#role-list", FomoSelectionList)
            await wait_for(pilot, lambda: role_list.option_count == 2)
            assert _prompts(role_list) == [
                "Key Vault Reader  —  Contoso Production   eligible until 2026-12-31",
                "Reader  —  Contoso Production   ● active · 47m left",
            ]

    asyncio.run(scenario())


def test_assignments_show_time_left_directory_scope_and_sort_by_time(make_live_app, fake_azure) -> None:  # noqa: F811
    now = datetime.now(UTC)
    fake_azure.arm_assignments = [
        ActiveAssignment("Owner", "/subscriptions/s1", "Contoso Production", None, "Assigned"),
        ActiveAssignment(
            "Reader", "/subscriptions/s1", "Contoso Production", _iso(now + timedelta(days=30)), "Activated"
        ),
        ActiveAssignment(
            "Contributor", "/subscriptions/s1", "Contoso Production", _iso(now + timedelta(days=2)), "Activated"
        ),
        ActiveAssignment(
            "Key Vault Reader",
            "/subscriptions/s1",
            "Contoso Production",
            _iso(now + timedelta(minutes=47)),
            "Activated",
        ),
    ]
    fake_azure.entra_assignments = [
        ActiveEntraAssignment("Global Reader", "/", None, "Activated"),
        ActiveEntraAssignment("Helpdesk Administrator", "/administrativeUnits/au1", None, "Activated"),
    ]

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE) as pilot:
            await _scope_ready(pilot)
            screen = AssignmentsScreen()
            await app.push_screen(screen)
            azure_table = screen.query_one("#azure-table", DataTable)
            entra_table = screen.query_one("#entra-table", DataTable)
            await wait_for(pilot, lambda: azure_table.row_count == 4 and entra_table.row_count == 2)
            assert _status_cells(entra_table, 1) == ["Directory", "/administrativeUnits/au1"]
            expiry = dict(zip(_status_cells(azure_table, 0), _status_cells(azure_table, 2), strict=True))
            assert expiry["Key Vault Reader"].endswith(" (47m left)")
            assert expiry["Contributor"].endswith(" (2d 00h left)")
            assert expiry["Reader"] == (now + timedelta(days=30)).strftime("%Y-%m-%d")
            assert expiry["Owner"] == "Permanent"

            azure_table.focus()
            await pilot.press("3")
            await pilot.pause()
            assert _status_cells(azure_table, 0) == ["Key Vault Reader", "Contributor", "Reader", "Owner"]

    asyncio.run(scenario())
