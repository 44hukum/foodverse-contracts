from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.pdf.timefmt import format_both, format_display, format_utc, require_aware

SIGNED_AT = datetime(2026, 9, 28, 14, 22, 10, tzinfo=UTC)


def test_kathmandu_line_matches_spec_example() -> None:
    assert format_display(SIGNED_AT) == "2026-09-28 20:07:10 NPT (Asia/Kathmandu, UTC+05:45)"


def test_utc_line_matches_spec_example() -> None:
    assert format_utc(SIGNED_AT) == "2026-09-28 14:22:10 UTC"


def test_both_returns_display_then_utc() -> None:
    assert format_both(SIGNED_AT) == (
        "2026-09-28 20:07:10 NPT (Asia/Kathmandu, UTC+05:45)",
        "2026-09-28 14:22:10 UTC",
    )


def test_non_utc_input_is_converted_not_relabelled() -> None:
    plus_two = SIGNED_AT.astimezone(timezone(timedelta(hours=2)))
    assert format_both(plus_two) == format_both(SIGNED_AT)


def test_other_zone_uses_iana_abbreviation_and_negative_offset() -> None:
    line = format_display(SIGNED_AT, "America/New_York")
    assert line == "2026-09-28 10:22:10 EDT (America/New_York, UTC-04:00)"


def test_utc_zone_offset_is_zero() -> None:
    assert format_display(SIGNED_AT, "UTC").endswith("(UTC, UTC+00:00)")


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        require_aware(datetime(2026, 9, 28, 14, 22, 10), "signed_at")
    with pytest.raises(ValueError, match="timezone-aware"):
        format_utc(datetime(2026, 9, 28))
