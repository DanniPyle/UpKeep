import os
import smtplib
from email.message import EmailMessage
from typing import Optional

SMTP_HOST = os.getenv("SMTP_HOST", "smtp-relay.brevo.com")  # Brevo default
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")  # Brevo login (usually your Brevo account email or API key)
SMTP_PASS = os.getenv("SMTP_PASS")  # Brevo SMTP key
FROM_EMAIL = os.getenv("FROM_EMAIL", "no-reply@example.com")
FROM_NAME = os.getenv("FROM_NAME", "Home Maintenance Tracker")


def send_email(to_email: str, subject: str, html: str, text: Optional[str] = None) -> None:
    """
    Send a transactional email using SMTP (Brevo-compatible).
    Required env vars:
      - SMTP_HOST (default smtp-relay.brevo.com)
      - SMTP_PORT (default 587)
      - SMTP_USER
      - SMTP_PASS
      - FROM_EMAIL
      - FROM_NAME (optional)
    """
    if not (SMTP_USER and SMTP_PASS and FROM_EMAIL):
        raise RuntimeError("SMTP configuration missing (SMTP_USER/SMTP_PASS/FROM_EMAIL)")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>" if FROM_NAME else FROM_EMAIL
    msg["To"] = to_email

    if text:
        msg.set_content(text)
    else:
        # Fallback text content stripped from HTML tags (minimal)
        msg.set_content("This email requires an HTML-capable client.")

    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        # Use STARTTLS when on 587
        if SMTP_PORT in (587, 25, 2525):
            server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
