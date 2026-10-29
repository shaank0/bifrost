"""Failure alerts and the platform SMTP settings that email them (platform administrators)."""

from __future__ import annotations

import asyncio
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.core.auth import Context, CurrentActiveUser
from src.core.database import AsyncSession, get_db
from src.models.contracts.alerts import (
    AlertCountResponse,
    AlertEmailSettingsPublic,
    AlertEmailSettingsRequest,
    AlertEmailTestResponse,
    AlertListResponse,
    AlertPublic,
    AlertStatus,
)
from src.services import alert_email, alerts
from src.services.alert_email import SmtpSendError
from src.services.alert_email_settings import AlertEmailSettingsService
from src.services.authorization.enforce import authorize_operation
from src.services.authorization.evaluator import GLOBAL


async def _authorize_global_route(
    request: Request, user: CurrentActiveUser, db: AsyncSession = Depends(get_db, scope="function")
) -> None:
    await authorize_operation(db, user, f"{request.method} {request.scope['route'].path}", GLOBAL)


router = APIRouter(prefix="/api/alerts", tags=["Alerts"], dependencies=[Depends(_authorize_global_route)])

STATUS_VIEWS: dict[str, list[AlertStatus]] = {
    "unresolved": ["open", "acknowledged"],
    "open": ["open"],
    "acknowledged": ["acknowledged"],
    "resolved": ["resolved"],
}


@router.get("", response_model=AlertListResponse, summary="List failure alerts")
async def list_alerts(
    ctx: Context,
    user: CurrentActiveUser,
    view: Literal["unresolved", "open", "acknowledged", "resolved"] = "unresolved",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> AlertListResponse:
    rows, total = await alerts.list_alerts(ctx.db, STATUS_VIEWS[view], limit, offset)
    return AlertListResponse(items=[alerts.to_public(a) for a in rows], total=total)


@router.get("/count", response_model=AlertCountResponse, summary="Count unresolved failure alerts")
async def count_alerts(ctx: Context, user: CurrentActiveUser) -> AlertCountResponse:
    return await alerts.count_alerts(ctx.db)


@router.post("/{alert_id}/acknowledge", response_model=AlertPublic, summary="Acknowledge a failure alert")
async def acknowledge_alert(alert_id: UUID, ctx: Context, user: CurrentActiveUser) -> AlertPublic:
    alert = await alerts.acknowledge(ctx.db, alert_id, by=user.email)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    await ctx.db.commit()
    await alerts.publish_alerts_changed()
    return alerts.to_public(alert)


@router.post("/{alert_id}/resolve", response_model=AlertPublic, summary="Resolve a failure alert by hand")
async def resolve_alert(alert_id: UUID, ctx: Context, user: CurrentActiveUser) -> AlertPublic:
    alert = await alerts.resolve(ctx.db, alert_id)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    await ctx.db.commit()
    await alerts.publish_alerts_changed()
    return alerts.to_public(alert)


@router.get("/email-settings", response_model=AlertEmailSettingsPublic, summary="Get alert email settings")
async def get_email_settings(ctx: Context, user: CurrentActiveUser) -> AlertEmailSettingsPublic:
    return await AlertEmailSettingsService(ctx.db).get()


@router.put("/email-settings", response_model=AlertEmailSettingsPublic, summary="Set alert email settings")
async def set_email_settings(
    body: AlertEmailSettingsRequest, ctx: Context, user: CurrentActiveUser
) -> AlertEmailSettingsPublic:
    try:
        saved = await AlertEmailSettingsService(ctx.db).set(body, updated_by=user.email)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from None
    await ctx.db.commit()
    return saved


@router.post("/email-settings/test", response_model=AlertEmailTestResponse, summary="Send a test alert email")
async def send_test_email(ctx: Context, user: CurrentActiveUser) -> AlertEmailTestResponse:
    """Send a test message with the saved settings. Turn alert email on first."""
    settings = await AlertEmailSettingsService(ctx.db).smtp_settings()
    if settings is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Turn alert email on and save before sending a test")
    try:
        await asyncio.to_thread(alert_email.send, settings, alert_email.sample_email(settings))
    except SmtpSendError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from None
    return AlertEmailTestResponse(sent_to=settings.recipients)
