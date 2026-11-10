"""Transactional email providers behind one interface. Secrets come from the environment only."""

from __future__ import annotations

import logging
import smtplib
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol

import httpx

from app.config import get_settings

log = logging.getLogger("academy.email")


@dataclass
class OutgoingEmail:
    to: str
    subject: str
    html: str
    text: str
    idempotency_key: str
    headers: dict[str, str]


class EmailProvider(Protocol):
    name: str

    def send(self, msg: OutgoingEmail) -> str:
        """Send and return a provider message id. Raise on failure (the job retries)."""


def _mime(msg: OutgoingEmail) -> EmailMessage:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = get_settings().email_from, msg.to, msg.subject
    for k, v in msg.headers.items():
        m[k] = v
    m.set_content(msg.text)
    m.add_alternative(msg.html, subtype="html")
    return m


class ConsoleProvider:
    """Development: writes .eml files to OUTBOX_DIR and logs the subject."""

    name = "console"
    sent: list[OutgoingEmail] = []

    def send(self, msg: OutgoingEmail) -> str:
        out = Path(get_settings().outbox_dir)
        out.mkdir(parents=True, exist_ok=True)
        mid = f"console-{uuid.uuid4().hex[:12]}"
        (out / f"{mid}.eml").write_bytes(bytes(_mime(msg)))
        ConsoleProvider.sent.append(msg)
        log.info("email to %s: %s (%s)", msg.to, msg.subject, mid)
        return mid


class SMTPProvider:
    """SMTP (Mailpit in docker-compose for local dev, or any relay)."""

    name = "smtp"

    def send(self, msg: OutgoingEmail) -> str:
        s = get_settings()
        m = _mime(msg)
        m["Message-ID"] = f"<{msg.idempotency_key.replace(':', '.')}@ai-academy>"
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
            smtp.send_message(m)
        return m["Message-ID"]


class ResendProvider:
    name = "resend"
    URL = "https://api.resend.com/emails"

    def send(self, msg: OutgoingEmail) -> str:
        s = get_settings()
        if not s.resend_api_key:
            raise RuntimeError("RESEND_API_KEY is not set")
        resp = httpx.post(
            self.URL,
            headers={"Authorization": f"Bearer {s.resend_api_key}", "Idempotency-Key": msg.idempotency_key[:256]},
            json={"from": s.email_from, "to": [msg.to], "subject": msg.subject, "html": msg.html, "text": msg.text, "headers": msg.headers},
            timeout=15,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Resend error {resp.status_code}: {resp.text[:300]}")
        return resp.json().get("id", "")


def get_email_provider() -> EmailProvider:
    return {"console": ConsoleProvider, "smtp": SMTPProvider, "resend": ResendProvider}[get_settings().email_provider]()
