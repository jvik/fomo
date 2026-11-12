"""Azure CLI / ARM REST API helpers for PIM role management.

All I/O goes through `az rest` so that authentication is delegated to
the Azure CLI session already active in the terminal.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from fomo.state import write_private_json

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


# JSON keys whose values are credentials.  Matched anywhere in the key, so
# ``accessToken``, ``access_token`` and ``refresh_token`` are all caught.
_SECRET_VALUE_RE = re.compile(
    r'("[^"\\]*(?:access_?token|refresh_?token|id_?token|client_secret|password)[^"\\]*"\s*:\s*)'
    r'(?:"(?:[^"\\]|\\.)*(?:"|$)|[^\s,}\]]+)',
    re.IGNORECASE,
)


def _redact(text: str) -> str:
    """Mask the JSON values of credential keys (tokens, secrets, passwords) in *text*.

    Works on any text, not only valid JSON, so a truncated body or an error
    message that embeds JSON is still masked.
    """
    return _SECRET_VALUE_RE.sub(r'\1"***"', text)


def _run_az(*args: str, log_body: bool = True) -> Any:
    """Run an `az` CLI command and return parsed JSON output.

    Logged output is redacted with :func:`_redact`.  Pass ``log_body=False``
    for calls whose output must never reach the log (tokens, profile data).

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
        raise RuntimeError("Azure CLI not found. Install it: https://aka.ms/installazurecli") from None
    if result.returncode != 0:
        msg = _redact(result.stderr.strip())
        log.error(
            "az %s failed (exit %d):\n%s",
            " ".join(args),
            result.returncode,
            msg,
        )
        raise RuntimeError(msg or f"az {' '.join(args)} exited {result.returncode}")
    if log_body:
        log.debug("az response: %s", _redact(result.stdout)[:2000])
    else:
        log.debug("az response: <%d characters, not logged>", len(result.stdout))
    return json.loads(result.stdout)


AuthErrorKind = Literal["expired", "not_logged_in", "mfa", "consent", "other"]

# Lower-case markers of a missing OAuth scope or consent (Graph error codes).
_SCOPE_ERROR_TOKENS = (
    "permissionscopenotgranted",
    "authorization_requestdenied",
    "insufficient privileges",
)

# AADSTS error codes and the class each one belongs to.  A code decides the
# class before any phrase does, because some messages borrow another class's
# words: AADSTS70043 is an expired refresh token that mentions "conditional
# access", and AADSTS50078 is an MFA claim that "has expired".
_AADSTS_CODE_RE = re.compile(r"aadsts(\d+)", re.IGNORECASE)
_AADSTS_KINDS: dict[str, AuthErrorKind] = {
    "700082": "expired",
    "70043": "expired",
    "50173": "expired",
    "700084": "expired",
    "50133": "expired",
    "50076": "mfa",
    "50079": "mfa",
    "50158": "mfa",
    "53003": "mfa",
    "50078": "mfa",
    "65001": "consent",
    "7000112": "consent",
}
_PLEASE_RUN_AZ_LOGIN_RE = re.compile(r"please run ['\"]?az login")


def classify_auth_error(msg: str) -> AuthErrorKind:
    """Classify an Azure CLI or Graph error message by what the user must do.

    - ``expired``: the sign-in has expired or was revoked; ``az login`` again.
    - ``not_logged_in``: there is no az session at all.
    - ``mfa``: MFA, a compliant device or another Conditional Access
      requirement blocks the request; a plain retry won't help.
    - ``consent``: a scope or consent is missing (``is_scope_error``).
    - ``other``: anything else, including ARM ``AuthorizationFailed``.

    Known AADSTS codes are matched exactly and take precedence over phrases.
    """
    for code in _AADSTS_CODE_RE.findall(msg):
        if code in _AADSTS_KINDS:
            return _AADSTS_KINDS[code]
    lowered = msg.lower()
    if "multi-factor" in lowered or "conditional access" in lowered:
        return "mfa"
    if any(token in lowered for token in _SCOPE_ERROR_TOKENS):
        return "consent"
    if "refresh token has expired" in lowered or "token is expired" in lowered:
        return "expired"
    if (
        _PLEASE_RUN_AZ_LOGIN_RE.search(lowered)
        or ("az login" in lowered and "not logged in" in lowered)
        or "no subscription found" in lowered
    ):
        return "not_logged_in"
    return "other"


def is_auth_error(msg: str) -> bool:
    """Return True if *msg* means the az CLI session has expired or is missing.

    MFA, Conditional Access and consent errors are not session errors: signing
    in again the same way doesn't fix them.  See :func:`classify_auth_error`.
    """
    return classify_auth_error(msg) in {"expired", "not_logged_in"}


def is_scope_error(msg: str) -> bool:
    """Return True if *msg* indicates a missing OAuth scope / consent."""
    lowered = msg.lower()
    return any(token in lowered for token in _SCOPE_ERROR_TOKENS)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Subscription:
    id: str
    name: str


@dataclass
class ManagementGroup:
    id: str  # short name / tenantId-based ID used in the ARM path
    name: str  # displayName


@dataclass
class EligibleRole:
    role_name: str
    role_definition_id: str
    # actual assignment scope: /subscriptions/{id} or
    # /providers/Microsoft.Management/managementGroups/{id}
    scope: str
    scope_display_name: str  # human-readable scope name
    principal_id: str
    eligibility_schedule_id: str  # short GUID used in linkedRoleEligibilityScheduleId
    expiry: str | None  # ISO 8601 datetime string or None
    is_active: bool = False  # True if already PIM-activated
    active_until: str | None = None  # end of the current activation (ISO 8601), if active

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
    active_until: str | None = None  # end of the current activation (ISO 8601), if active


@dataclass
class ActiveAssignment:
    """An active ARM role assignment (permanently assigned or PIM-activated)."""

    role_name: str
    scope: str
    scope_display_name: str
    expiry: str | None  # ISO 8601 datetime or None for permanent
    assignment_type: str  # "Assigned" (direct/inherited) or "Activated" (PIM)


@dataclass
class ActiveEntraAssignment:
    """An active Entra role assignment (permanently assigned or PIM-activated)."""

    role_name: str
    directory_scope_id: str  # "/" = tenant-wide
    expiry: str | None  # ISO 8601 datetime or None for permanent
    assignment_type: str  # "Assigned" (direct) or "Activated" (PIM)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(r"^P(?:\d+Y)?(?:\d+M)?(?:\d+D)?(?:T(?:\d+H)?(?:\d+M)?(?:\d+(?:\.\d+)?S)?)?$")


def validate_duration(s: str) -> bool:
    """Return True if *s* is a non-trivial ISO 8601 duration (e.g. PT8H)."""
    return bool(_DURATION_RE.match(s)) and s not in ("P", "PT")


def parse_duration(s: str) -> str:
    """Parse a human-friendly duration string to ISO 8601.

    Accepts ISO 8601 directly (e.g. ``PT1H``) or shorthand such as
    ``30m``, ``1h``, ``1h30m`` (case-insensitive).

    Raises :exc:`ValueError` for unrecognised input.
    """
    if validate_duration(s):
        return s
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?", s.lower())
    if m and (m.group(1) or m.group(2)):
        result = "PT"
        if m.group(1):
            result += f"{m.group(1)}H"
        if m.group(2):
            result += f"{m.group(2)}M"
        return result
    raise ValueError(f"Invalid duration {s!r}. Use e.g. '30m', '1h', '1h30m', or ISO 8601 like 'PT1H'.")


# ---------------------------------------------------------------------------
# Azure API calls
# ---------------------------------------------------------------------------


# The signed-in user's object ID, looked up once per process.  Role loads run
# in parallel (one per subscription in the TUI); the lock makes them share one
# ``az ad signed-in-user show`` instead of each starting its own.
_current_user_id: str | None = None
_current_user_lock = threading.Lock()


def get_current_user() -> str:
    """Return the object ID of the currently signed-in user.

    Only the ``id`` is requested (``--query id`` returns it as a JSON string),
    so the rest of the profile (mail, phone) is never read or logged.

    The ID is looked up once and then cached for the rest of the process;
    concurrent callers wait for the first lookup.  A failed lookup is not
    cached, so the next caller tries again.
    """
    global _current_user_id
    with _current_user_lock:
        if _current_user_id is None:
            _current_user_id = _run_az("ad", "signed-in-user", "show", "--query", "id", log_body=False)
        return _current_user_id


def reset_caches() -> None:
    """Forget the per-process caches: the signed-in user ID and the Graph access token.

    For tests, which must not see a value cached by an earlier test.  The
    Graph refresh token on disk is left alone.
    """
    global _current_user_id
    with _current_user_lock:
        _current_user_id = None
    forget_graph_access_token()


def check_auth() -> None:
    """Verify the az CLI session is valid by requesting a fresh token.

    Unlike `az account show`, this actually attempts a token refresh and
    will raise RuntimeError if the session has expired.  Only the expiry is
    requested (``--query expiresOn``), so the access token never leaves `az`.
    """
    _run_az("account", "get-access-token", "--query", "expiresOn", log_body=False)


def get_account_info() -> tuple[str, str]:
    """Return (user_name, tenant_display_name) from the active az session."""
    data = _run_az("account", "show")
    user = data.get("user", {}).get("name", "unknown")
    tenant = data.get("tenantDisplayName") or data.get("tenantId", "unknown")
    return user, tenant


def list_subscriptions() -> list[Subscription]:
    """Return all subscriptions visible to the current account."""
    data = _run_az("account", "list")
    return [Subscription(id=s["id"], name=s["name"]) for s in data]


def list_management_groups() -> list[ManagementGroup]:
    """Return all management groups visible to the current account."""
    data = _run_az("account", "management-group", "list")
    return [ManagementGroup(id=mg["name"], name=mg["displayName"]) for mg in data]


def list_eligible_roles_mg(mg_id: str) -> list[EligibleRole]:
    """List eligible PIM role assignments for the signed-in user in management group *mg_id*.

    *mg_id* is the short management group name (not the display name) as returned
    by ``az account management-group list`` (.name field).
    """
    scope = f"/providers/Microsoft.Management/managementGroups/{mg_id}"
    url = (
        f"https://management.azure.com{scope}"
        f"/providers/Microsoft.Authorization/roleEligibilityScheduleInstances"
        f"?$filter=asTarget()&api-version=2020-10-01"
    )
    user_id = get_current_user()
    active_ends = _list_active_role_keys(scope)
    data = _run_az("rest", "--method", "GET", "--url", url)
    roles: list[EligibleRole] = []
    for item in data.get("value", []):
        props = item.get("properties", {})
        expanded = props.get("expandedProperties", {})
        sched_path: str = props.get("roleEligibilityScheduleId", "")
        sched_id = sched_path.rsplit("/", 1)[-1] if "/" in sched_path else item.get("name", str(uuid.uuid4()))
        actual_scope = expanded.get("scope", {}).get("id") or scope
        role_def_id = props.get("roleDefinitionId", "")
        already_active = (role_def_id, actual_scope) in active_ends
        if already_active:
            log.debug("marking already-active role %s on %s", role_def_id, actual_scope)
        roles.append(
            EligibleRole(
                role_name=expanded.get("roleDefinition", {}).get("displayName", "Unknown"),
                role_definition_id=role_def_id,
                scope=actual_scope,
                scope_display_name=(expanded.get("scope", {}).get("displayName") or mg_id),
                principal_id=user_id,
                eligibility_schedule_id=sched_id,
                expiry=props.get("endDateTime"),
                is_active=already_active,
                active_until=active_ends.get((role_def_id, actual_scope)),
            )
        )
    return roles


def _list_active_role_keys(scope: str) -> dict[tuple[str, str], str | None]:
    """Map (role_definition_id, scope) of each currently active PIM assignment to its end.

    The end is the activation's ``endDateTime`` (ISO 8601), or ``None`` if it
    has none.  A failed lookup returns an empty mapping, so every role is
    listed as not active; the failure is logged as a warning.
    """
    url = (
        f"https://management.azure.com{scope}"
        f"/providers/Microsoft.Authorization/roleAssignmentScheduleInstances"
        f"?$filter=asTarget()&api-version=2020-10-01"
    )
    try:
        data = _run_az("rest", "--method", "GET", "--url", url)
    except RuntimeError as exc:
        log.warning("could not read active assignments for %s: %s", scope, exc)
        return {}
    ends: dict[tuple[str, str], str | None] = {}
    for item in data.get("value", []):
        props = item.get("properties", {})
        # Only count Activated (PIM-activated) assignments, not permanent ones
        if props.get("assignmentType") != "Activated":
            continue
        expanded = props.get("expandedProperties", {})
        role_def_id = props.get("roleDefinitionId", "")
        active_scope = expanded.get("scope", {}).get("id") or scope
        ends[(role_def_id, active_scope)] = props.get("endDateTime")
    return ends


def list_eligible_roles(subscription_id: str) -> list[EligibleRole]:
    """List eligible PIM role assignments for the signed-in user in *subscription_id*.

    Roles that are already active (PIM-activated) are included, with
    ``is_active=True``.
    """
    scope = f"/subscriptions/{subscription_id}"
    url = (
        f"https://management.azure.com{scope}"
        f"/providers/Microsoft.Authorization/roleEligibilityScheduleInstances"
        f"?$filter=asTarget()&api-version=2020-10-01"
    )
    # Resolve the signed-in user's own object ID (cached per process).
    # When a role eligibility is assigned to a group, the API returns the
    # group's principalId — but SelfActivate requires the requesting *user's*
    # object ID.  We always substitute the real user ID here so activation
    # works for both direct and group-based eligibilities.
    user_id = get_current_user()
    active_ends = _list_active_role_keys(scope)
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
        already_active = (role_def_id, actual_scope) in active_ends
        if already_active:
            log.debug("marking already-active role %s on %s", role_def_id, actual_scope)
        roles.append(
            EligibleRole(
                role_name=expanded.get("roleDefinition", {}).get("displayName", "Unknown"),
                role_definition_id=role_def_id,
                scope=actual_scope,
                scope_display_name=(expanded.get("scope", {}).get("displayName") or subscription_id),
                principal_id=user_id,
                eligibility_schedule_id=sched_id,
                expiry=props.get("endDateTime"),
                is_active=already_active,
                active_until=active_ends.get((role_def_id, actual_scope)),
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
    log.debug("activating role %s on %s (request %s)", role.role_name, role.scope, request_id)
    response = _run_az(
        "rest",
        "--method",
        "PUT",
        "--url",
        url,
        "--body",
        body,
        "--headers",
        "Content-Type=application/json",
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
_TOKEN_CACHE_PATH = os.path.expanduser("~/.cache/fomo/graph_token.json")

# Module-level token cache: (access_token, expiry_unix_timestamp)
_graph_token_cache: tuple[str, float] | None = None

# Serialises Graph token acquisition, so concurrent callers (the Entra tab and
# the Assignments screen) share one device-code flow instead of starting two.
_graph_token_lock = threading.RLock()


def forget_graph_access_token() -> None:
    """Drop the in-process Graph access token; the cached refresh token stays.

    The next Graph call refreshes the token from ``graph_token.json`` or, if
    the user has deleted that file to sign in again, starts a new device-code
    sign-in.  Without this, a retry in the same session would keep using the
    old access token for up to an hour.
    """
    global _graph_token_cache
    _graph_token_cache = None


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
    """Persist access + refresh tokens to disk, privately and atomically.

    The cache directory (fomo's own) is made 0700 and the file 0600, through
    a temp file that is renamed over the cache path, so the tokens are never
    readable by others and a symlink at the path is replaced, not followed
    (see :func:`fomo.state.write_private_json`).
    """
    payload = {k: token_data[k] for k in ("access_token", "refresh_token", "expires_in") if k in token_data}
    payload["tenant_id"] = tenant_id
    payload["cached_at"] = time.time()
    write_private_json(_TOKEN_CACHE_PATH, payload)


def _token_endpoint(tenant_id: str) -> str:
    return f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"


def _try_refresh_token(tenant_id: str, refresh_token: str) -> dict | None:
    """Attempt a silent token refresh. Returns the token dict or None on failure."""
    data = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "client_id": _GRAPH_CLIENT_ID,
            "refresh_token": refresh_token,
            "scope": _GRAPH_SCOPES,
        }
    ).encode()
    req = urllib.request.Request(_token_endpoint(tenant_id), data=data, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError:
        return None


# Browsers that run inside the terminal.  fomo never opens one: it would take
# over the screen that shows the device code (and the TUI).
_CONSOLE_BROWSERS = frozenset({"lynx", "w3m", "links", "elinks", "www-browser"})

# Upper bound, in seconds, for the device-code poll interval, whatever the
# server asks for.
_MAX_POLL_INTERVAL = 30

# Non-JSON poll answers in a row (a proxy or gateway error page, say) before
# the sign-in gives up.
_MAX_NON_JSON_POLLS = 3


def _is_wsl() -> bool:
    """True when running under Windows Subsystem for Linux."""
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        return "microsoft" in os.uname().release.lower()
    except (AttributeError, OSError):
        return False


def _platform() -> Literal["macos", "windows", "wsl", "unix"]:
    """The kind of desktop fomo runs on, as far as opening a browser goes."""
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("win"):
        return "windows"
    return "wsl" if _is_wsl() else "unix"


def _can_open_browser() -> bool:
    """Return True if a browser opened now would appear in front of the user.

    - macOS and Windows: always.
    - WSL: when ``wslview`` is on ``PATH`` or ``BROWSER`` is set.
    - Linux and other Unix systems: when there is a display (``DISPLAY`` or
      ``WAYLAND_DISPLAY``) and the session is not over SSH, where a browser
      would open on the remote machine, if anywhere.
    """
    kind = _platform()
    if kind in ("macos", "windows"):
        return True
    if kind == "wsl":
        return bool(shutil.which("wslview") or os.environ.get("BROWSER"))
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        return False
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _is_console_browser(browser: webbrowser.BaseBrowser) -> bool:
    """Return True if *browser* runs in the terminal (lynx, w3m, links, elinks, www-browser).

    A command found on ``PATH`` is also judged by the file it links to, so a
    ``BROWSER`` or alternatives symlink to ``w3m`` counts as ``w3m``.
    """
    words = (getattr(browser, "name", "") or "").split()
    if not words:
        return False
    command = words[0]
    names = {os.path.basename(command).lower()}
    path = shutil.which(command)
    if path:
        names.add(os.path.basename(os.path.realpath(path)).lower())
    return not names.isdisjoint(_CONSOLE_BROWSERS)


def _pick_browser() -> webbrowser.BaseBrowser:
    """Return the browser to open: ``wslview`` on WSL unless ``BROWSER`` says otherwise, else the default."""
    if "BROWSER" not in os.environ and _platform() == "wsl":
        wslview = shutil.which("wslview")
        if wslview:
            return webbrowser.BackgroundBrowser(wslview)
    return webbrowser.get()


def _open_browser(url: str) -> None:
    """Open *url* in a graphical browser if one can be shown; never fail.

    The device code is always shown as text as well, so a browser that can't
    be opened (no display, SSH, only a text-mode browser) costs nothing.
    """
    if not _can_open_browser():
        log.debug("not opening a browser: no display, or an SSH session")
        return
    try:
        browser = _pick_browser()
        if _is_console_browser(browser):
            log.debug("not opening text-mode browser %s", getattr(browser, "name", "?"))
            return
        browser.open(url)
    except Exception as exc:
        log.debug("could not open a browser: %s", exc)


def _json_object(raw: bytes) -> dict | None:
    """Parse *raw* as a JSON object; None if it isn't one (an HTML error page, say)."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _error_body(exc: urllib.error.HTTPError) -> bytes:
    """The body of an HTTP error response, or b"" if it can't be read."""
    try:
        return exc.read()
    except (OSError, ValueError):
        return b""


def _device_code_flow(
    tenant_id: str,
    on_device_code: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> dict:
    """Run the OAuth 2.0 device authorization grant and return the token dict.

    Calls *on_device_code* with the user-facing message once the device code
    is ready, then opens the verification URL in a browser (when one can be
    shown, see :func:`_open_browser`) and polls until the user completes
    authentication.

    Polling tolerates a busy or flaky endpoint: HTTP 429 and 5xx answers, and
    answers that aren't JSON, are retried after the poll interval (at most
    30 s).  Three non-JSON answers in a row end the sign-in with
    "Graph sign-in failed: HTTP <code>".
    """
    dc_req = urllib.request.Request(
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/devicecode",
        data=urllib.parse.urlencode(
            {
                "client_id": _GRAPH_CLIENT_ID,
                "scope": _GRAPH_SCOPES,
            }
        ).encode(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(dc_req) as resp:
            status = getattr(resp, "status", 200)
            dc = _json_object(resp.read())
    except urllib.error.HTTPError as exc:
        error_body = _json_object(_error_body(exc)) or {}
        detail = error_body.get("error_description") or error_body.get("error") or exc.reason or ""
        raise RuntimeError(_redact(f"Could not start Graph sign-in: HTTP {exc.code} {detail}".rstrip())) from None
    if dc is None or "device_code" not in dc:
        raise RuntimeError(f"Could not start Graph sign-in: HTTP {status} unexpected response")

    if on_device_code is not None:
        user_code = dc.get("user_code", "")
        verify_url = dc.get("verification_uri", "")
        on_device_code(f"{verify_url}\n{user_code}")

    # Open the browser to the pre-filled URL when available.
    browser_url = dc.get("verification_uri_complete") or dc.get("verification_uri", "")
    if browser_url:
        _open_browser(browser_url)

    interval = min(int(dc.get("interval", 5)), _MAX_POLL_INTERVAL)
    deadline = time.time() + int(dc.get("expires_in", 900))
    token_endpoint = _token_endpoint(tenant_id)
    non_json = 0  # non-JSON answers in a row

    while time.time() < deadline:
        if stop_event is not None:
            stop_event.wait(interval)
            if stop_event.is_set():
                raise RuntimeError("Authentication cancelled.")
        else:
            time.sleep(interval)
        poll_req = urllib.request.Request(
            token_endpoint,
            data=urllib.parse.urlencode(
                {
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": _GRAPH_CLIENT_ID,
                    "device_code": dc["device_code"],
                }
            ).encode(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(poll_req) as resp:
                code = getattr(resp, "status", 200)
                body = _json_object(resp.read())
        except urllib.error.HTTPError as exc:
            code = exc.code
            body = _json_object(_error_body(exc))
        else:
            if body is not None:
                return body

        if body is None:
            non_json += 1
            if non_json >= _MAX_NON_JSON_POLLS:
                raise RuntimeError(f"Graph sign-in failed: HTTP {code}")
            log.debug("device-code poll: HTTP %d without a JSON body, retrying", code)
            continue
        non_json = 0
        if code == 429 or code >= 500:
            log.debug("device-code poll: HTTP %d, retrying", code)
            continue
        error = body.get("error", "")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval = min(interval + 5, _MAX_POLL_INTERVAL)
            continue
        if error == "access_denied":
            raise RuntimeError("Graph authentication was denied.")
        if error == "expired_token":
            raise RuntimeError("Device code expired — please try again.")
        raise RuntimeError(f"Graph authentication failed: {error}: {body.get('error_description', '')}")

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

    Callers are serialised: a second caller waits for the first one and then
    reuses its token.  A caller whose *stop_event* is set while it waits, or
    before it would start a device-code flow, gets "Authentication cancelled."
    """
    global _graph_token_cache
    if stop_event is None:
        _graph_token_lock.acquire()
    else:
        while not _graph_token_lock.acquire(timeout=0.1):
            if stop_event.is_set():
                raise RuntimeError("Authentication cancelled.")
    try:
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

        # 3. Interactive device code flow -- unless the caller has gone away
        # (e.g. its screen closed while it waited for another caller's flow).
        if stop_event is not None and stop_event.is_set():
            raise RuntimeError("Authentication cancelled.")
        tenant_id = _get_tenant_id()
        log.debug("starting device code flow for tenant %s", tenant_id)
        token_data = _device_code_flow(tenant_id, on_device_code, stop_event)
        expiry = now + float(token_data.get("expires_in", 3600)) - 60
        _graph_token_cache = (token_data["access_token"], expiry)
        _save_token_cache(token_data, tenant_id)
        log.debug("Graph token acquired via device code, expires in %.0fs", token_data.get("expires_in", 3600))
        return token_data["access_token"]
    finally:
        _graph_token_lock.release()


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
        # The message is shown to the user and logged by the screens.
        raise RuntimeError(_redact(str(detail))) from None


def _list_active_entra_role_def_ids(principal_id: str) -> dict[str, str | None]:
    """Map the role definition IDs currently PIM-activated in Entra for *principal_id* to their end.

    The end is the activation's ``endDateTime`` (ISO 8601), or ``None`` if it
    has none.  A failed lookup returns an empty mapping, so every role is
    listed as not active; the failure is logged as a warning.
    """
    filter_val = urllib.parse.quote(
        f"principalId eq '{principal_id}' and assignmentType eq 'Activated'",
        safe="'()",
    )
    url = f"{_GRAPH}/v1.0/roleManagement/directory/roleAssignmentScheduleInstances?$filter={filter_val}"
    try:
        data = _run_graph("GET", url)
    except RuntimeError as exc:
        log.warning("could not read active assignments for Entra roles: %s", exc)
        return {}
    return {item.get("roleDefinitionId", ""): item.get("endDateTime") for item in data.get("value", [])}


def list_entra_eligible_roles(
    on_device_code: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> list[EntraEligibleRole]:
    """List eligible Entra PIM role assignments for the signed-in user."""
    user_id = get_current_user()
    # Acquire the token once (triggering device code if needed) so all
    # subsequent _run_graph calls hit the in-process cache silently.
    _get_graph_token(on_device_code, stop_event)
    active_ends = _list_active_entra_role_def_ids(user_id)
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
                eligibility_schedule_id=item.get("roleEligibilityScheduleId", item.get("id", str(uuid.uuid4()))),
                expiry=item.get("endDateTime"),
                directory_scope_id=item.get("directoryScopeId", "/"),
                is_active=role_def_id in active_ends,
                active_until=active_ends.get(role_def_id),
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


# ---------------------------------------------------------------------------
# Active assignment listings (for the Assignments screen)
# ---------------------------------------------------------------------------


def list_active_arm_assignments() -> list[ActiveAssignment]:
    """List all active ARM role assignments for the current user across all scopes.

    Uses the tenant-level roleAssignmentScheduleInstances endpoint with the
    asTarget() filter so a single request returns assignments across every
    subscription/resource-group/resource the caller can see.
    """
    url = (
        "https://management.azure.com"
        "/providers/Microsoft.Authorization/roleAssignmentScheduleInstances"
        "?$filter=asTarget()&api-version=2020-10-01"
    )
    data = _run_az("rest", "--method", "GET", "--url", url)
    assignments: list[ActiveAssignment] = []
    for item in data.get("value", []):
        props = item.get("properties", {})
        expanded = props.get("expandedProperties", {})
        scope_id = expanded.get("scope", {}).get("id", "")
        assignments.append(
            ActiveAssignment(
                role_name=expanded.get("roleDefinition", {}).get("displayName", "Unknown"),
                scope=scope_id,
                scope_display_name=(expanded.get("scope", {}).get("displayName") or scope_id),
                expiry=props.get("endDateTime"),
                assignment_type=props.get("assignmentType", "Assigned"),
            )
        )
    return assignments


def list_active_entra_assignments(
    on_device_code: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> list[ActiveEntraAssignment]:
    """List all active Entra role assignments for the current user.

    Uses roleAssignmentScheduleInstances so that expiry and assignment type
    (Assigned vs PIM-Activated) are available.
    """
    user_id = get_current_user()
    _get_graph_token(on_device_code, stop_event)
    filter_val = urllib.parse.quote(f"principalId eq '{user_id}'", safe="'()")
    url = (
        f"{_GRAPH}/v1.0/roleManagement/directory/roleAssignmentScheduleInstances"
        f"?$filter={filter_val}&$expand=roleDefinition"
    )
    data = _run_graph("GET", url)
    assignments: list[ActiveEntraAssignment] = []
    for item in data.get("value", []):
        role_def = item.get("roleDefinition") or {}
        assignments.append(
            ActiveEntraAssignment(
                role_name=role_def.get("displayName", "Unknown"),
                directory_scope_id=item.get("directoryScopeId", "/"),
                expiry=item.get("endDateTime"),
                assignment_type=item.get("assignmentType", "Assigned"),
            )
        )
    return assignments
