"""Platform job that emails a newly opened failure alert through the platform SMTP server."""

import asyncio
from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.jobs.platform.base import PlatformJobContext, PlatformJobFailure, define_platform_job
from src.models.orm.alerts import Alert
from src.models.orm.platform_jobs import PlatformJob
from src.services import alert_email
from src.services.alert_email import AlertMessage, SmtpSendError
from src.services.alert_email_settings import AlertEmailSettingsService
from src.services.platform_features import is_enabled

JOB_TYPE = "alert.email"


class AlertEmailPayload(BaseModel):
    alert_id: UUID


def _when(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


async def run_alert_email(context: PlatformJobContext, payload: AlertEmailPayload) -> dict:
    from src.config import get_settings
    from src.core.database import get_db_context

    async with get_db_context() as db:
        alert = await db.get(Alert, payload.alert_id, options=[selectinload(Alert.organization)])
        if alert is None:
            return {"sent": False, "reason": "The alert no longer exists"}
        if alert.status == "resolved" or alert.emailed_at is not None:
            return {"sent": False, "reason": "The alert was already resolved or emailed"}
        settings = await AlertEmailSettingsService(db).smtp_settings()
        if settings is None or not await is_enabled("alerts", db):
            return {"sent": False, "reason": "Alert email is off"}
        public_url = (get_settings().public_url or "").rstrip("/")
        message = alert_email.alert_email(
            AlertMessage(
                title=alert.title,
                detail=alert.detail,
                organization_name=alert.organization.name if alert.organization else None,
                occurrences=alert.occurrences,
                first_seen=_when(alert.first_seen_at),
                last_seen=_when(alert.last_seen_at),
                link=f"{public_url}/alerts" if public_url else None,
            ),
            settings,
        )
        await context.report("Sending alert email", percent=50)
        try:
            await asyncio.to_thread(alert_email.send, settings, message)
        except SmtpSendError as e:
            raise PlatformJobFailure("alert_email_failed", str(e), retryable=True) from None
        alert.emailed_at = datetime.now(timezone.utc)
        await db.commit()
    return {"sent": True, "recipients": len(settings.recipients)}


ALERT_EMAIL_DEFINITION = define_platform_job(JOB_TYPE, AlertEmailPayload, run_alert_email)


async def enqueue_alert_email(db: AsyncSession, alert: Alert) -> PlatformJob | None:
    """Queue the email for a newly opened alert, when alert email is on. The caller commits."""
    from src.services.platform_jobs import enqueue_platform_job

    if await AlertEmailSettingsService(db).smtp_settings() is None:
        return None
    job, _ = await enqueue_platform_job(
        db,
        ALERT_EMAIL_DEFINITION,
        AlertEmailPayload(alert_id=alert.id),
        dedupe_key=str(alert.id),
        priority=500,
        organization_id=None,
        requested_by_user_id="system",
        requested_by_email="system@gobifrost.local",
        requested_by_name="Bifrost Alerts",
        resource_type="alert",
        resource_id=str(alert.id),
        title=f"Email alert: {alert.title}"[:200],
        action_url="/alerts",
    )
    return job
