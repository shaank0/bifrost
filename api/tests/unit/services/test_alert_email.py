"""Alert email content and SMTP delivery."""

import smtplib

import pytest

from src.services import alert_email
from src.services.alert_email import AlertMessage, SmtpSendError, SmtpSettings

SETTINGS = SmtpSettings(
    host="smtp.example.com",
    port=587,
    security="starttls",
    username="alerts@example.com",
    password="app-password",
    from_address="alerts@example.com",
    recipients=["ops@example.com", "will@example.com"],
)
ALERT = AlertMessage(
    title="receipts_scan_mailbox failed",
    detail="QboError: QuickBooks GET /query failed (401)",
    organization_name="Acme",
    occurrences=3,
    first_seen="2026-10-28 08:00 UTC",
    last_seen="2026-10-28 08:30 UTC",
    link="https://bifrost.example.com/alerts",
)


def test_alert_email_names_the_failure_its_organization_and_where_to_look():
    message = alert_email.alert_email(ALERT, SETTINGS)
    assert message["Subject"] == "[Bifrost alert] receipts_scan_mailbox failed (Acme)"
    assert message["To"] == "ops@example.com, will@example.com"
    assert message["Auto-Submitted"] == "auto-generated"
    body = message.get_content()
    assert "QuickBooks GET /query failed (401)" in body
    assert "Occurrences: 3" in body
    assert "https://bifrost.example.com/alerts" in body


class FakeSmtp:
    sent: list = []
    instances: list = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.calls = host, port, []
        FakeSmtp.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, username, password):
        if password != "app-password":
            raise smtplib.SMTPAuthenticationError(535, b"5.7.3 Authentication unsuccessful")
        self.calls.append("login")

    def send_message(self, message):
        FakeSmtp.sent.append(message)


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch):
    FakeSmtp.sent, FakeSmtp.instances = [], []
    monkeypatch.setattr(alert_email.smtplib, "SMTP", FakeSmtp)
    monkeypatch.setattr(alert_email.smtplib, "SMTP_SSL", FakeSmtp)


def test_send_upgrades_to_tls_signs_in_and_sends():
    alert_email.send(SETTINGS, alert_email.sample_email(SETTINGS))
    assert FakeSmtp.instances[0].calls == ["starttls", "login"]
    assert FakeSmtp.sent[0]["Subject"] == "[Bifrost alert] Test email"


def test_a_relay_without_credentials_skips_sign_in():
    relay = SmtpSettings(**{**SETTINGS.__dict__, "username": None, "password": None, "security": "none", "port": 25})
    alert_email.send(relay, alert_email.sample_email(relay))
    assert FakeSmtp.instances[0].calls == []


def test_a_wrong_password_is_reported_without_the_password():
    wrong = SmtpSettings(**{**SETTINGS.__dict__, "password": "nope"})
    with pytest.raises(SmtpSendError, match="refused the username or password") as raised:
        alert_email.send(wrong, alert_email.sample_email(wrong))
    assert "nope" not in str(raised.value)


def test_no_recipients_is_refused():
    nobody = SmtpSettings(**{**SETTINGS.__dict__, "recipients": []})
    with pytest.raises(SmtpSendError, match="No alert email recipients"):
        alert_email.send(nobody, alert_email.sample_email(nobody))
