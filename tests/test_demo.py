"""Demo data: realistic enough for screenshots and for exploring the TUI (F40)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fomo import demo
from fomo.timefmt import parse_iso

PROD_ID = "11111111-1111-1111-1111-111111111111"  # "Contoso Production"
MG_CONTOSO = "/providers/Microsoft.Management/managementGroups/mg-contoso"


def _ends_in(iso: str | None, now: datetime) -> timedelta:
    end = parse_iso(iso)
    assert end is not None, iso
    return end - now


def test_contoso_production_includes_the_role_inherited_from_its_management_group() -> None:
    # asTarget() at a subscription also returns eligibilities on its parent
    # management groups, so the roles screen's "Global assignments" section
    # shows up in demo mode too.
    roles = demo.list_eligible_roles(PROD_ID)
    assert [(r.role_name, r.scope) for r in roles if r.is_global] == [("Reader", MG_CONTOSO)]
    assert any(not r.is_global for r in roles)


def test_demo_dates_are_relative_to_now() -> None:
    now = datetime.now(UTC)
    roles = [role for sub in demo.list_subscriptions() for role in demo.list_eligible_roles(sub.id)]
    entra = demo.list_entra_eligible_roles()

    # Active roles and active assignments end 30-90 minutes after the demo
    # data was made, so they are still running now.
    active_ends = [r.active_until for r in [*roles, *entra] if r.active_until]
    active_ends += [a.expiry for a in demo.list_active_arm_assignments() if a.expiry]
    active_ends += [a.expiry for a in demo.list_active_entra_assignments() if a.expiry]
    assert len(active_ends) >= 4
    for end in active_ends:
        assert timedelta(0) < _ends_in(end, now) <= timedelta(minutes=90), end

    # Eligibilities end in one to six months.
    eligible_ends = [r.expiry for r in [*roles, *entra] if r.expiry]
    assert eligible_ends
    for end in eligible_ends:
        assert timedelta(days=29) < _ends_in(end, now) <= timedelta(days=183), end
