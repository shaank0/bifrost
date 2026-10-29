"""Failure alerts: recorded from built-in events, shown to platform admins, emailed when on."""

from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from src.models.orm.alerts import Alert
from src.models.orm.config import SystemConfig
from src.models.orm.platform_jobs import PlatformJob
from src.models.contracts.alerts import ALERT_EMAIL_CONFIG_CATEGORY
from src.services import platform_features
from src.services.alert_signals import AlertSignal
from src.services.alerts import apply_signal, record_from_event

pytestmark = pytest.mark.e2e


def _failure(subject: str, detail: str = "boom") -> AlertSignal:
    return AlertSignal(
        action="open", kind="workflow_failed", subject_key=subject, organization_id=None, title="nightly failed", detail=detail
    )


@pytest.fixture
async def alerts_feature(db_session):
    """Turn the Failure Alerts feature on (it is off by default) and back off afterwards."""
    await platform_features.set_features(db_session, {"alerts": True}, updated_by="test")
    await db_session.commit()
    yield
    await platform_features.set_features(db_session, {"alerts": False}, updated_by="test")
    await db_session.commit()


class _Context:
    async def report(self, *args, **kwargs):
        pass


@pytest.fixture
async def email_on(db_session):
    """Alert email turned on (at an unreachable server), replacing whatever settings a previous test saved."""
    await db_session.execute(delete(SystemConfig).where(SystemConfig.category == ALERT_EMAIL_CONFIG_CATEGORY))
    db_session.add(
        SystemConfig(
            category=ALERT_EMAIL_CONFIG_CATEGORY,
            key="smtp",
            value_json={
                "value": {
                    "enabled": True,
                    "host": "smtp.invalid",
                    "port": 587,
                    "security": "starttls",
                    "username": "",
                    "from_address": "alerts@example.com",
                    "recipients": ["ops@example.com"],
                }
            },
            organization_id=None,
            created_by="test",
            updated_by="test",
        )
    )
    await db_session.commit()
    yield
    await db_session.execute(delete(SystemConfig).where(SystemConfig.category == ALERT_EMAIL_CONFIG_CATEGORY))
    await db_session.commit()


async def test_repeat_failures_add_to_one_alert_until_a_success_resolves_it(db_session):
    subject = f"workflow:{uuid4()}"
    first, opened = await apply_signal(db_session, _failure(subject, "first"))
    again, opened_again = await apply_signal(db_session, _failure(subject, "second"))
    assert (opened, opened_again) == (True, False)
    assert again is not None and first is not None and again.id == first.id
    assert (again.occurrences, again.detail) == (2, "second")

    resolved, _ = await apply_signal(db_session, AlertSignal(action="resolve", kind="workflow_failed", subject_key=subject, organization_id=None))
    assert resolved is not None and resolved.status == "resolved"

    reopened, opened_new = await apply_signal(db_session, _failure(subject))
    assert opened_new is True and reopened is not None and reopened.id != first.id


async def test_an_unattended_failure_event_opens_an_alert_and_queues_its_email(db_session, email_on, alerts_feature):
    workflow_id = uuid4()
    try:
        body = {
            "organization": {"id": None, "name": None},
            "workflow": {"id": str(workflow_id), "name": "nightly_sync"},
            "execution": {"id": str(uuid4())},
            "trigger": {"type": "event", "event_type": "schedule", "event_id": str(uuid4())},
            "error": {"type": "RuntimeError", "message": "upstream timed out"},
        }
        await record_from_event("workflow.retry_exhausted", body)
        await record_from_event("workflow.retry_exhausted", body)

        alerts = (await db_session.execute(select(Alert).where(Alert.workflow_id == workflow_id))).scalars().all()
        assert [(a.status, a.occurrences, a.title) for a in alerts] == [("open", 2, "nightly_sync failed")]
        jobs = (
            await db_session.execute(
                select(PlatformJob).where(PlatformJob.job_type == "alert.email", PlatformJob.resource_id == str(alerts[0].id))
            )
        ).scalars().all()
        assert len(jobs) == 1  # one email per alert, not per occurrence
    finally:
        await db_session.execute(delete(Alert).where(Alert.workflow_id == workflow_id))
        await db_session.commit()


async def test_a_run_a_person_started_never_alerts(db_session, alerts_feature):
    workflow_id = uuid4()
    await record_from_event(
        "workflow.retry_exhausted",
        {
            "organization": {"id": None},
            "workflow": {"id": str(workflow_id), "name": "x"},
            "execution": {"id": str(uuid4())},
            "trigger": {"type": "manual"},
            "error": {"type": "E", "message": "m"},
        },
    )
    assert (await db_session.execute(select(Alert).where(Alert.workflow_id == workflow_id))).first() is None


async def test_nothing_is_recorded_while_the_feature_is_off(db_session):
    platform_features.clear_cache()
    workflow_id = uuid4()
    await record_from_event(
        "workflow.retry_exhausted",
        {
            "organization": {"id": None},
            "workflow": {"id": str(workflow_id), "name": "x"},
            "execution": {"id": str(uuid4())},
            "trigger": {"type": "event"},
            "error": {"type": "E", "message": "m"},
        },
    )
    assert (await db_session.execute(select(Alert).where(Alert.workflow_id == workflow_id))).first() is None


class TestAlertsApi:
    async def test_admin_lists_counts_and_acknowledges(self, e2e_client, platform_admin, db_session):
        alert, _ = await apply_signal(db_session, _failure(f"workflow:{uuid4()}"))
        assert alert is not None
        await db_session.commit()
        alert_id = str(alert.id)

        listed = e2e_client.get("/api/alerts", headers=platform_admin.headers)
        assert listed.status_code == 200, listed.text
        assert alert_id in {a["id"] for a in listed.json()["items"]}
        assert e2e_client.get("/api/alerts/count", headers=platform_admin.headers).json()["open"] >= 1

        acked = e2e_client.post(f"/api/alerts/{alert_id}/acknowledge", headers=platform_admin.headers)
        assert acked.status_code == 200, acked.text
        assert (acked.json()["status"], acked.json()["acknowledged_by"]) == ("acknowledged", platform_admin.email)
        resolved = e2e_client.post(f"/api/alerts/{alert_id}/resolve", headers=platform_admin.headers)
        assert resolved.json()["status"] == "resolved"

    def test_an_organization_user_cannot_see_alerts(self, e2e_client, org1_user):
        assert e2e_client.get("/api/alerts", headers=org1_user.headers).status_code == 403
        assert e2e_client.get("/api/alerts/email-settings", headers=org1_user.headers).status_code == 403

    def test_email_settings_keep_the_password_out_of_reads(self, e2e_client, platform_admin):
        headers = platform_admin.headers
        incomplete = e2e_client.put("/api/alerts/email-settings", headers=headers, json={"enabled": True})
        assert incomplete.status_code == 422
        assert "SMTP server" in incomplete.text

        saved = e2e_client.put(
            "/api/alerts/email-settings",
            headers=headers,
            json={
                "enabled": False,
                "host": "smtp.office365.com",
                "port": 587,
                "security": "starttls",
                "username": "alerts@example.com",
                "password": "s3cret-app-password",
                "from_address": "alerts@example.com",
                "recipients": ["Ops@Example.com"],
            },
        )
        assert saved.status_code == 200, saved.text
        read = e2e_client.get("/api/alerts/email-settings", headers=headers)
        assert read.json()["password_set"] is True
        assert read.json()["recipients"] == ["ops@example.com"]
        assert "s3cret" not in read.text
        # Off: a test send is refused instead of reaching the server.
        assert e2e_client.post("/api/alerts/email-settings/test", headers=headers).status_code == 409


async def test_the_email_job_sends_once_and_records_it(db_session, email_on, alerts_feature, monkeypatch):
    from src.jobs.platform.alert_email import AlertEmailPayload, run_alert_email
    from src.services import alert_email

    sent = []
    monkeypatch.setattr(alert_email, "send", lambda settings, message: sent.append(message))
    alert, _ = await apply_signal(db_session, _failure(f"workflow:{uuid4()}", "upstream timed out"))
    assert alert is not None
    await db_session.commit()

    result = await run_alert_email(_Context(), AlertEmailPayload(alert_id=alert.id))  # type: ignore[arg-type]
    again = await run_alert_email(_Context(), AlertEmailPayload(alert_id=alert.id))  # type: ignore[arg-type]

    assert result == {"sent": True, "recipients": 1}
    assert again["sent"] is False
    assert len(sent) == 1 and "upstream timed out" in sent[0].get_content()
    await db_session.refresh(alert)
    assert alert.emailed_at is not None


async def test_an_smtp_failure_fails_the_job_so_it_is_retried(db_session, email_on, alerts_feature, monkeypatch):
    from src.jobs.platform.alert_email import AlertEmailPayload, run_alert_email
    from src.jobs.platform.base import PlatformJobFailure
    from src.services import alert_email
    from src.services.alert_email import SmtpSendError

    def refuse(settings, message):
        raise SmtpSendError("Couldn't reach smtp.invalid:587")

    monkeypatch.setattr(alert_email, "send", refuse)
    alert, _ = await apply_signal(db_session, _failure(f"workflow:{uuid4()}"))
    assert alert is not None
    await db_session.commit()
    with pytest.raises(PlatformJobFailure) as failed:
        await run_alert_email(_Context(), AlertEmailPayload(alert_id=alert.id))  # type: ignore[arg-type]
    assert failed.value.retryable
