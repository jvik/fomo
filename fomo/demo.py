"""Dummy data for --demo mode (screenshot generation, no Azure auth required)."""

from __future__ import annotations

from fomo.azure import (
    ActiveAssignment,
    ActiveEntraAssignment,
    EligibleRole,
    EntraEligibleRole,
    Subscription,
)

_PRINCIPAL = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------

SUBSCRIPTIONS: list[Subscription] = [
    Subscription(id="11111111-1111-1111-1111-111111111111", name="Contoso Production"),
    Subscription(id="22222222-2222-2222-2222-222222222222", name="Contoso Development"),
    Subscription(id="33333333-3333-3333-3333-333333333333", name="Contoso Shared Services"),
    Subscription(id="44444444-4444-4444-4444-444444444444", name="Fabrikam Platform"),
    Subscription(id="55555555-5555-5555-5555-555555555555", name="Woodgrove Analytics"),
]


def list_subscriptions() -> list[Subscription]:
    return list(SUBSCRIPTIONS)


# ---------------------------------------------------------------------------
# Eligible RBAC roles
# ---------------------------------------------------------------------------

_SUB_ROLES: list[EligibleRole] = [
    # Contoso Production
    EligibleRole(
        role_name="Key Vault Administrator",
        role_definition_id="/subscriptions/11111111-1111-1111-1111-111111111111/providers/Microsoft.Authorization/roleDefinitions/00482a5a-887f-4fb3-b363-3b7fe8e74483",
        scope="/subscriptions/11111111-1111-1111-1111-111111111111",
        scope_display_name="Contoso Production",
        principal_id=_PRINCIPAL,
        eligibility_schedule_id="sched-0001",
        expiry="2026-12-31T00:00:00Z",
        is_active=False,
    ),
    EligibleRole(
        role_name="Contributor",
        role_definition_id="/subscriptions/11111111-1111-1111-1111-111111111111/providers/Microsoft.Authorization/roleDefinitions/b24988ac-6180-42a0-ab88-20f7382dd24c",
        scope="/subscriptions/11111111-1111-1111-1111-111111111111",
        scope_display_name="Contoso Production",
        principal_id=_PRINCIPAL,
        eligibility_schedule_id="sched-0002",
        expiry="2026-09-30T00:00:00Z",
        is_active=True,
    ),
    EligibleRole(
        role_name="Storage Blob Data Owner",
        role_definition_id="/subscriptions/11111111-1111-1111-1111-111111111111/providers/Microsoft.Authorization/roleDefinitions/b7e6dc6d-f1e8-4753-8033-0f276bb0955b",
        scope="/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-prod-storage",
        scope_display_name="rg-prod-storage",
        principal_id=_PRINCIPAL,
        eligibility_schedule_id="sched-0003",
        expiry="2026-12-31T00:00:00Z",
        is_active=False,
    ),
    # Contoso Development
    EligibleRole(
        role_name="Owner",
        role_definition_id="/subscriptions/22222222-2222-2222-2222-222222222222/providers/Microsoft.Authorization/roleDefinitions/8e3af657-a8ff-443c-a75c-2fe8c4bcb635",
        scope="/subscriptions/22222222-2222-2222-2222-222222222222",
        scope_display_name="Contoso Development",
        principal_id=_PRINCIPAL,
        eligibility_schedule_id="sched-0004",
        expiry=None,
        is_active=False,
    ),
    EligibleRole(
        role_name="Virtual Machine Contributor",
        role_definition_id="/subscriptions/22222222-2222-2222-2222-222222222222/providers/Microsoft.Authorization/roleDefinitions/9980e02c-c2be-4d73-94e8-173b1dc7cf3c",
        scope="/subscriptions/22222222-2222-2222-2222-222222222222",
        scope_display_name="Contoso Development",
        principal_id=_PRINCIPAL,
        eligibility_schedule_id="sched-0005",
        expiry="2026-10-15T00:00:00Z",
        is_active=False,
    ),
    EligibleRole(
        role_name="DevTest Labs User",
        role_definition_id="/subscriptions/22222222-2222-2222-2222-222222222222/providers/Microsoft.Authorization/roleDefinitions/76283e04-6283-4c54-8f91-720b658f157e",
        scope="/subscriptions/22222222-2222-2222-2222-222222222222/resourceGroups/rg-devtest",
        scope_display_name="rg-devtest",
        principal_id=_PRINCIPAL,
        eligibility_schedule_id="sched-0006",
        expiry="2027-01-01T00:00:00Z",
        is_active=False,
    ),
    # Contoso Shared Services
    EligibleRole(
        role_name="Network Contributor",
        role_definition_id="/subscriptions/33333333-3333-3333-3333-333333333333/providers/Microsoft.Authorization/roleDefinitions/4d97b98b-1d4f-4787-a291-c67834d212e7",
        scope="/subscriptions/33333333-3333-3333-3333-333333333333",
        scope_display_name="Contoso Shared Services",
        principal_id=_PRINCIPAL,
        eligibility_schedule_id="sched-0007",
        expiry="2026-11-30T00:00:00Z",
        is_active=False,
    ),
    EligibleRole(
        role_name="Monitoring Contributor",
        role_definition_id="/subscriptions/33333333-3333-3333-3333-333333333333/providers/Microsoft.Authorization/roleDefinitions/749f88d5-cbae-40b8-bcfc-e573ddc772fa",
        scope="/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/rg-monitoring",
        scope_display_name="rg-monitoring",
        principal_id=_PRINCIPAL,
        eligibility_schedule_id="sched-0008",
        expiry="2026-08-31T00:00:00Z",
        is_active=False,
    ),
    # Fabrikam Platform
    EligibleRole(
        role_name="AKS Cluster Admin",
        role_definition_id="/subscriptions/44444444-4444-4444-4444-444444444444/providers/Microsoft.Authorization/roleDefinitions/0ab0b1a8-8aac-4efd-b8c2-3ee1fb270be8",
        scope="/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/rg-aks-prod",
        scope_display_name="rg-aks-prod",
        principal_id=_PRINCIPAL,
        eligibility_schedule_id="sched-0009",
        expiry="2026-12-31T00:00:00Z",
        is_active=False,
    ),
    EligibleRole(
        role_name="Key Vault Secrets Officer",
        role_definition_id="/subscriptions/44444444-4444-4444-4444-444444444444/providers/Microsoft.Authorization/roleDefinitions/b86a8fe4-44ce-4948-aee5-eccb2c155cd7",
        scope="/subscriptions/44444444-4444-4444-4444-444444444444",
        scope_display_name="Fabrikam Platform",
        principal_id=_PRINCIPAL,
        eligibility_schedule_id="sched-0010",
        expiry="2027-03-01T00:00:00Z",
        is_active=False,
    ),
    # Woodgrove Analytics
    EligibleRole(
        role_name="Storage Blob Data Contributor",
        role_definition_id="/subscriptions/55555555-5555-5555-5555-555555555555/providers/Microsoft.Authorization/roleDefinitions/ba92f5b4-2d11-453d-a403-e96b0029c9fe",
        scope="/subscriptions/55555555-5555-5555-5555-555555555555",
        scope_display_name="Woodgrove Analytics",
        principal_id=_PRINCIPAL,
        eligibility_schedule_id="sched-0011",
        expiry="2026-07-31T00:00:00Z",
        is_active=False,
    ),
    EligibleRole(
        role_name="Cosmos DB Operator",
        role_definition_id="/subscriptions/55555555-5555-5555-5555-555555555555/providers/Microsoft.Authorization/roleDefinitions/230815da-be43-4aae-9201-5db1f487b7b7",
        scope="/subscriptions/55555555-5555-5555-5555-555555555555/resourceGroups/rg-analytics",
        scope_display_name="rg-analytics",
        principal_id=_PRINCIPAL,
        eligibility_schedule_id="sched-0012",
        expiry="2026-10-01T00:00:00Z",
        is_active=False,
    ),
    # Management group (global scope)
    EligibleRole(
        role_name="Reader",
        role_definition_id="/providers/Microsoft.Authorization/roleDefinitions/acdd72a7-3385-48ef-bd42-f606fba81ae7",
        scope="/providers/Microsoft.Management/managementGroups/mg-contoso",
        scope_display_name="mg-contoso",
        principal_id=_PRINCIPAL,
        eligibility_schedule_id="sched-0013",
        expiry=None,
        is_active=False,
    ),
]

_SUB_ID_TO_ROLES: dict[str, list[EligibleRole]] = {}
for _r in _SUB_ROLES:
    parts = _r.scope.split("/")
    if len(parts) >= 3 and parts[1] == "subscriptions":
        _key = parts[2]
    else:
        _key = "__global__"
    _SUB_ID_TO_ROLES.setdefault(_key, []).append(_r)


def list_eligible_roles(sub_id: str) -> list[EligibleRole]:
    return list(_SUB_ID_TO_ROLES.get(sub_id, []))


# ---------------------------------------------------------------------------
# Eligible Entra roles
# ---------------------------------------------------------------------------

_ENTRA_ROLES: list[EntraEligibleRole] = [
    EntraEligibleRole(
        role_name="Global Reader",
        role_definition_id="f2ef992c-3afb-46b9-b7cf-a126ee74c451",
        principal_id=_PRINCIPAL,
        eligibility_schedule_id="entra-sched-0001",
        expiry="2026-12-31T00:00:00Z",
        directory_scope_id="/",
        is_active=False,
    ),
    EntraEligibleRole(
        role_name="Security Reader",
        role_definition_id="5d6b6bb7-de71-4623-b4af-96380a352509",
        principal_id=_PRINCIPAL,
        eligibility_schedule_id="entra-sched-0002",
        expiry=None,
        directory_scope_id="/",
        is_active=False,
    ),
    EntraEligibleRole(
        role_name="Cloud Application Administrator",
        role_definition_id="158c047a-c907-4556-b7ef-446551a6b5f7",
        principal_id=_PRINCIPAL,
        eligibility_schedule_id="entra-sched-0003",
        expiry="2026-06-30T00:00:00Z",
        directory_scope_id="/",
        is_active=True,
    ),
    EntraEligibleRole(
        role_name="Privileged Role Administrator",
        role_definition_id="e8611ab8-c189-46e8-94e1-60213ab1f814",
        principal_id=_PRINCIPAL,
        eligibility_schedule_id="entra-sched-0004",
        expiry="2026-09-15T00:00:00Z",
        directory_scope_id="/",
        is_active=False,
    ),
    EntraEligibleRole(
        role_name="Intune Administrator",
        role_definition_id="3a2c62db-5318-420d-8d74-23affee5d9d5",
        principal_id=_PRINCIPAL,
        eligibility_schedule_id="entra-sched-0005",
        expiry="2026-11-01T00:00:00Z",
        directory_scope_id="/",
        is_active=False,
    ),
]


def list_entra_eligible_roles() -> list[EntraEligibleRole]:
    return list(_ENTRA_ROLES)


# ---------------------------------------------------------------------------
# Active assignments
# ---------------------------------------------------------------------------

ACTIVE_ARM_ASSIGNMENTS: list[ActiveAssignment] = [
    ActiveAssignment(
        role_name="Contributor",
        scope="/subscriptions/11111111-1111-1111-1111-111111111111",
        scope_display_name="Contoso Production",
        expiry="2026-06-30T18:00:00Z",
        assignment_type="Activated",
    ),
    ActiveAssignment(
        role_name="Reader",
        scope="/subscriptions/22222222-2222-2222-2222-222222222222",
        scope_display_name="Contoso Development",
        expiry=None,
        assignment_type="Assigned",
    ),
    ActiveAssignment(
        role_name="Key Vault Secrets User",
        scope="/subscriptions/44444444-4444-4444-4444-444444444444",
        scope_display_name="Fabrikam Platform",
        expiry="2026-06-28T09:30:00Z",
        assignment_type="Activated",
    ),
    ActiveAssignment(
        role_name="Monitoring Reader",
        scope="/subscriptions/33333333-3333-3333-3333-333333333333",
        scope_display_name="Contoso Shared Services",
        expiry=None,
        assignment_type="Assigned",
    ),
]

ACTIVE_ENTRA_ASSIGNMENTS: list[ActiveEntraAssignment] = [
    ActiveEntraAssignment(
        role_name="Cloud Application Administrator",
        directory_scope_id="/",
        expiry="2026-06-30T18:00:00Z",
        assignment_type="Activated",
    ),
    ActiveEntraAssignment(
        role_name="Global Reader",
        directory_scope_id="/",
        expiry=None,
        assignment_type="Assigned",
    ),
]


def list_active_arm_assignments() -> list[ActiveAssignment]:
    return list(ACTIVE_ARM_ASSIGNMENTS)


def list_active_entra_assignments() -> list[ActiveEntraAssignment]:
    return list(ACTIVE_ENTRA_ASSIGNMENTS)


# ---------------------------------------------------------------------------
# Account info
# ---------------------------------------------------------------------------

DEMO_USER = "demo@contoso.com"
DEMO_TENANT = "Contoso Corp"
