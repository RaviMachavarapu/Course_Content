"""Minimal SMTP sending (O6: password reset). Dev/CI point `SMTP_URL` at
mailhog; a real deployment points it at a real relay — no other code changes.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from urllib.parse import urlparse

from app.config import Settings
from app.logging import get_logger

log = get_logger("mail")

_FROM_ADDRESS = "no-reply@shikshak-dp.local"


def send_mail(settings: Settings, *, to: str, subject: str, body: str) -> None:
    parsed = urlparse(settings.smtp_url)
    msg = EmailMessage()
    msg["From"] = _FROM_ADDRESS
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(parsed.hostname or "localhost", parsed.port or 1025, timeout=10) as smtp:
        smtp.send_message(msg)
    log.info("mail.sent", to=to, subject=subject)
