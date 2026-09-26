"""Token, consent, and helper units behind the signing endpoints."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime

import pytest

from app.config import Settings
from app.errors import redact_path
from app.services import tokens
from app.services.consent import UnknownConsentVersionError, render_consent_text
from app.services.signing import retain_until_for


def test_token_is_43_char_base64url_of_32_random_bytes() -> None:
    seen = {tokens.generate_token() for _ in range(200)}
    assert len(seen) == 200
    for token in seen:
        assert len(token) == 43
        assert tokens.is_well_formed(token)
        assert "=" not in token


def test_only_the_sha256_of_a_token_is_ever_used() -> None:
    token = tokens.generate_token()
    assert tokens.hash_token(token) == hashlib.sha256(token.encode()).hexdigest()
    assert len(tokens.hash_token(token)) == 64
    assert tokens.hash_token(token) != tokens.hash_token(
        token[:-1] + ("A" if token[-1] != "A" else "B")
    )


@pytest.mark.parametrize(
    "bad",
    ["", "short", "a" * 42, "a" * 44, "a" * 42 + "=", "a" * 42 + "/", "a" * 42 + " ", "é" * 43],
)
def test_malformed_tokens_are_rejected_before_lookup(bad: str) -> None:
    assert not tokens.is_well_formed(bad)


def test_link_ttl_defaults_and_bounds(settings: Settings) -> None:
    assert tokens.link_ttl_days(settings, None) == settings.signing_link_ttl_days
    assert tokens.link_ttl_days(settings, 1) == 1
    assert tokens.link_ttl_days(settings, 30) == 30
    for out_of_range in (0, 31, -1):
        with pytest.raises(ValueError, match="between 1 and 30"):
            tokens.link_ttl_days(settings, out_of_range)
    now = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
    assert tokens.expiry_for(14, now) == datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def test_default_ttl_setting_must_be_a_legal_per_send_value() -> None:
    with pytest.raises(ValueError, match="SIGNING_LINK_TTL_DAYS"):
        Settings(signing_link_ttl_days=31)
    with pytest.raises(ValueError, match="SIGNING_LINK_TTL_DAYS"):
        Settings(signing_link_ttl_days=0)


def test_signing_url_is_web_base_url_sign_token(settings: Settings) -> None:
    token = tokens.generate_token()
    assert tokens.signing_url(settings, token) == f"{settings.web_base_url}/sign/{token}"
    with_slash = Settings(web_base_url="https://contracts.example/")
    assert tokens.signing_url(with_slash, token) == f"https://contracts.example/sign/{token}"


def test_consent_text_is_the_spec_wording_for_v0_draft(settings: Settings) -> None:
    text = render_consent_text(settings, signer_name="Maria Petrova", title="Hotel Aurora 2026")
    assert text.startswith(
        "I confirm that I am Maria Petrova, that I have read the document titled"
    )
    assert '"Hotel Aurora 2026"' in text
    assert text.endswith("[v0-draft — pending legal review]")


def test_unknown_consent_version_is_a_startup_error() -> None:
    bad = Settings(consent_text_version="v9-nope")
    with pytest.raises(UnknownConsentVersionError, match="v9-nope"):
        render_consent_text(bad, signer_name="x", title="y")


def test_retain_until_is_term_end_or_signing_date_plus_seven_years(settings: Settings) -> None:
    signed_at = datetime(2026, 9, 28, 14, 22, 10, tzinfo=UTC)
    assert retain_until_for(settings, None, signed_at) == date(2033, 9, 28)
    assert retain_until_for(settings, date(2028, 12, 31), signed_at) == date(2035, 12, 31)
    assert retain_until_for(settings, date(2028, 2, 29), signed_at) == date(2035, 2, 28)


def test_log_paths_never_carry_the_token() -> None:
    token = tokens.generate_token()
    assert token not in redact_path(f"/api/v1/public/sign/{token}")
    assert token not in redact_path(f"/api/v1/public/sign/{token}/signature")
    assert redact_path(f"/api/v1/public/sign/{token}/signature") == (
        "/api/v1/public/sign/[redacted]/signature"
    )
    assert redact_path("/api/v1/admin/contracts") == "/api/v1/admin/contracts"
