"""Optional platform features: list them and switch them on or off (platform administrators)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.core.auth import Context, CurrentActiveUser
from src.core.database import AsyncSession, get_db
from src.models.contracts.platform_features import PlatformFeaturesRequest, PlatformFeaturesResponse
from src.services import platform_features
from src.services.authorization.enforce import authorize_operation
from src.services.authorization.evaluator import GLOBAL


async def _authorize_global_route(
    request: Request, user: CurrentActiveUser, db: AsyncSession = Depends(get_db, scope="function")
) -> None:
    await authorize_operation(db, user, f"{request.method} {request.scope['route'].path}", GLOBAL)


router = APIRouter(
    prefix="/api/settings/features",
    tags=["Platform Features"],
    dependencies=[Depends(_authorize_global_route)],
)


@router.get("", response_model=PlatformFeaturesResponse, summary="List optional platform features")
async def list_platform_features(ctx: Context, user: CurrentActiveUser) -> PlatformFeaturesResponse:
    return PlatformFeaturesResponse(features=await platform_features.list_features(ctx.db))


@router.put("", response_model=PlatformFeaturesResponse, summary="Turn optional platform features on or off")
async def set_platform_features(
    body: PlatformFeaturesRequest, ctx: Context, user: CurrentActiveUser
) -> PlatformFeaturesResponse:
    try:
        features = await platform_features.set_features(ctx.db, body.enabled, updated_by=user.email)
    except KeyError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e.args[0])) from None
    await ctx.db.commit()
    return PlatformFeaturesResponse(features=features)
