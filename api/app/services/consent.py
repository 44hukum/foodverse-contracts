"""Consent wording shown to the signer (SPEC.md §8).

The text is versioned (CLAUDE.md rule 15): ``CONSENT_TEXT_VERSION`` selects
the template, the served version string is stored on the signer at signing
and printed on the certificate page, so a later change of wording stays
distinguishable in the audit trail. Adding a version means adding a template
here and pointing the config at it; old versions are never edited.
"""

from __future__ import annotations

from app.config import Settings

_TEMPLATES: dict[str, str] = {
    "v0-draft": (
        "I confirm that I am {signer_name}, that I have read the document titled "
        '"{title}", and that I agree to sign it electronically. I understand that my '
        "typed name, drawn signature, IP address, and the time of signing will be "
        "recorded and attached to the document as evidence of my agreement. "
        "[v0-draft — pending legal review]"
    ),
}


class UnknownConsentVersionError(RuntimeError):
    """``CONSENT_TEXT_VERSION`` names a wording this build does not carry."""


def consent_template(version: str) -> str:
    try:
        return _TEMPLATES[version]
    except KeyError as exc:
        raise UnknownConsentVersionError(
            f"CONSENT_TEXT_VERSION={version!r} has no wording; known: {sorted(_TEMPLATES)}"
        ) from exc


def render_consent_text(settings: Settings, *, signer_name: str, title: str) -> str:
    """The exact wording the UI must show next to the checkbox."""
    return consent_template(settings.consent_text_version).format(
        signer_name=signer_name, title=title
    )
