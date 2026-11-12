"""Human-readable end times for eligible roles, activations and assignments.

Azure and Microsoft Graph return end times as ISO 8601 strings in UTC.  These
helpers turn them into "47m left", "14:32 (47m left)" or "2026-12-31".  They
never read the clock themselves: every function that needs the current time
takes *now*, an aware datetime whose time zone is the one to show times in.
Screens pass :func:`now`.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime, timedelta

# Azure returns up to seven fractional digits (.NET ticks); datetime takes six.
_EXTRA_FRACTION_RE = re.compile(r"(\.\d{6})\d+")

#: An end time closer than this shows as a local time plus the time left,
#: anything further away as a date.
NEAR = timedelta(days=7)


def now() -> datetime:
    """The current time in the local time zone."""
    return datetime.now().astimezone()


def parse_iso(iso: str | None) -> datetime | None:
    """Parse an ISO 8601 date-time; ``None`` if *iso* is empty or malformed.

    A time without a time zone is taken to be UTC, as Azure means it.
    """
    if not iso:
        return None
    try:
        parsed = datetime.fromisoformat(_EXTRA_FRACTION_RE.sub(r"\1", iso.strip()))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def format_remaining(iso: str | None, now: datetime) -> str:
    """Time left until *iso*: "47m left", "3h 05m left", "2d 03h left" or "expired".

    No end time (``None``) is "permanent"; a malformed one gives "".  Minutes
    are rounded up, so the last minute shows as "1m left", not "0m left".
    """
    if not iso:
        return "permanent"
    end = parse_iso(iso)
    if end is None:
        return ""
    seconds = (end - now).total_seconds()
    if seconds <= 0:
        return "expired"
    minutes = math.ceil(seconds / 60)
    if minutes < 60:
        return f"{minutes}m left"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes:02d}m left"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours:02d}h left"


def format_date(iso: str) -> str:
    """The date part of *iso*, e.g. "2026-12-31" (as Azure gives it, in UTC)."""
    return iso[:10]


def format_end(iso: str | None, now: datetime) -> str:
    """When something ends: "14:32 (47m left)", "Fri 09:30 (2d 03h left)" or a date.

    An end time less than :data:`NEAR` away shows as a time in *now*'s time
    zone, with the weekday when it is not today, plus the time left.  A later
    one shows as its date, a past one as "2026-11-12 (expired)", and no end
    time as "Permanent".
    """
    if not iso:
        return "Permanent"
    end = parse_iso(iso)
    if end is None:
        return format_date(iso)
    if end <= now:
        return f"{format_date(iso)} (expired)"
    if end - now >= NEAR:
        return format_date(iso)
    local = end.astimezone(now.tzinfo)
    clock = local.strftime("%H:%M") if local.date() == now.date() else local.strftime("%a %H:%M")
    return f"{clock} ({format_remaining(iso, now)})"


def end_sort_key(iso: str | None) -> tuple[int, float, str]:
    """Sort key for end times: soonest first, malformed ones next, permanent last."""
    if not iso:
        return (2, 0.0, "")
    end = parse_iso(iso)
    if end is None:
        return (1, 0.0, iso)
    return (0, end.timestamp(), "")
