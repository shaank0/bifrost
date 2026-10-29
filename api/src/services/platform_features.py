"""Whether an optional platform feature is turned on (Settings → Platform → Features).

Features are off unless a platform admin turned them on. Reads are cached for
``CACHE_SECONDS`` per process, so hot paths (every workflow completion asks
about alerts) don't add a query each time; a change reaches other replicas
within that window.
"""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.contracts.platform_features import (
    PLATFORM_FEATURES,
    PLATFORM_FEATURES_CONFIG_CATEGORY,
    PlatformFeaturePublic,
)
from src.models.orm.config import SystemConfig

CACHE_SECONDS = 30.0

_cache: tuple[float, dict[str, bool]] | None = None


async def _load(db: AsyncSession) -> dict[str, bool]:
    rows = await db.execute(
        select(SystemConfig.key, SystemConfig.value_json).where(
            SystemConfig.category == PLATFORM_FEATURES_CONFIG_CATEGORY,
            SystemConfig.organization_id.is_(None),
        )
    )
    stored = {key: bool((value or {}).get("value")) for key, value in rows.all()}
    return {key: stored.get(key, False) for key in PLATFORM_FEATURES}


async def enabled_features(db: AsyncSession | None = None) -> dict[str, bool]:
    """Every known feature and whether it is on."""
    global _cache
    if _cache is not None and _cache[0] > time.monotonic():
        return dict(_cache[1])
    if db is None:
        from src.core.database import get_db_context

        async with get_db_context() as session:
            values = await _load(session)
    else:
        values = await _load(db)
    _cache = (time.monotonic() + CACHE_SECONDS, values)
    return dict(values)


async def is_enabled(key: str, db: AsyncSession | None = None) -> bool:
    if key not in PLATFORM_FEATURES:
        raise KeyError(f"Unknown platform feature {key!r}")
    return (await enabled_features(db))[key]


def clear_cache() -> None:
    global _cache
    _cache = None


async def list_features(db: AsyncSession) -> list[PlatformFeaturePublic]:
    clear_cache()
    values = await enabled_features(db)
    return [PlatformFeaturePublic(**info.model_dump(), enabled=values[key]) for key, info in PLATFORM_FEATURES.items()]


async def set_features(db: AsyncSession, changes: dict[str, bool], updated_by: str) -> list[PlatformFeaturePublic]:
    """Switch features on or off. Raises KeyError for a feature that doesn't exist."""
    unknown = sorted(set(changes) - set(PLATFORM_FEATURES))
    if unknown:
        raise KeyError(f"Unknown platform features: {', '.join(unknown)}")
    for key, enabled in changes.items():
        row = (
            await db.execute(
                select(SystemConfig).where(
                    SystemConfig.category == PLATFORM_FEATURES_CONFIG_CATEGORY,
                    SystemConfig.key == key,
                    SystemConfig.organization_id.is_(None),
                )
            )
        ).scalar_one_or_none()
        if row:
            row.value_json = {"value": enabled}
            row.updated_by = updated_by
        else:
            db.add(
                SystemConfig(
                    category=PLATFORM_FEATURES_CONFIG_CATEGORY,
                    key=key,
                    value_json={"value": enabled},
                    organization_id=None,
                    created_by=updated_by,
                    updated_by=updated_by,
                )
            )
    await db.flush()
    clear_cache()
    return await list_features(db)
