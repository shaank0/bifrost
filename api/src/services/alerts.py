"""Failure alerts: recorded from built-in platform events, read and acknowledged by platform admins.

``record_from_event`` is called for every built-in event (see
``events.builtins._emit``); ``alert_signals`` decides which ones matter. When an
alert opens and alert email is on, an ``alert.email`` platform job sends it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.contracts.alerts import AlertCountResponse, AlertPublic, AlertStatus
from src.models.orm.alerts import Alert
from src.services.alert_signals import AlertSignal, signal_from_event

logger = logging.getLogger(__name__)

# The WebSocket channel platform admins' browsers listen on for alert changes.
ALERTS_CHANNEL = "alerts"


def _uuid(value: str | None) -> UUID | None:
    return UUID(value) if value else None


async def apply_signal(db: AsyncSession, signal: AlertSignal) -> tuple[Alert | None, bool]:
    """Apply one signal. Returns (the alert it touched, whether it opened a new one)."""
    now = datetime.now(timezone.utc)
    if signal.action == "resolve":
        result = await db.execute(
            update(Alert)
            .where(Alert.subject_key == signal.subject_key, Alert.status != "resolved")
            .values(status="resolved", resolved_at=now)
            .returning(Alert),
            execution_options={"populate_existing": True},
        )
        return result.scalars().first(), False

    values = {
        "organization_id": _uuid(signal.organization_id),
        "kind": signal.kind,
        "subject_key": signal.subject_key,
        "status": "open",
        "title": signal.title[:300],
        "detail": signal.detail,
        "workflow_id": _uuid(signal.workflow_id),
        "integration_id": _uuid(signal.integration_id),
        "last_execution_id": _uuid(signal.execution_id),
        "occurrences": 1,
        "first_seen_at": now,
        "last_seen_at": now,
    }
    statement = insert(Alert).values(**values)
    # One unresolved alert per subject: a repeat failure adds to it (an acknowledged one stays acknowledged).
    statement = statement.on_conflict_do_update(
        index_elements=[Alert.subject_key],
        index_where=text("status <> 'resolved'"),
        set_={
            "occurrences": Alert.occurrences + 1,
            "last_seen_at": now,
            "title": statement.excluded.title,
            "detail": statement.excluded.detail,
            "last_execution_id": statement.excluded.last_execution_id,
        },
    ).returning(Alert)
    # The session may already hold this alert: take the row the upsert returned, not the cached copy.
    alert = (await db.execute(statement, execution_options={"populate_existing": True})).scalars().one()
    return alert, alert.occurrences == 1


async def record_from_event(topic: str, body: dict[str, Any]) -> None:
    """Open, add to, or resolve the alert a built-in event implies. Never raises: alerting must
    not break the work that emitted the event."""
    try:
        signal = signal_from_event(topic, body)
        if signal is None:
            return
        from src.core.database import get_session_factory

        async with get_session_factory()() as db:
            alert, opened = await apply_signal(db, signal)
            job = None
            if opened and alert is not None:
                from src.jobs.platform.alert_email import enqueue_alert_email

                job = await enqueue_alert_email(db, alert)
            await db.commit()
        if alert is not None:
            await publish_alerts_changed()
        if job is not None:
            from src.services.platform_jobs import publish_platform_job_update

            await publish_platform_job_update(job)
    except Exception:
        logger.warning("Failed to record an alert for %s", topic, exc_info=True)


async def publish_alerts_changed() -> None:
    """Tell admins' browsers to refresh their alert count and list."""
    from src.core.pubsub import manager

    try:
        await manager.broadcast(ALERTS_CHANNEL, {"type": "alerts_changed"})
    except Exception:
        logger.warning("Failed to publish an alerts update", exc_info=True)


def to_public(alert: Alert) -> AlertPublic:
    return AlertPublic(
        id=alert.id,
        kind=alert.kind,  # type: ignore[arg-type]
        status=alert.status,  # type: ignore[arg-type]
        title=alert.title,
        detail=alert.detail,
        organization_id=alert.organization_id,
        organization_name=alert.organization.name if alert.organization else None,
        workflow_id=alert.workflow_id,
        integration_id=alert.integration_id,
        last_execution_id=alert.last_execution_id,
        occurrences=alert.occurrences,
        first_seen_at=alert.first_seen_at,
        last_seen_at=alert.last_seen_at,
        acknowledged_at=alert.acknowledged_at,
        acknowledged_by=alert.acknowledged_by,
        resolved_at=alert.resolved_at,
        emailed_at=alert.emailed_at,
    )


async def list_alerts(
    db: AsyncSession, statuses: list[AlertStatus], limit: int, offset: int
) -> tuple[list[Alert], int]:
    """Alerts in the given statuses, most recently seen first."""
    where = Alert.status.in_(statuses)
    total = (await db.execute(select(func.count()).select_from(Alert).where(where))).scalar_one()
    rows = await db.execute(
        select(Alert)
        .options(selectinload(Alert.organization))
        .where(where)
        .order_by(Alert.last_seen_at.desc(), Alert.id)
        .limit(limit)
        .offset(offset)
    )
    return list(rows.scalars().all()), total


async def count_alerts(db: AsyncSession) -> AlertCountResponse:
    rows = await db.execute(
        select(Alert.status, func.count()).where(Alert.status != "resolved").group_by(Alert.status)
    )
    by_status = {status: count for status, count in rows.all()}
    return AlertCountResponse(open=by_status.get("open", 0), unresolved=sum(by_status.values()))


async def acknowledge(db: AsyncSession, alert_id: UUID, by: str) -> Alert | None:
    """Mark an open alert as seen. It stays until the subject's next success resolves it."""
    alert = await db.get(Alert, alert_id, options=[selectinload(Alert.organization)])
    if alert is None:
        return None
    if alert.status == "open":
        alert.status = "acknowledged"
        alert.acknowledged_at = datetime.now(timezone.utc)
        alert.acknowledged_by = by
        await db.flush()
    return alert


async def resolve(db: AsyncSession, alert_id: UUID) -> Alert | None:
    """Close an alert by hand, for a subject that will never succeed again (deleted, retired)."""
    alert = await db.get(Alert, alert_id, options=[selectinload(Alert.organization)])
    if alert is None:
        return None
    if alert.status != "resolved":
        alert.status = "resolved"
        alert.resolved_at = datetime.now(timezone.utc)
        await db.flush()
    return alert
