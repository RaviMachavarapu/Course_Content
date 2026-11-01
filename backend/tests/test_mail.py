"""SMTP settings are honoured: EMAIL_FROM, credentials and TLS in SMTP_URL."""

from __future__ import annotations

from email.message import EmailMessage
from typing import Any, ClassVar

import pytest

from app.config import Settings
from app.services import mail


class FakeSMTP:
    instances: ClassVar[list[FakeSMTP]] = []

    def __init__(self, host: str, port: int, timeout: float, **kw: Any) -> None:
        self.host, self.port, self.kw = host, port, kw
        self.calls: list[tuple[str, Any]] = []
        self.sent: list[EmailMessage] = []
        FakeSMTP.instances.append(self)

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def starttls(self, **kw: Any) -> None:
        self.calls.append(("starttls", kw))

    def login(self, user: str, password: str) -> None:
        self.calls.append(("login", (user, password)))

    def send_message(self, msg: EmailMessage) -> None:
        self.sent.append(msg)


class FakeSSL(FakeSMTP):
    pass


@pytest.fixture(autouse=True)
def _fake(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSMTP.instances = []
    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", FakeSSL)


def _send(url: str, **extra: Any) -> FakeSMTP:
    mail.send_mail(Settings(smtp_url=url, **extra), to="a@example.com", subject="s", body="b")
    return FakeSMTP.instances[-1]


def test_plain_dev_relay_uses_email_from() -> None:
    smtp = _send("smtp://mailhog:1025", email_from="noreply@school.example")
    assert (smtp.host, smtp.port) == ("mailhog", 1025)
    assert smtp.calls == []
    assert smtp.sent[0]["From"] == "noreply@school.example"


def test_starttls_with_credentials() -> None:
    smtp = _send("smtp://user%40x.com:p%40ss@relay.example:587?starttls=true")
    assert type(smtp) is FakeSMTP
    assert [c[0] for c in smtp.calls] == ["starttls", "login"]
    assert smtp.calls[1][1] == ("user@x.com", "p@ss")


def test_smtps_is_implicit_tls_on_465() -> None:
    smtp = _send("smtps://u:pw@relay.example")
    assert type(smtp) is FakeSSL
    assert smtp.port == 465
    assert [c[0] for c in smtp.calls] == ["login"]


def test_unknown_scheme_is_rejected() -> None:
    with pytest.raises(ValueError, match="SMTP_URL"):
        _send("http://relay.example")
