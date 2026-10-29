"""Alert email: the message for an alert, and sending it through the platform's SMTP server.

The SMTP server is the platform's own (Settings → Alerts), not any organization's
integration, so an alert can still go out when the broken thing is a client's
Microsoft 365 or Google connection.
"""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Literal

SmtpSecurity = Literal["starttls", "ssl", "none"]
SMTP_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    security: SmtpSecurity
    username: str | None
    password: str | None
    from_address: str
    recipients: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AlertMessage:
    title: str
    detail: str
    organization_name: str | None
    occurrences: int
    first_seen: str
    last_seen: str
    link: str | None


class SmtpSendError(RuntimeError):
    """Sending failed; the message is safe to show an administrator (it never contains the password)."""


def alert_email(alert: AlertMessage, settings: SmtpSettings) -> EmailMessage:
    message = EmailMessage()
    where = f" ({alert.organization_name})" if alert.organization_name else ""
    message["Subject"] = f"[Bifrost alert] {alert.title}{where}"
    message["From"] = settings.from_address
    message["To"] = ", ".join(settings.recipients)
    message["Message-ID"] = make_msgid(domain=settings.from_address.rpartition("@")[2] or None)
    # Ask mail servers not to send vacation replies back to the platform address.
    message["Auto-Submitted"] = "auto-generated"
    lines = [
        alert.title + where,
        "",
        alert.detail,
        "",
        f"First seen: {alert.first_seen}",
        f"Last seen: {alert.last_seen}",
    ]
    if alert.occurrences > 1:
        lines.append(f"Occurrences: {alert.occurrences}")
    if alert.link:
        lines += ["", f"Open in Bifrost: {alert.link}"]
    lines += ["", "You get this because your address is on the Bifrost alert email list (Settings → Alerts)."]
    message.set_content("\n".join(lines))
    return message


def sample_email(settings: SmtpSettings) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = "[Bifrost alert] Test email"
    message["From"] = settings.from_address
    message["To"] = ", ".join(settings.recipients)
    message["Auto-Submitted"] = "auto-generated"
    message.set_content("Bifrost can send alert emails with these SMTP settings.")
    return message


def send(settings: SmtpSettings, message: EmailMessage) -> None:
    """Deliver ``message`` to the recipients in its To header. Blocking: call it from a worker thread."""
    if not settings.recipients:
        raise SmtpSendError("No alert email recipients are set")
    try:
        if settings.security == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                settings.host, settings.port, timeout=SMTP_TIMEOUT_SECONDS, context=ssl.create_default_context()
            )
        else:
            client = smtplib.SMTP(settings.host, settings.port, timeout=SMTP_TIMEOUT_SECONDS)
        with client:
            if settings.security == "starttls":
                client.starttls(context=ssl.create_default_context())
            if settings.username:
                client.login(settings.username, settings.password or "")
            client.send_message(message)
    except smtplib.SMTPAuthenticationError as e:
        raise SmtpSendError(f"The SMTP server refused the username or password ({e.smtp_code})") from None
    except smtplib.SMTPRecipientsRefused as e:
        raise SmtpSendError(f"The SMTP server refused the recipients: {', '.join(e.recipients)}") from None
    except smtplib.SMTPException as e:
        raise SmtpSendError(f"SMTP error: {e}") from None
    except (OSError, ssl.SSLError) as e:
        raise SmtpSendError(f"Couldn't reach {settings.host}:{settings.port}: {e}") from None
