"""``SmtpMailer`` against an in-process aiosmtpd server on the loopback interface.

This is the one place the real ``smtplib`` path runs. The server lives in the
test process, binds 127.0.0.1 on a free port, and is torn down with the test;
no network mail server is ever contacted.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any

import pytest
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import SMTP, AuthResult, Envelope, LoginPassword, Session

from app.config import Settings
from app.notify import InMemoryMailer, SmtpMailer, build_mailer


@dataclass
class Received:
    """Every envelope the fake server accepted."""

    envelopes: list[Envelope] = field(default_factory=list)

    async def handle_DATA(self, server: SMTP, session: Session, envelope: Envelope) -> str:  # noqa: N802
        self.envelopes.append(envelope)
        return "250 Message accepted for delivery"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


def _authenticator(
    server: SMTP, session: Session, envelope: Envelope, mechanism: str, auth_data: Any
) -> AuthResult:
    ok = (
        isinstance(auth_data, LoginPassword)
        and auth_data.login == b"mailer"
        and auth_data.password == b"mailer-secret"
    )
    return AuthResult(success=ok, handled=ok)


@pytest.fixture
def smtp_server() -> Iterator[tuple[Received, int]]:
    received = Received()
    port = _free_port()
    controller = Controller(received, hostname="127.0.0.1", port=port)
    controller.start()
    try:
        yield received, port
    finally:
        controller.stop()


@pytest.fixture
def auth_smtp_server() -> Iterator[tuple[Received, int]]:
    received = Received()
    port = _free_port()
    controller = Controller(
        received,
        hostname="127.0.0.1",
        port=port,
        authenticator=_authenticator,
        auth_required=True,
        auth_require_tls=False,
    )
    controller.start()
    try:
        yield received, port
    finally:
        controller.stop()


def _message() -> EmailMessage:
    message = EmailMessage()
    message["From"] = "Foodverse Contracts <contracts@foodverse.example>"
    message["To"] = "Maria Petrova <maria@hotel-aurora.example>"
    message["Subject"] = "Hello"
    message["Message-ID"] = "<test-1@foodverse.example>"
    message.set_content("Plain body with a link: http://localhost:5173/sign/abc")
    message.add_attachment(b"%PDF-1.4 x", maintype="application", subtype="pdf", filename="a.pdf")
    return message


async def test_smtp_mailer_delivers_headers_body_and_attachment(
    smtp_server: tuple[Received, int],
) -> None:
    received, port = smtp_server
    mailer = SmtpMailer(
        host="127.0.0.1", port=port, username="", password="", use_tls=False, timeout_seconds=5
    )
    await mailer.send(_message())
    (envelope,) = received.envelopes
    assert envelope.mail_from == "contracts@foodverse.example"
    assert envelope.rcpt_tos == ["maria@hotel-aurora.example"]
    raw = envelope.content
    assert isinstance(raw, bytes)
    assert b"Subject: Hello" in raw
    assert b"Message-ID: <test-1@foodverse.example>" in raw
    assert b"http://localhost:5173/sign/abc" in raw
    assert b'Content-Disposition: attachment; filename="a.pdf"' in raw


@pytest.mark.filterwarnings("ignore:Requiring AUTH while not requiring TLS:UserWarning")
async def test_smtp_mailer_authenticates_when_credentials_are_set(
    auth_smtp_server: tuple[Received, int],
) -> None:
    received, port = auth_smtp_server
    anonymous = SmtpMailer(
        host="127.0.0.1", port=port, username="", password="", use_tls=False, timeout_seconds=5
    )
    with pytest.raises(Exception, match="530"):  # smtplib raises the response code
        await anonymous.send(_message())
    assert received.envelopes == []

    wrong = SmtpMailer(
        host="127.0.0.1",
        port=port,
        username="mailer",
        password="not-the-password",
        use_tls=False,
        timeout_seconds=5,
    )
    with pytest.raises(Exception, match="535"):
        await wrong.send(_message())

    right = SmtpMailer(
        host="127.0.0.1",
        port=port,
        username="mailer",
        password="mailer-secret",
        use_tls=False,
        timeout_seconds=5,
    )
    await right.send(_message())
    assert len(received.envelopes) == 1


async def test_smtp_mailer_raises_when_the_server_is_down() -> None:
    port = _free_port()  # nothing listens here
    mailer = SmtpMailer(
        host="127.0.0.1", port=port, username="", password="", use_tls=False, timeout_seconds=2
    )
    with pytest.raises(OSError):
        await mailer.send(_message())


def test_build_mailer_reads_smtp_settings() -> None:
    settings = Settings(
        smtp_host="mail.example",
        smtp_port=2525,
        smtp_username="u",
        smtp_password="p",
        smtp_use_tls=True,
        smtp_timeout_seconds=3,
    )
    mailer = build_mailer(settings)
    assert isinstance(mailer, SmtpMailer)
    assert (mailer._host, mailer._port, mailer._use_tls, mailer._timeout) == (
        "mail.example",
        2525,
        True,
        3,
    )
    assert mailer._username == "u"


async def test_in_memory_mailer_records_and_fails_on_demand() -> None:
    mailer = InMemoryMailer()
    mailer.failures = [OSError("boom")]
    with pytest.raises(OSError):
        await mailer.send(_message())
    await mailer.send(_message())
    assert len(mailer.outbox) == 1
