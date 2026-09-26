"""The three emails the system sends, as plain-text ``EmailMessage`` objects (SPEC.md §10).

Rendering edge for timestamps (CLAUDE.md rule 14): every time is printed in
``DISPLAY_TIMEZONE`` with UTC alongside. Bodies are plain text so nothing
here needs escaping and every mail client renders the link and the hash
verbatim.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from datetime import datetime
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid, parseaddr

from app.config import Settings
from app.pdf.timefmt import format_both


class Recipient(enum.StrEnum):
    signer = "signer"
    admin = "admin"


class DeliveryMode(enum.StrEnum):
    link = "link"
    attachment = "attachment"


@dataclass(frozen=True, slots=True)
class SignedCopy:
    """What a completion email carries: the PDF itself, or a pre-signed link to it."""

    filename: str
    sha256: str
    size: int
    pdf_bytes: bytes | None = None
    download_url: str | None = None
    download_expires_at: datetime | None = None

    @property
    def mode(self) -> DeliveryMode:
        return DeliveryMode.attachment if self.pdf_bytes is not None else DeliveryMode.link


def _message(settings: Settings, *, to_name: str, to_email: str, subject: str) -> EmailMessage:
    message = EmailMessage()
    from_name, from_addr = parseaddr(settings.email_from)
    message["From"] = Address(from_name, addr_spec=from_addr) if from_addr else settings.email_from
    message["To"] = Address(to_name, addr_spec=to_email)
    message["Subject"] = subject
    message["Date"] = format_datetime(datetime.now().astimezone())
    domain = from_addr.rsplit("@", 1)[-1] if "@" in from_addr else None
    message["Message-ID"] = make_msgid(domain=domain)
    return message


def _both_lines(settings: Settings, value: datetime, indent: str = "  ") -> str:
    display, utc = format_both(value, settings.display_timezone)
    return f"{indent}{display}\n{indent}{utc}"


def _human_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size} bytes"


def signing_link_email(
    settings: Settings,
    *,
    signer_name: str,
    signer_email: str,
    title: str,
    signing_url: str,
    expires_at: datetime,
    sender_name: str | None,
    note: str | None,
) -> EmailMessage:
    """To the signer: title, sender organisation, expiry, the link, optional note."""
    org = settings.org_display_name
    lines = [
        f"Hello {signer_name},",
        "",
        f'{org} has sent you a document to review and sign: "{title}".',
        "",
        "Open this link to read the document and sign it electronically:",
        f"  {signing_url}",
        "",
        "The link expires on:",
        _both_lines(settings, expires_at),
        "",
        "The link is personal to you. Do not forward it; anyone holding it can sign",
        "the document in your name. If it has expired, ask the sender for a new one.",
    ]
    if note:
        who = f"Message from {sender_name}" if sender_name else "Message from the sender"
        lines += ["", f"{who}:", *(f"  {line}" for line in note.strip().splitlines())]
    lines += ["", "If you were not expecting this email, you can ignore it.", "", f"— {org}"]
    message = _message(
        settings,
        to_name=signer_name,
        to_email=signer_email,
        subject=f'{org}: "{title}" is ready for your signature',
    )
    message.set_content("\n".join(lines))
    return message


def _completion_lines(settings: Settings, *, copy: SignedCopy, signed_at: datetime) -> list[str]:
    lines = [
        "Signed at:",
        _both_lines(settings, signed_at),
        "",
        "SHA-256 of the signed PDF:",
        f"  {copy.sha256}",
        "",
    ]
    if copy.mode is DeliveryMode.attachment:
        lines += [f"The signed PDF is attached ({copy.filename}, {_human_size(copy.size)})."]
    else:
        assert copy.download_url is not None and copy.download_expires_at is not None
        lines += [
            f"The signed PDF ({_human_size(copy.size)}) is too large to attach. Download it here:",
            f"  {copy.download_url}",
            "",
            "The download link is valid until:",
            _both_lines(settings, copy.download_expires_at),
        ]
    lines += [
        "",
        "Anyone holding a copy of the PDF can check it is unaltered by computing its",
        "SHA-256 and comparing it with the value above.",
    ]
    return lines


def _attach(message: EmailMessage, copy: SignedCopy) -> None:
    if copy.pdf_bytes is not None:
        message.add_attachment(
            copy.pdf_bytes, maintype="application", subtype="pdf", filename=copy.filename
        )


def signed_copy_email_to_signer(
    settings: Settings,
    *,
    signer_name: str,
    signer_email: str,
    title: str,
    signed_at: datetime,
    copy: SignedCopy,
) -> EmailMessage:
    """Confirmation to the signer with the signed PDF (or a link) and its hash."""
    org = settings.org_display_name
    lines = [
        f"Hello {signer_name},",
        "",
        f'Thank you. Your electronic signature on "{title}" has been recorded.',
        "",
        *_completion_lines(settings, copy=copy, signed_at=signed_at),
        "",
        "Please keep this email as your copy of the signed document.",
        "",
        f"— {org}",
    ]
    message = _message(
        settings, to_name=signer_name, to_email=signer_email, subject=f'Signed: "{title}"'
    )
    message.set_content("\n".join(lines))
    _attach(message, copy)
    return message


def admin_contract_url(settings: Settings, contract_id: uuid.UUID) -> str:
    return f"{settings.web_base_url.rstrip('/')}/contracts/{contract_id}"


def signed_copy_email_to_admin(
    settings: Settings,
    *,
    admin_name: str,
    admin_email: str,
    signer_name: str,
    title: str,
    contract_id: uuid.UUID,
    signed_at: datetime,
    copy: SignedCopy,
) -> EmailMessage:
    """Same as the signer's copy, plus a link to the admin contract page."""
    lines = [
        f"Hello {admin_name},",
        "",
        f'{signer_name} has signed "{title}".',
        "",
        *_completion_lines(settings, copy=copy, signed_at=signed_at),
        "",
        "Contract page (login required):",
        f"  {admin_contract_url(settings, contract_id)}",
        "",
        "— Foodverse Contract Signing",
    ]
    message = _message(
        settings,
        to_name=admin_name,
        to_email=admin_email,
        subject=f'Signed by {signer_name}: "{title}"',
    )
    message.set_content("\n".join(lines))
    _attach(message, copy)
    return message
