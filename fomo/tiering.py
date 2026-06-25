"""AzTier blast-radius tiering for Azure and Entra roles.

Data source: https://github.com/emiliensocchi/azure-tiering
Fetched once and cached at ~/.cache/fomo/tiering_{azure,entra}.json.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import TypedDict

log = logging.getLogger(__name__)

_CACHE_DIR = os.path.expanduser("~/.cache/fomo")
_CACHE_TTL = 7 * 24 * 3600  # 1 week

_AZURE_URL = (
    "https://raw.githubusercontent.com/emiliensocchi/azure-tiering/main"
    "/Azure%20roles/tiered-azure-roles.json"
)
_ENTRA_URL = (
    "https://raw.githubusercontent.com/emiliensocchi/azure-tiering/main"
    "/Entra%20roles/tiered-entra-roles.json"
)

# Tier display metadata
TIER_BADGE: dict[int, str] = {0: "🔴", 1: "🟠", 2: "🟡", 3: "🟢"}
TIER_LABEL: dict[int, str] = {
    0: "T0 · privilege ascender",
    1: "T1 · lateral navigator",
    2: "T2 · data explorer",
    3: "T3 · unprivileged",
}
# Rich-markup colors readable in both light and dark terminal themes
TIER_COLOUR: dict[int, str] = {
    0: "#c0392b",  # dark red
    1: "#d35400",  # dark orange
    2: "#2980b9",  # medium blue
    3: "#27ae60",  # medium green
}


class TierInfo(TypedDict):
    tier: int
    name: str
    attack_path: str  # shortestPath (T0/T1) or worstCaseScenario (T2/T3)


# Module-level lookup dicts populated by load_azure() / load_entra()
_azure_index: dict[str, TierInfo] = {}
_entra_index: dict[str, TierInfo] = {}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _cache_path(kind: str) -> str:
    return os.path.join(_CACHE_DIR, f"tiering_{kind}.json")


def _load_disk_cache(kind: str) -> list | None:
    path = _cache_path(kind)
    try:
        mtime = os.path.getmtime(path)
        if time.time() - mtime > _CACHE_TTL:
            return None
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _save_disk_cache(kind: str, data: list) -> None:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    path = _cache_path(kind)
    try:
        with open(path, "w") as f:
            json.dump(data, f)
    except OSError as exc:
        log.warning("tiering: could not write cache %s: %s", path, exc)


def _fetch_json(url: str) -> list | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "fomo/tiering"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as exc:  # noqa: BLE001
        log.debug("tiering: fetch failed for %s: %s", url, exc)
        return None


def _build_index(data: list) -> dict[str, TierInfo]:
    index: dict[str, TierInfo] = {}
    for item in data:
        guid = item.get("id", "").lower().strip()
        if not guid:
            continue
        try:
            tier = int(item["tier"])
        except (KeyError, ValueError):
            continue
        attack_path = (
            item.get("shortestPath")
            or item.get("worstCaseScenario")
            or item.get("providesFullAccessTo")
            or ""
        )
        index[guid] = TierInfo(
            tier=tier,
            name=item.get("assetName", ""),
            attack_path=attack_path,
        )
    return index


# ---------------------------------------------------------------------------
# Public API — called from background worker threads
# ---------------------------------------------------------------------------

def load_azure() -> None:
    """Load (or refresh) the Azure roles tiering index.

    Safe to call from a background thread.  Reads disk cache if fresh,
    otherwise fetches from GitHub.  Populates the module-level lookup dict.
    """
    global _azure_index
    data = _load_disk_cache("azure")
    if data is None:
        log.debug("tiering: fetching Azure roles from GitHub")
        data = _fetch_json(_AZURE_URL) or []
        if data:
            _save_disk_cache("azure", data)
        else:
            log.warning("tiering: could not load Azure tiering data; blast-radius badges will be absent")
    _azure_index = _build_index(data)
    log.debug("tiering: loaded %d Azure role entries", len(_azure_index))


def load_entra() -> None:
    """Load (or refresh) the Entra roles tiering index.

    Safe to call from a background thread.
    """
    global _entra_index
    data = _load_disk_cache("entra")
    if data is None:
        log.debug("tiering: fetching Entra roles from GitHub")
        data = _fetch_json(_ENTRA_URL) or []
        if data:
            _save_disk_cache("entra", data)
        else:
            log.warning("tiering: could not load Entra tiering data; blast-radius badges will be absent")
    _entra_index = _build_index(data)
    log.debug("tiering: loaded %d Entra role entries", len(_entra_index))


def get_azure_tier(role_definition_id: str) -> TierInfo | None:
    """Return TierInfo for an Azure role by its definition GUID or full path."""
    guid = role_definition_id.rsplit("/", 1)[-1].lower()
    return _azure_index.get(guid)


def get_entra_tier(role_definition_id: str) -> TierInfo | None:
    """Return TierInfo for an Entra role by its definition GUID."""
    return _entra_index.get(role_definition_id.lower())


def tier_badge(tier: int) -> str:
    """Return the colour-coded emoji for a given tier number."""
    return TIER_BADGE.get(tier, "⚪")


def tier_label(tier: int) -> str:
    """Return a short human-readable label for a tier number."""
    return TIER_LABEL.get(tier, "untiered")


def high_risk_summary(roles_tier_infos: list[TierInfo]) -> str:
    """Build a concise warning string for a list of high-risk (T0/T1) TierInfos."""
    if not roles_tier_infos:
        return ""
    lines: list[str] = []
    for info in roles_tier_infos[:3]:  # cap at 3 to keep notification readable
        badge = tier_badge(info["tier"])
        path = info["attack_path"]
        # Truncate long paths
        if len(path) > 120:
            path = path[:117] + "…"
        lines.append(f"{badge} {info['name']}: {path}")
    if len(roles_tier_infos) > 3:
        lines.append(f"…and {len(roles_tier_infos) - 3} more")
    return "\n".join(lines)
