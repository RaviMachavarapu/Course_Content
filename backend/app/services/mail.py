"""Minimal SMTP sending (O6: password reset). Dev/CI point `SMTP_URL` at
mailhog; a real deployment points it at a real relay — no other code changes.

`SMTP_URL` forms:

- ``smtp://host:port`` — plain (dev mailhog);
- ``smtp://user:pass@host:587?starttls=true`` — STARTTLS, then login;
- ``smtps://user:pass@host`` — implicit TLS (default port 465), then login.

User and password are URL-decoded (``%40`` for ``@``). The sender is
`EMAIL_FROM`.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import parse_qs, unquote, urlparse

from app.config import Settings
from app.logging import get_logger

log = get_logger("mail")

_TIMEOUT_SEC = 10
_TRUE = {"1", "true", "yes", "on"}


def _deliver(settings: Settings, msg: EmailMessage) -> None:
    parsed = urlparse(settings.smtp_url)
    scheme = parsed.scheme.lower()
    if scheme not in {"smtp", "smtps"}:
        raise ValueError(f"SMTP_URL must start with smtp:// or smtps:// (got {scheme!r})")
    host = parsed.hostname or "localhost"
    query = parse_qs(parsed.query)
    starttls = query.get("starttls", ["false"])[0].lower() in _TRUE

    smtp: smtplib.SMTP
    if scheme == "smtps":
        smtp = smtplib.SMTP_SSL(
            host, parsed.port or 465, timeout=_TIMEOUT_SEC, context=ssl.create_default_context()
        )
    else:
        smtp = smtplib.SMTP(host, parsed.port or 1025, timeout=_TIMEOUT_SEC)
    with smtp:
        if starttls and scheme == "smtp":
            smtp.starttls(context=ssl.create_default_context())
        if parsed.username:
            smtp.login(unquote(parsed.username), unquote(parsed.password or ""))
        smtp.send_message(msg)


def send_mail(settings: Settings, *, to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    _deliver(settings, msg)
    log.info("mail.sent", to=to, subject=subject)
