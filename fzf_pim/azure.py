"""Azure CLI / ARM REST API helpers for PIM role management.

All I/O goes through `az rest` so that authentication is delegated to
the Azure CLI session already active in the terminal.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from dataclasses import dataclass
from typing import Any, Callable

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_az(*args: str) -> Any:
    """Run an `az` CLI command and return parsed JSON output.

    Raises RuntimeError on non-zero exit or if `az` is not found.
    """
    log.debug("az %s", " ".join(args))
    try:
        result = subprocess.run(
            ["az", *args, "--output", "json"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "Azure CLI not found. Install it: https://aka.ms/installazurecli"
        )
    if result.returncode != 0:
        msg = result.stderr.strip()
        log.error(
            "az %s failed (exit %d):\n%s",
            " ".join(args),
            result.returncode,
            msg,
        )
        raise RuntimeError(msg or f"az {' '.join(args)} exited {result.returncode}")
    log.debug("az response: %s", result.stdout[:2000])
    return json.loads(result.stdout)


def is_auth_error(msg: str) -> bool:
    """Return True if *msg* indicates an expired or missing Azure CLI session."""
    lowered = msg.lower()
    return any(
        token in lowered
        for token in (
            "refresh token",
            "aadsts",
            "az login",
            "not logged in",
            "please run",
            "unauthorized",
        )
    )


def is_scope_error(msg: str) -> bool:
    """Return True if *msg* indicates a missing OAuth scope / consent."""
    lowered = msg.lower()
    return any(
        token in lowered
        for token in (
            "permissionscopenotgranted",
            "authorization_requestdenied",
            "insufficient privileges",
        )
    )


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Subscription:
    id: str
    name: str


@dataclass
class EligibleRole:
    role_name: str
    role_definition_id: str
    scope: str               # actual assignment scope: /subscriptions/{id} or /providers/Microsoft.Management/managementGroups/{id}
    scope_display_name: str  # human-readable scope name
    principal_id: str
    eligibility_schedule_id: str  # short GUID used in linkedRoleEligibilityScheduleId
    expiry: str | None            # ISO 8601 datetime string or None
    is_active: bool = False       # True if already PIM-activated

    @property
    def is_global(self) -> bool:
        """True if assigned at management group or root scope (not subscription-scoped)."""
        return not self.scope.startswith("/subscriptions/")


@dataclass
class EntraEligibleRole:
    role_name: str
    role_definition_id: str
    principal_id: str
    eligibility_schedule_id: str  # unifiedRoleEligibilitySchedule id
    expiry: str | None
    directory_scope_id: str = "/"  # directoryScopeId from eligibility; "/" = tenant-wide
    is_active: bool = False


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(
    r"^P(?:\d+Y)?(?:\d+M)?(?:\d+D)?(?:T(?:\d+H)?(?:\d+M)?(?:\d+(?:\.\d+)?S)?)?$"
)


def validate_duration(s: str) -> bool:
    """Return True if *s* is a non-trivial ISO 8601 duration (e.g. PT8H)."""
    return bool(_DURATION_RE.match(s)) and s not in ("P", "PT")


def format_expiry(expiry: str | None) -> str:
    """Shorten an ISO 8601 datetime to YYYY-MM-DD, or return 'Permanent'."""
    if not expiry:
        return "Permanent"
    return expiry[:10]


# ---------------------------------------------------------------------------
# Azure API calls
# ---------------------------------------------------------------------------

def get_current_user() -> str:
    """Return the object ID of the currently signed-in user."""
    data = _run_az("ad", "signed-in-user", "show")
    return data["id"]


def list_subscriptions() -> list[Subscription]:
    """Return all subscriptions visible to the current account."""
    data = _run_az("account", "list")
    return [Subscription(id=s["id"], name=s["name"]) for s in data]


def _list_active_role_keys(scope: str) -> frozenset[tuple[str, str]]:
    """Return a set of (role_definition_id, scope) for currently active PIM assignments."""
    url = (
        f"https://management.azure.com{scope}"
        f"/providers/Microsoft.Authorization/roleAssignmentScheduleInstances"
        f"?$filter=asTarget()&api-version=2020-10-01"
    )
    try:
        data = _run_az("rest", "--method", "GET", "--url", url)
    except RuntimeError:
        return frozenset()
    keys: set[tuple[str, str]] = set()
    for item in data.get("value", []):
        props = item.get("properties", {})
        # Only count Activated (PIM-activated) assignments, not permanent ones
        if props.get("assignmentType") != "Activated":
            continue
        expanded = props.get("expandedProperties", {})
        role_def_id = props.get("roleDefinitionId", "")
        active_scope = expanded.get("scope", {}).get("id") or scope
        keys.add((role_def_id, active_scope))
    return frozenset(keys)


def list_eligible_roles(subscription_id: str) -> list[EligibleRole]:
    """List eligible PIM role assignments for the signed-in user in *subscription_id*.

    Roles that are already active (PIM-activated) are excluded from the result.
    """
    scope = f"/subscriptions/{subscription_id}"
    url = (
        f"https://management.azure.com{scope}"
        f"/providers/Microsoft.Authorization/roleEligibilityScheduleInstances"
        f"?$filter=asTarget()&api-version=2020-10-01"
    )
    # Resolve the signed-in user's own object ID once.
    # When a role eligibility is assigned to a group, the API returns the
    # group's principalId — but SelfActivate requires the requesting *user's*
    # object ID.  We always substitute the real user ID here so activation
    # works for both direct and group-based eligibilities.
    user_id = get_current_user()
    active_keys = _list_active_role_keys(scope)
    data = _run_az("rest", "--method", "GET", "--url", url)
    roles: list[EligibleRole] = []
    for item in data.get("value", []):
        props = item.get("properties", {})
        expanded = props.get("expandedProperties", {})
        # Extract the short GUID from the full resource path
        sched_path: str = props.get("roleEligibilityScheduleId", "")
        sched_id = sched_path.rsplit("/", 1)[-1] if "/" in sched_path else item.get("name", str(uuid.uuid4()))
        actual_scope = expanded.get("scope", {}).get("id") or scope
        role_def_id = props.get("roleDefinitionId", "")
        already_active = (role_def_id, actual_scope) in active_keys
        if already_active:
            log.debug("marking already-active role %s on %s", role_def_id, actual_scope)
        roles.append(
            EligibleRole(
                role_name=expanded.get("roleDefinition", {}).get("displayName", "Unknown"),
                role_definition_id=role_def_id,
                scope=actual_scope,
                scope_display_name=(
                    expanded.get("scope", {}).get("displayName") or subscription_id
                ),
                principal_id=user_id,
                eligibility_schedule_id=sched_id,
                expiry=props.get("endDateTime"),
                is_active=already_active,
            )
        )
    return roles


def activate_role(
    role: EligibleRole,
    justification: str,
    duration: str,
    dry_run: bool = False,
) -> dict:
    """Submit a SelfActivate request for an eligible PIM role.

    Returns the ARM response dict.  When *dry_run* is True the API call
    is skipped and a synthetic response is returned instead.
    """
    request_id = str(uuid.uuid4())
    if dry_run:
        log.debug("dry-run: skipping activation of %s", role.role_name)
        return {
            "name": request_id,
            "properties": {"status": "DryRun", "requestType": "SelfActivate"},
        }
    body = json.dumps(
        {
            "properties": {
                "principalId": role.principal_id,
                "roleDefinitionId": role.role_definition_id,
                "requestType": "SelfActivate",
                "linkedRoleEligibilityScheduleId": role.eligibility_schedule_id,
                "scheduleInfo": {
                    "expiration": {
                        "type": "AfterDuration",
                        "duration": duration,
                    }
                },
                "justification": justification,
            }
        }
    )
    url = (
        f"https://management.azure.com{role.scope}"
        f"/providers/Microsoft.Authorization"
        f"/roleAssignmentScheduleRequests/{request_id}?api-version=2020-10-01"
    )
    log.debug(
        "activating role %s on %s (request %s)", role.role_name, role.scope, request_id
    )
    response = _run_az(
        "rest", "--method", "PUT", "--url", url, "--body", body,
        "--headers", "Content-Type=application/json",
    )
    log.debug(
        "activation response for %s: status=%s",
        role.role_name,
        response.get("properties", {}).get("status"),
    )
    return response


# ---------------------------------------------------------------------------
# Microsoft Entra (Azure AD) PIM — Graph API
# ---------------------------------------------------------------------------

_GRAPH = "https://graph.microsoft.com"

# Well-known Microsoft Graph PowerShell public client — pre-authorised for
# delegated PIM scopes in every tenant without requiring a separate app registration.
_GRAPH_CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
_GRAPH_SCOPES = "RoleManagement.ReadWrite.Directory offline_access"
_TOKEN_CACHE_PATH = os.path.expanduser("~/.cache/fzf-pim/graph_token.json")

# Module-level token cache: (access_token, expiry_unix_timestamp)
_graph_token_cache: tuple[str, float] | None = None


def _get_tenant_id() -> str:
    """Return the tenant ID of the currently active Azure CLI account."""
    data = _run_az("account", "show")
    return data["tenantId"]


def _load_token_cache() -> dict | None:
    """Load persisted token data from disk. Returns None on any error."""
    try:
        with open(_TOKEN_CACHE_PATH) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _save_token_cache(token_data: dict, tenant_id: str) -> None:
    """Persist access + refresh tokens to disk with 0o600 permissions."""
    os.makedirs(os.path.dirname(_TOKEN_CACHE_PATH), exist_ok=True)
    payload = {
        k: token_data[k]
        for k in ("access_token", "refresh_token", "expires_in")
        if k in token_data
    }
    payload["tenant_id"] = tenant_id
    payload["cached_at"] = time.time()
    with open(_TOKEN_CACHE_PATH, "w") as f:
        json.dump(payload, f)
    os.chmod(_TOKEN_CACHE_PATH, 0o600)


def _token_endpoint(tenant_id: str) -> str:
    return f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"


def _try_refresh_token(tenant_id: str, refresh_token: str) -> dict | None:
    """Attempt a silent token refresh. Returns the token dict or None on failure."""
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": _GRAPH_CLIENT_ID,
        "refresh_token": refresh_token,
        "scope": _GRAPH_SCOPES,
    }).encode()
    req = urllib.request.Request(_token_endpoint(tenant_id), data=data, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError:
        return None


def _device_code_flow(
    tenant_id: str,
    on_device_code: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> dict:
    """Run the OAuth 2.0 device authorization grant and return the token dict.

    Calls *on_device_code* with the user-facing message once the device code
    is ready, then opens the verification URL in the system browser and polls
    until the user completes authentication.
    """
    dc_req = urllib.request.Request(
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/devicecode",
        data=urllib.parse.urlencode({
            "client_id": _GRAPH_CLIENT_ID,
            "scope": _GRAPH_SCOPES,
        }).encode(),
        method="POST",
    )
    with urllib.request.urlopen(dc_req) as resp:
        dc = json.loads(resp.read())

    if on_device_code is not None:
        user_code = dc.get("user_code", "")
        verify_url = dc.get("verification_uri", "")
        on_device_code(f"{verify_url}\n{user_code}")

    # Open the browser to the pre-filled URL when available.
    browser_url = dc.get("verification_uri_complete") or dc.get("verification_uri", "")
    if browser_url:
        webbrowser.open(browser_url)

    interval = int(dc.get("interval", 5))
    deadline = time.time() + int(dc.get("expires_in", 900))
    token_endpoint = _token_endpoint(tenant_id)

    while time.time() < deadline:
        if stop_event is not None:
            stop_event.wait(interval)
            if stop_event.is_set():
                raise RuntimeError("Authentication cancelled.")
        else:
            time.sleep(interval)
        poll_req = urllib.request.Request(
            token_endpoint,
            data=urllib.parse.urlencode({
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": _GRAPH_CLIENT_ID,
                "device_code": dc["device_code"],
            }).encode(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(poll_req) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read())
            error = body.get("error", "")
            if error == "authorization_pending":
                continue
            elif error == "slow_down":
                interval += 5
                continue
            elif error == "access_denied":
                raise RuntimeError("Graph authentication was denied.") from None
            elif error == "expired_token":
                raise RuntimeError("Device code expired — please try again.") from None
            else:
                raise RuntimeError(
                    f"Graph authentication failed: {error}: "
                    f"{body.get('error_description', '')}"
                ) from None

    raise RuntimeError("Device code authentication timed out — please try again.")


def _get_graph_token(
    on_device_code: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> str:
    """Return a bearer token for the Graph API.

    Uses the Microsoft Graph PowerShell public client (14d82eec-...) which is
    pre-authorised for delegated PIM scopes without tenant-admin consent and
    without a separate app registration.  Tokens are cached in-process and on
    disk (refresh token) so the browser flow only runs on first use.
    """
    global _graph_token_cache
    now = time.time()

    # 1. In-process access token still valid.
    if _graph_token_cache and _graph_token_cache[1] > now + 60:
        log.debug("using cached Graph token (expires in %.0fs)", _graph_token_cache[1] - now)
        return _graph_token_cache[0]

    # 2. Try silent refresh via cached refresh token.
    cache = _load_token_cache()
    if cache and "refresh_token" in cache:
        tenant_id = cache.get("tenant_id") or _get_tenant_id()
        log.debug("refreshing Graph token for tenant %s", tenant_id)
        token_data = _try_refresh_token(tenant_id, cache["refresh_token"])
        if token_data and "access_token" in token_data:
            expiry = now + float(token_data.get("expires_in", 3600)) - 60
            _graph_token_cache = (token_data["access_token"], expiry)
            _save_token_cache(token_data, tenant_id)
            log.debug("Graph token refreshed, expires in %.0fs", token_data.get("expires_in", 3600))
            return token_data["access_token"]

    # 3. Interactive device code flow.
    tenant_id = _get_tenant_id()
    log.debug("starting device code flow for tenant %s", tenant_id)
    token_data = _device_code_flow(tenant_id, on_device_code, stop_event)
    expiry = now + float(token_data.get("expires_in", 3600)) - 60
    _graph_token_cache = (token_data["access_token"], expiry)
    _save_token_cache(token_data, tenant_id)
    log.debug("Graph token acquired via device code, expires in %.0fs", token_data.get("expires_in", 3600))
    return token_data["access_token"]


def _run_graph(method: str, url: str, body: str | None = None) -> Any:
    """Make a Microsoft Graph API call using a device-code-acquired bearer token."""
    token = _get_graph_token()
    req = urllib.request.Request(url, method=method.upper())
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    if body is not None:
        req.data = body.encode()
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            detail = json.loads(raw).get("error", {}).get("message", raw)
        except Exception:
            detail = raw
        raise RuntimeError(detail) from None


def _list_active_entra_role_def_ids(principal_id: str) -> frozenset[str]:
    """Return role definition IDs currently PIM-activated in Entra for *principal_id*."""
    filter_val = urllib.parse.quote(
        f"principalId eq '{principal_id}' and assignmentType eq 'Activated'",
        safe="'()",
    )
    url = (
        f"{_GRAPH}/v1.0/roleManagement/directory/roleAssignmentScheduleInstances"
        f"?$filter={filter_val}"
    )
    try:
        data = _run_graph("GET", url)
    except RuntimeError:
        return frozenset()
    return frozenset(item.get("roleDefinitionId", "") for item in data.get("value", []))


def list_entra_eligible_roles(
    on_device_code: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> list[EntraEligibleRole]:
    """List eligible Entra PIM role assignments for the signed-in user."""
    user_id = get_current_user()
    # Acquire the token once (triggering device code if needed) so all
    # subsequent _run_graph calls hit the in-process cache silently.
    _get_graph_token(on_device_code, stop_event)
    active_def_ids = _list_active_entra_role_def_ids(user_id)
    filter_val = urllib.parse.quote(f"principalId eq '{user_id}'", safe="'()")
    url = (
        f"{_GRAPH}/v1.0/roleManagement/directory/roleEligibilityScheduleInstances"
        f"?$filter={filter_val}&$expand=roleDefinition"
    )
    data = _run_graph("GET", url)
    roles: list[EntraEligibleRole] = []
    for item in data.get("value", []):
        role_def = item.get("roleDefinition") or {}
        role_def_id = item.get("roleDefinitionId", "")
        roles.append(
            EntraEligibleRole(
                role_name=role_def.get("displayName", "Unknown"),
                role_definition_id=role_def_id,
                principal_id=user_id,
                eligibility_schedule_id=item.get(
                    "roleEligibilityScheduleId", item.get("id", str(uuid.uuid4()))
                ),
                expiry=item.get("endDateTime"),
                directory_scope_id=item.get("directoryScopeId", "/"),
                is_active=role_def_id in active_def_ids,
            )
        )
    return roles


def activate_entra_role(
    role: EntraEligibleRole,
    justification: str,
    duration: str,
    dry_run: bool = False,
) -> dict:
    """Submit a selfActivate request for an Entra PIM role via Microsoft Graph."""
    request_id = str(uuid.uuid4())
    if dry_run:
        log.debug("dry-run: skipping Entra activation of %s", role.role_name)
        return {"id": request_id, "status": "DryRun"}
    body = json.dumps(
        {
            "action": "selfActivate",
            "principalId": role.principal_id,
            "roleDefinitionId": role.role_definition_id,
            "directoryScopeId": role.directory_scope_id,
            "justification": justification,
            "linkedRoleEligibilityScheduleId": role.eligibility_schedule_id,
            "scheduleInfo": {
                "expiration": {
                    "type": "afterDuration",
                    "duration": duration,
                }
            },
        }
    )
    url = f"{_GRAPH}/v1.0/roleManagement/directory/roleAssignmentScheduleRequests"
    log.debug("activating Entra role %s (request %s)", role.role_name, request_id)
    response = _run_graph("POST", url, body)
    log.debug(
        "Entra activation response for %s: status=%s",
        role.role_name,
        response.get("status"),
    )
    return response

