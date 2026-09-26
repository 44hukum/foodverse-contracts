"""Notification tests share the in-memory mailer from the root conftest and skip retry pauses."""

from __future__ import annotations

import pytest

from app.notify import service


@pytest.fixture(autouse=True)
def no_retry_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "RETRY_BACKOFF_SECONDS", 0)
