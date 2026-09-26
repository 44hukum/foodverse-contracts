"""Human-facing timestamp rendering (SPEC.md §8, CLAUDE.md rule 14).

Storage and the API stay UTC. Only rendering edges (this PDF module, emails,
the admin UI) convert to ``DISPLAY_TIMEZONE`` and always print UTC alongside.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

DEFAULT_DISPLAY_TIMEZONE = "Asia/Kathmandu"

# IANA ships numeric abbreviations ("+0545") for zones without a conventional
# one. The spec wants the conventional label where one exists.
_ABBREVIATIONS: dict[str, str] = {"Asia/Kathmandu": "NPT"}

_FORMAT = "%Y-%m-%d %H:%M:%S"


def require_aware(value: datetime, name: str) -> datetime:
    """Return ``value`` if it is timezone-aware, otherwise raise ``ValueError``."""
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        msg = f"{name} must be a timezone-aware datetime"
        raise ValueError(msg)
    return value


def format_utc(value: datetime) -> str:
    """``2026-09-28 14:22:10 UTC``."""
    return require_aware(value, "value").astimezone(UTC).strftime(_FORMAT) + " UTC"


def format_display(value: datetime, tz_name: str = DEFAULT_DISPLAY_TIMEZONE) -> str:
    """``2026-09-28 20:07:10 NPT (Asia/Kathmandu, UTC+05:45)``."""
    zone = ZoneInfo(tz_name)
    local = require_aware(value, "value").astimezone(zone)
    offset = local.utcoffset()
    assert offset is not None  # an aware datetime always has an offset
    total_minutes = int(offset.total_seconds()) // 60
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    label = _ABBREVIATIONS.get(tz_name) or local.tzname() or tz_name
    return f"{local.strftime(_FORMAT)} {label} ({tz_name}, UTC{sign}{hours:02d}:{minutes:02d})"


def format_both(value: datetime, tz_name: str = DEFAULT_DISPLAY_TIMEZONE) -> tuple[str, str]:
    """The display-zone line and the UTC line, in that order."""
    return format_display(value, tz_name), format_utc(value)
