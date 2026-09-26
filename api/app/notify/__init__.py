"""Email notifications over plain SMTP (SPEC.md §10, CLAUDE.md rule 12).

Public surface::

    from app.notify import Mailer, SmtpMailer, InMemoryMailer, build_mailer
    from app.notify import send_signing_link, send_signed_copies

The mailer moves finished messages; the service builds them, retries, and
writes ``notification.sent`` / ``notification.failed`` events. Neither ever
raises into the request that triggered them.
"""

from app.notify.mailer import InMemoryMailer, Mailer, SmtpMailer, build_mailer
from app.notify.service import (
    RETRY_BACKOFF_SECONDS,
    Notification,
    send_signed_copies,
    send_signing_link,
    signed_copy_for,
)
from app.notify.templates import DeliveryMode, Recipient, SignedCopy, admin_contract_url

__all__ = [
    "RETRY_BACKOFF_SECONDS",
    "DeliveryMode",
    "InMemoryMailer",
    "Mailer",
    "Notification",
    "Recipient",
    "SignedCopy",
    "SmtpMailer",
    "admin_contract_url",
    "build_mailer",
    "send_signed_copies",
    "send_signing_link",
    "signed_copy_for",
]
