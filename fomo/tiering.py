"""AzTier blast-radius tiering for Azure and Entra roles.

Data source: https://github.com/emiliensocchi/azure-tiering at the commit in
``_TIERING_REF``.  Fetched on demand and cached for a week at
~/.cache/fomo/tiering_{azure,entra}.json; an older cached copy is used when a
refresh fails.  Tier data is optional: loading it never raises, and without it
the index is simply empty.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request
from typing import TypedDict

log = logging.getLogger(__name__)

_CACHE_DIR = os.path.expanduser("~/.cache/fomo")
_CACHE_TTL = 7 * 24 * 3600  # 1 week

# Upstream commit of emiliensocchi/azure-tiering that the tier data is read
# from.  Pinned so that the risk labels shown before a privileged activation
# only change with a fomo release, not whenever the third-party repo changes.
# To bump it: pick a commit from
# https://github.com/emiliensocchi/azure-tiering/commits/main, review the diff
# of the two JSON files below since the current ref, and paste the full
# 40-character SHA here.  Existing user caches pick up the new data once they
# are older than _CACHE_TTL.
_TIERING_REF = "4afd962a8db1c53d42fb6ef88a008c4b5d074ec9"
_TIERING_BASE = f"https://raw.githubusercontent.com/emiliensocchi/azure-tiering/{_TIERING_REF}"
_AZURE_URL = f"{_TIERING_BASE}/Azure%20roles/tiered-azure-roles.json"
_ENTRA_URL = f"{_TIERING_BASE}/Entra%20roles/tiered-entra-roles.json"

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

# Serialise ensure_*_loaded() so concurrent workers load each index once.
# Separate locks keep an Azure load from blocking an Entra load.
_azure_lock = threading.Lock()
_entra_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _cache_path(kind: str) -> str:
    return os.path.join(_CACHE_DIR, f"tiering_{kind}.json")


def _read_disk_cache(kind: str) -> tuple[list | None, bool]:
    """Return the cached data for *kind* and whether it is still fresh.

    Stale data (older than ``_CACHE_TTL``) is returned too, as a fallback for
    when a refresh fails.  The data is None if there is no readable cache.
    """
    path = _cache_path(kind)
    try:
        age = time.time() - os.path.getmtime(path)
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None, False
    if not isinstance(data, list):
        return None, False
    return data, age <= _CACHE_TTL


def _save_disk_cache(kind: str, data: list) -> None:
    """Write the cache atomically (temp file in the same directory, then rename).

    Never raises: an unwritable cache directory only costs a refetch later.
    """
    path = _cache_path(kind)
    tmp: str | None = None
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=_CACHE_DIR, prefix=f".tiering_{kind}.", suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
        tmp = None
    except (OSError, TypeError, ValueError) as exc:
        log.warning("tiering: could not write cache %s: %s", path, exc)
    finally:
        if tmp is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp)


def _fetch_json(url: str) -> list | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "fomo/tiering"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        log.debug("tiering: fetch failed for %s: %s", url, exc)
        return None
    if not isinstance(data, list):
        log.debug("tiering: %s returned %s, not a list", url, type(data).__name__)
        return None
    return data


def _text(item: dict, *keys: str) -> str:
    """Return the first non-empty string among *keys* of *item*, or ""."""
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _build_index(data: object) -> dict[str, TierInfo]:
    """Index tier entries by lower-case role GUID, skipping malformed entries.

    An entry is kept only if it is an object with a non-empty string ``id``
    and an integer-convertible ``tier``.  Text fields that aren't strings
    are treated as empty.
    """
    index: dict[str, TierInfo] = {}
    if not isinstance(data, list):
        log.debug("tiering: ignoring tier data of type %s", type(data).__name__)
        return index
    for pos, item in enumerate(data):
        if not isinstance(item, dict):
            log.debug("tiering: skipping entry %d: not an object", pos)
            continue
        raw_id = item.get("id")
        guid = raw_id.lower().strip() if isinstance(raw_id, str) else ""
        if not guid:
            log.debug("tiering: skipping entry %d: id %r is not a non-empty string", pos, raw_id)
            continue
        try:
            tier = int(item["tier"])
        except (KeyError, TypeError, ValueError, OverflowError):
            log.debug("tiering: skipping entry %d (%s): tier %r is not an integer", pos, guid, item.get("tier"))
            continue
        index[guid] = TierInfo(
            tier=tier,
            name=_text(item, "assetName"),
            attack_path=_text(item, "shortestPath", "worstCaseScenario", "providesFullAccessTo"),
        )
    return index


def _load_index(kind: str, url: str, allow_network: bool) -> dict[str, TierInfo]:
    """Build the *kind* index from the fresh cache, a download, or the stale cache, in that order."""
    cached, fresh = _read_disk_cache(kind)
    if cached is not None and fresh:
        index = _build_index(cached)
        if index:
            return index
    if allow_network:
        log.debug("tiering: fetching %s tier data from GitHub", kind)
        fetched = _fetch_json(url)
        if fetched is not None:
            index = _build_index(fetched)
            if index:
                _save_disk_cache(kind, fetched)
                return index
            log.warning("tiering: downloaded %s tier data has no usable entries", kind)
    else:
        log.info("tiering: network disabled; using only cached %s tier data", kind)
    if cached is not None:
        log.info("tiering: using stale cached %s tier data", kind)
        return _build_index(cached)
    log.warning("tiering: no %s tier data available; blast-radius badges will be absent", kind)
    return {}


# ---------------------------------------------------------------------------
# Public API — called from background worker threads
# ---------------------------------------------------------------------------


def load_azure(allow_network: bool = True) -> None:
    """Load (or refresh) the Azure roles tiering index.

    Safe to call from a background thread.  Reads the disk cache if fresh,
    otherwise fetches from GitHub unless *allow_network* is False, and falls
    back to a stale cache if that yields nothing.  Populates the
    module-level lookup dict.
    """
    global _azure_index
    _azure_index = _load_index("azure", _AZURE_URL, allow_network)
    log.debug("tiering: loaded %d Azure role entries", len(_azure_index))


def load_entra(allow_network: bool = True) -> None:
    """Load (or refresh) the Entra roles tiering index.

    Safe to call from a background thread; see :func:`load_azure`.
    """
    global _entra_index
    _entra_index = _load_index("entra", _ENTRA_URL, allow_network)
    log.debug("tiering: loaded %d Entra role entries", len(_entra_index))


def ensure_azure_loaded(allow_network: bool = True) -> None:
    """Load the Azure tiering index unless it is already populated.

    Thread-safe: concurrent callers wait for the first load instead of
    starting their own.  An empty index (no data available) is retried on
    the next call.  Never raises: tier data is optional, so any failure is
    logged and leaves the index empty.  With *allow_network* False (demo
    mode) only the disk cache is read.
    """
    with _azure_lock:
        if _azure_index:
            return
        try:
            load_azure(allow_network=allow_network)
        except Exception:
            log.warning("tiering: could not load Azure tier data; badges will be absent", exc_info=True)


def ensure_entra_loaded(allow_network: bool = True) -> None:
    """Load the Entra tiering index unless it is already populated.

    Thread-safe and never raises; see :func:`ensure_azure_loaded`.
    """
    with _entra_lock:
        if _entra_index:
            return
        try:
            load_entra(allow_network=allow_network)
        except Exception:
            log.warning("tiering: could not load Entra tier data; badges will be absent", exc_info=True)


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
