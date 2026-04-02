"""Shared SMTP send (plain text, optional multipart). Used by email_proposal and render_outbound_email."""

from __future__ import annotations

import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")


def smtp_settings() -> tuple[str, int, str, str, str]:
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    from_addr = os.getenv("PROPOSAL_FROM_EMAIL", user).strip()
    return host, port, user, password, from_addr


def send_plain_email(
    *,
    recipients: list[str],
    subject: str,
    body: str,
    dry_run: bool = False,
) -> None:
    host, port, user, password, from_addr = smtp_settings()
    if not host or not from_addr:
        raise SystemExit("Set SMTP_HOST and PROPOSAL_FROM_EMAIL (or SMTP_USER) in .env")

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(body, "plain", "utf-8"))

    if dry_run:
        print("Dry run — not sending.")
        print(msg.as_string()[:4000])
        return

    if not password:
        raise SystemExit("SMTP_PASSWORD missing in .env")

    context = ssl.create_default_context()
    with smtplib.SMTP(host, port) as server:
        server.starttls(context=context)
        server.login(user, password)
        server.sendmail(from_addr, recipients, msg.as_string())
