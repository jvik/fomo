"""fomo's private files on disk, and the recent activations kept in one of them.

:func:`write_private_json` writes a file that only the user may read, such as
the cached Graph refresh token or the state file.

The state file, ``$XDG_STATE_HOME/fomo/state.json`` (by default
``~/.local/state/fomo/state.json``), remembers the last few TUI activations
(:class:`Recent`), justification included, so that the scope screen can
start one again with a single key.  It is never written in demo mode or with
``FOMO_NO_STATE=1``: :func:`open_store` then returns a store that only lasts
for the session.  A corrupt or unreadable file is ignored.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import stat
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, Protocol, TypeGuard, TypeVar

if TYPE_CHECKING:
    from fomo.azure import EligibleRole, EntraEligibleRole

log = logging.getLogger(__name__)

STATE_VERSION = 1
#: How many recent activations are kept (the keys 1–5 start them).
MAX_RECENT = 5
#: Set to anything but "" or "0" to keep nothing on disk.
NO_STATE_ENV = "FOMO_NO_STATE"

RecentKind = Literal["azure", "entra"]
#: Azure: (role definition GUID, scope).  Entra: (role definition ID, directory scope ID).
Target = tuple[str, str]


def write_private_json(path: str, payload: object) -> None:
    """Write *payload* as JSON to *path*, privately and atomically.

    The file's directory (fomo's own) is made 0700, and tightened to 0700 if
    it already exists with wider permissions; its parents are left alone.
    The JSON goes to a new temp file that is created 0600, never through an
    existing file or symlink, and is then renamed over *path*, so it is never
    readable by others, a symlink at *path* is replaced rather than followed,
    and a failed write leaves the old file as it was.  Errors are raised.
    """
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    if stat.S_IMODE(os.stat(directory).st_mode) & 0o077:
        os.chmod(directory, 0o700)
    tmp = f"{path}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


# ---------------------------------------------------------------------------
# Recent activations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Recent:
    """One remembered activation: which roles, with which justification and duration.

    *labels* holds the display text of each target ("Key Vault Administrator ·
    Contoso Production"), in the same order.  *subscriptions* (Azure only)
    are the subscriptions whose roles were listed, to list them again.
    """

    kind: RecentKind
    targets: tuple[Target, ...]
    labels: tuple[str, ...]
    justification: str
    duration: str
    ts: str = ""
    subscriptions: tuple[str, ...] = ()

    @property
    def key(self) -> tuple[str, frozenset[Target]]:
        """Entries with the same key activate the same roles; only the newest is kept."""
        return (self.kind, frozenset(_norm(target) for target in self.targets))

    def label(self, index: int) -> str:
        """The display text of target *index*."""
        if index < len(self.labels) and self.labels[index]:
            return self.labels[index]
        return " · ".join(self.targets[index])

    def to_json(self) -> dict[str, object]:
        data: dict[str, object] = {"kind": self.kind}
        if self.kind == "azure":
            data["subscriptions"] = list(self.subscriptions)
        data.update(
            targets=[list(target) for target in self.targets],
            labels=list(self.labels),
            justification=self.justification,
            duration=self.duration,
            ts=self.ts,
        )
        return data

    @classmethod
    def from_json(cls, data: object) -> Recent | None:
        """The entry in *data*, or ``None`` if it is malformed."""
        if not isinstance(data, dict):
            return None
        kind = data.get("kind")
        targets = data.get("targets")
        justification = data.get("justification")
        duration = data.get("duration")
        if kind not in ("azure", "entra") or not isinstance(justification, str) or not isinstance(duration, str):
            return None
        if not isinstance(targets, list) or not targets or not all(_is_target(target) for target in targets):
            return None
        subscriptions: list[str] = []
        if kind == "azure":
            listed = data.get("subscriptions")
            if not _is_string_list(listed) or not listed:
                return None
            subscriptions = listed
        labels = data.get("labels")
        ts = data.get("ts")
        return cls(
            kind=kind,
            targets=tuple((first, second) for first, second in targets),
            labels=tuple(labels) if _is_string_list(labels) else (),
            justification=justification,
            duration=duration,
            ts=ts if isinstance(ts, str) else "",
            subscriptions=tuple(subscriptions),
        )


def _norm(target: Target) -> Target:
    """Targets compare without regard to case: Azure IDs come in either."""
    return (target[0].casefold(), target[1].casefold())


def _is_target(value: object) -> bool:
    return isinstance(value, list) and len(value) == 2 and all(isinstance(part, str) and part for part in value)


def _is_string_list(value: object) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _merged(entry: Recent, entries: Iterable[Recent]) -> list[Recent]:
    """*entry* first, then *entries* without the one for the same roles, at most MAX_RECENT."""
    return [entry, *(other for other in entries if other.key != entry.key)][:MAX_RECENT]


def read_recent(path: str) -> list[Recent]:
    """The recent activations in the state file at *path*, newest first.

    A missing file is empty.  An unreadable, corrupt or unknown file is
    ignored (logged at debug level), and so is a malformed entry.
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, ValueError, RecursionError) as exc:
        log.debug("ignoring the state file %s: %s", path, exc)
        return []
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION or not isinstance(data.get("recent"), list):
        log.debug("ignoring the state file %s: not a version %d state file", path, STATE_VERSION)
        return []
    entries: list[Recent] = []
    for item in data["recent"]:
        entry = Recent.from_json(item)
        if entry is None:
            log.debug("ignoring a malformed recent activation in %s", path)
        elif all(other.key != entry.key for other in entries):
            entries.append(entry)
    return entries[:MAX_RECENT]


class RecentStore:
    """Recent activations for this session only (demo mode, ``FOMO_NO_STATE``)."""

    def __init__(self, entries: Iterable[Recent] = ()) -> None:
        self._entries: list[Recent] = list(entries)[:MAX_RECENT]

    def entries(self) -> list[Recent]:
        """The recent activations, newest first."""
        return list(self._entries)

    def add(self, entry: Recent) -> None:
        """Remember *entry* as the newest, replacing an older one for the same roles."""
        self._entries = _merged(entry, self._entries)


class FileRecentStore(RecentStore):
    """Recent activations kept in the state file at *path*."""

    def __init__(self, path: str) -> None:
        super().__init__(read_recent(path))
        self.path = path

    def add(self, entry: Recent) -> None:
        """Remember *entry* and save the file; a failed save is logged, never raised."""
        # Merge into the file as it is now: another fomo may have written it.
        self._entries = _merged(entry, read_recent(self.path))
        payload = {"version": STATE_VERSION, "recent": [recent.to_json() for recent in self._entries]}
        try:
            write_private_json(self.path, payload)
        except OSError as exc:
            log.warning("could not save recent activations to %s: %s", self.path, exc)


def state_path() -> str:
    """``$XDG_STATE_HOME/fomo/state.json``; ``~/.local/state`` if that isn't an absolute path."""
    base = os.environ.get("XDG_STATE_HOME", "")
    if not os.path.isabs(base):
        base = os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "fomo", "state.json")


def state_disabled() -> bool:
    """True when ``FOMO_NO_STATE`` is set to anything but "" or "0"."""
    return os.environ.get(NO_STATE_ENV, "").strip() not in ("", "0")


def open_store(demo_mode: bool) -> RecentStore:
    """The state file's store, or a session-only one in demo mode or with ``FOMO_NO_STATE``."""
    if demo_mode or state_disabled():
        return RecentStore()
    return FileRecentStore(state_path())


def now_iso() -> str:
    """The current time for :attr:`Recent.ts`, e.g. "2026-11-12T14:32:05+00:00"."""
    return datetime.now(UTC).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Roles ↔ targets
# ---------------------------------------------------------------------------


def azure_target(role: EligibleRole) -> Target:
    """The same role on the same scope, whichever subscription listed it.

    The role definition ID includes the subscription it was listed through,
    so only its trailing GUID is kept (as the roles screen de-duplicates).
    """
    return (role.role_definition_id.rsplit("/", 1)[-1], role.scope)


def entra_target(role: EntraEligibleRole) -> Target:
    return (role.role_definition_id, role.directory_scope_id)


def azure_label(role: EligibleRole) -> str:
    return f"{role.role_name} · {role.scope_display_name}"


def entra_label(role: EntraEligibleRole) -> str:
    scope = "" if role.directory_scope_id == "/" else f" {role.directory_scope_id}"
    return f"{role.role_name} · Entra{scope}"


def azure_recent(
    roles: Sequence[EligibleRole], subscriptions: Sequence[str], justification: str, duration: str
) -> Recent:
    return Recent(
        kind="azure",
        targets=tuple(azure_target(role) for role in roles),
        labels=tuple(azure_label(role) for role in roles),
        justification=justification,
        duration=duration,
        ts=now_iso(),
        subscriptions=tuple(subscriptions),
    )


def entra_recent(roles: Sequence[EntraEligibleRole], justification: str, duration: str) -> Recent:
    return Recent(
        kind="entra",
        targets=tuple(entra_target(role) for role in roles),
        labels=tuple(entra_label(role) for role in roles),
        justification=justification,
        duration=duration,
        ts=now_iso(),
    )


@dataclass(frozen=True)
class TargetMatch:
    """How a recent entry's targets compare with the roles that are eligible now."""

    #: Indices into the roles of the targets that can be activated.
    ready: tuple[int, ...]
    #: Labels of the targets that are active already.
    active: tuple[str, ...]
    #: Labels of the targets that aren't among the roles (no longer eligible, or not loaded).
    missing: tuple[str, ...]

    @property
    def complete(self) -> bool:
        """Every target can be activated."""
        return not self.active and not self.missing

    def problems(self) -> str:
        """What stops the entry from starting by itself, as plain text lines."""
        lines = []
        if self.active:
            lines.append(f"Already active: {', '.join(self.active)}")
        if self.missing:
            lines.append(f"Not eligible or not loaded: {', '.join(self.missing)}")
        lines.append("Check the selection, then press Enter." if self.ready else "Nothing left to activate.")
        return "\n".join(lines)


class _Activatable(Protocol):
    @property
    def is_active(self) -> bool: ...


RoleT = TypeVar("RoleT", bound=_Activatable)


def match_targets(entry: Recent, roles: Sequence[RoleT], target: Callable[[RoleT], Target]) -> TargetMatch:
    """Find *entry*'s targets among *roles*; *target* gives a role's target."""
    index: dict[Target, int] = {}
    for i, role in enumerate(roles):
        index.setdefault(_norm(target(role)), i)
    ready: list[int] = []
    active: list[str] = []
    missing: list[str] = []
    for n, wanted in enumerate(entry.targets):
        found = index.get(_norm(wanted))
        if found is None:
            missing.append(entry.label(n))
        elif roles[found].is_active:
            active.append(entry.label(n))
        elif found not in ready:
            ready.append(found)
    return TargetMatch(tuple(ready), tuple(active), tuple(missing))
