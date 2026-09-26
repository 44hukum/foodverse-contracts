"""The mailer interface and its two implementations (SPEC.md §10, CLAUDE.md rule 12).

``SmtpMailer`` talks plain SMTP through the standard library and is the only
outbound integration the service has. ``InMemoryMailer`` is the test double:
it keeps every message in an outbox and can be told to fail, so tests never
reach a network mail server.

A mailer only moves a finished ``EmailMessage``; it knows nothing about
contracts, tokens, or events. Nothing in this module logs a message body or
header, because the signing-link email carries the raw token (rule 6).
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol

from app.config import Settings


class Mailer(Protocol):
    async def send(self, message: EmailMessage) -> None:
        """Hand one message to the transport; raise on any failure."""
        ...


class SmtpMailer:
    """``smtplib`` behind the interface; STARTTLS when ``SMTP_USE_TLS`` is set."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        use_tls: bool,
        timeout_seconds: float,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._timeout = timeout_seconds

    async def send(self, message: EmailMessage) -> None:
        # smtplib is blocking; keep the event loop free while the handshake runs.
        await asyncio.to_thread(self._send_blocking, message)

    def _send_blocking(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as smtp:
            smtp.ehlo()
            if self._use_tls:
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            if self._username:
                smtp.login(self._username, self._password)
            smtp.send_message(message)


class InMemoryMailer:
    """Test double: records sent messages; ``failures`` are raised one per call, in order."""

    def __init__(self) -> None:
        self.outbox: list[EmailMessage] = []
        self.failures: list[Exception] = []

    async def send(self, message: EmailMessage) -> None:
        if self.failures:
            raise self.failures.pop(0)
        self.outbox.append(message)


def build_mailer(settings: Settings) -> Mailer:
    return SmtpMailer(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        use_tls=settings.smtp_use_tls,
        timeout_seconds=settings.smtp_timeout_seconds,
    )
