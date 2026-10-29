"""The platform SMTP settings alert email is sent with, kept in system_configs.

Two global rows: the settings (key ``smtp``) and the encrypted password (key
``password``), so the password never travels with the readable settings.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import decrypt_secret, encrypt_secret
from src.models.contracts.alerts import (
    ALERT_EMAIL_CONFIG_CATEGORY,
    AlertEmailSettingsPublic,
    AlertEmailSettingsRequest,
)
from src.models.orm.config import SystemConfig
from src.services.alert_email import SmtpSettings

logger = logging.getLogger(__name__)

SETTINGS_KEY = "smtp"
PASSWORD_KEY = "password"


class AlertEmailSettingsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _row(self, key: str) -> SystemConfig | None:
        result = await self.db.execute(
            select(SystemConfig).where(
                SystemConfig.category == ALERT_EMAIL_CONFIG_CATEGORY,
                SystemConfig.key == key,
                SystemConfig.organization_id.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def _write(self, key: str, value: object, updated_by: str) -> None:
        row = await self._row(key)
        if row:
            row.value_json = {"value": value}
            row.updated_by = updated_by
        else:
            self.db.add(
                SystemConfig(
                    category=ALERT_EMAIL_CONFIG_CATEGORY,
                    key=key,
                    value_json={"value": value},
                    organization_id=None,
                    created_by=updated_by,
                    updated_by=updated_by,
                )
            )

    async def _password(self) -> str | None:
        row = await self._row(PASSWORD_KEY)
        stored = (row.value_json or {}).get("value") if row else None
        if not stored:
            return None
        try:
            return decrypt_secret(stored)
        except Exception as e:
            logger.error(f"Failed to decrypt the alert email SMTP password: {e}")
            return None

    async def get(self) -> AlertEmailSettingsPublic:
        row = await self._row(SETTINGS_KEY)
        stored = ((row.value_json or {}).get("value") if row else None) or {}
        password_row = await self._row(PASSWORD_KEY)
        return AlertEmailSettingsPublic(
            **stored,
            password_set=bool(password_row and (password_row.value_json or {}).get("value")),
        )

    async def set(self, request: AlertEmailSettingsRequest, updated_by: str) -> AlertEmailSettingsPublic:
        """Store the settings. Raises ValueError when email is turned on without what it needs to send."""
        if request.enabled:
            missing = [
                label
                for label, value in (
                    ("an SMTP server", request.host.strip()),
                    ("a From address", request.from_address),
                    ("at least one recipient", request.recipients),
                )
                if not value
            ]
            if missing:
                raise ValueError(f"To turn alert email on, set {', '.join(missing)}")
        settings = request.model_dump(exclude={"password"})
        settings["host"] = request.host.strip()
        settings["username"] = request.username.strip()
        settings["recipients"] = sorted({str(r).lower() for r in request.recipients})
        await self._write(SETTINGS_KEY, settings, updated_by)
        if request.password is not None:
            await self._write(PASSWORD_KEY, encrypt_secret(request.password) if request.password else "", updated_by)
        await self.db.flush()
        return await self.get()

    async def smtp_settings(self) -> SmtpSettings | None:
        """What sending needs, or None while alert email is off."""
        public = await self.get()
        if not public.enabled:
            return None
        return SmtpSettings(
            host=public.host,
            port=public.port,
            security=public.security,
            username=public.username or None,
            password=await self._password(),
            from_address=public.from_address,
            recipients=list(public.recipients),
        )
