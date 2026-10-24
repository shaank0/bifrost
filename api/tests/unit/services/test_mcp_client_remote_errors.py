"""Remote MCP failures arrive wrapped in task-group exception groups."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.services.mcp_client import dispatch
from src.services.mcp_client.auth_resolution import ResolutionPath
from src.services.mcp_client.errors import (
    NeedsReauthError,
    ToolDispatchError,
    describe_remote_error,
)


def _grouped(exc: Exception) -> BaseExceptionGroup:
    return BaseExceptionGroup("unhandled errors in a TaskGroup", [exc])


def _connection() -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), encrypted_static_headers=None)


def _catalog_row() -> SimpleNamespace:
    return SimpleNamespace(enabled=True, disabled_reason=None)


def test_describe_remote_error_names_the_underlying_errors() -> None:
    error = _grouped(ConnectionRefusedError("connection refused"))
    assert describe_remote_error(error) == "ConnectionRefusedError: connection refused"


@pytest.mark.asyncio
async def test_dispatch_failures_report_the_underlying_error() -> None:
    with (
        patch.object(dispatch, "_load_tool", AsyncMock(return_value=_catalog_row())),
        patch.object(
            dispatch, "resolve_token", AsyncMock(return_value=("tok", ResolutionPath.SERVICE_FALLBACK_AUTONOMOUS))
        ),
        patch.object(
            dispatch,
            "_call_remote",
            AsyncMock(side_effect=_grouped(ConnectionRefusedError("connection refused"))),
        ),
    ):
        with pytest.raises(ToolDispatchError, match="ConnectionRefusedError: connection refused"):
            await dispatch.invoke(_connection(), "get_ticket", {}, uuid4(), AsyncMock())


@pytest.mark.asyncio
async def test_grouped_auth_rejections_take_the_reauth_path() -> None:
    db = AsyncMock()
    with (
        patch.object(dispatch, "_load_tool", AsyncMock(return_value=_catalog_row())),
        patch.object(
            dispatch, "resolve_token", AsyncMock(return_value=("tok", ResolutionPath.USER_TOKEN))
        ),
        patch.object(
            dispatch,
            "_call_remote",
            AsyncMock(side_effect=_grouped(RuntimeError("401 Unauthorized"))),
        ) as call_remote,
    ):
        with pytest.raises(NeedsReauthError):
            await dispatch.invoke(_connection(), "get_ticket", {}, uuid4(), db)

    assert call_remote.await_count == 2
