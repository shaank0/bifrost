"""Failure alerts and the platform SMTP settings that email them."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

AlertStatus = Literal["open", "acknowledged", "resolved"]
AlertKind = Literal["workflow_failed", "integration_refresh_failed"]
SmtpSecurity = Literal["starttls", "ssl", "none"]

# The system_configs category that holds the alert email settings.
ALERT_EMAIL_CONFIG_CATEGORY = "alert_email"


class AlertPublic(BaseModel):
    id: UUID
    kind: AlertKind
    status: AlertStatus
    title: str
    detail: str
    organization_id: UUID | None
    organization_name: str | None
    workflow_id: UUID | None
    integration_id: UUID | None
    last_execution_id: UUID | None
    occurrences: int
    first_seen_at: datetime
    last_seen_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by: str | None
    resolved_at: datetime | None
    emailed_at: datetime | None


class AlertListResponse(BaseModel):
    items: list[AlertPublic]
    total: int


class AlertCountResponse(BaseModel):
    """Alerts nobody has looked at yet (open), and all unresolved ones (open + acknowledged)."""

    open: int
    unresolved: int


class AlertEmailSettingsPublic(BaseModel):
    enabled: bool = False
    host: str = ""
    port: int = 587
    security: SmtpSecurity = "starttls"
    username: str = ""
    password_set: bool = False
    from_address: str = ""
    recipients: list[str] = Field(default_factory=list)


class AlertEmailSettingsRequest(BaseModel):
    enabled: bool
    host: str = Field(default="", max_length=255)
    port: int = Field(default=587, ge=1, le=65535)
    security: SmtpSecurity = "starttls"
    username: str = Field(default="", max_length=320)
    # None keeps the stored password; an empty string removes it (for a relay that needs no sign-in).
    password: str | None = Field(default=None, max_length=1000)
    from_address: EmailStr | Literal[""] = ""
    recipients: list[EmailStr] = Field(default_factory=list, max_length=50)


class AlertEmailTestResponse(BaseModel):
    sent_to: list[str]
