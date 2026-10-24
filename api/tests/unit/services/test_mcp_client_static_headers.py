"""Connections with static headers dispatch with them instead of resolving a token."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.core.security import encrypt_secret
from src.services.mcp_client import dispatch
from src.services.mcp_client.auth_resolution import ResolutionPath
from src.services.mcp_client.errors import ToolDispatchError


def _connection(headers: dict[str, str] | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        encrypted_static_headers=None if headers is None else encrypt_secret(json.dumps(headers)),
    )


def _catalog_row() -> SimpleNamespace:
    return SimpleNamespace(enabled=True, disabled_reason=None)


def _call_result() -> SimpleNamespace:
    return SimpleNamespace(content=[], structuredContent={"ok": True}, isError=False)


@pytest.mark.asyncio
async def test_static_headers_are_sent_without_token_resolution() -> None:
    connection = _connection({"X-API-Key": "s3cret"})
    with (
        patch.object(dispatch, "_load_tool", AsyncMock(return_value=_catalog_row())),
        patch.object(dispatch, "resolve_token", AsyncMock()) as resolve_token,
        patch.object(dispatch, "_call_remote", AsyncMock(return_value=_call_result())) as call_remote,
    ):
        envelope = await dispatch.invoke(connection, "get_ticket", {}, uuid4(), AsyncMock())

    resolve_token.assert_not_awaited()
    assert call_remote.await_args.args[1] == {"X-API-Key": "s3cret"}
    assert envelope["_resolution_path"] == ResolutionPath.STATIC_HEADERS.value


@pytest.mark.asyncio
async def test_static_header_auth_rejection_is_not_retried() -> None:
    connection = _connection({"X-API-Key": "revoked"})
    with (
        patch.object(dispatch, "_load_tool", AsyncMock(return_value=_catalog_row())),
        patch.object(
            dispatch, "_call_remote", AsyncMock(side_effect=RuntimeError("401 Unauthorized"))
        ) as call_remote,
    ):
        with pytest.raises(ToolDispatchError):
            await dispatch.invoke(connection, "get_ticket", {}, uuid4(), AsyncMock())

    assert call_remote.await_count == 1


@pytest.mark.asyncio
async def test_connections_without_static_headers_send_the_resolved_bearer_token() -> None:
    connection = _connection(None)
    with (
        patch.object(dispatch, "_load_tool", AsyncMock(return_value=_catalog_row())),
        patch.object(
            dispatch,
            "resolve_token",
            AsyncMock(return_value=("tok", ResolutionPath.USER_TOKEN)),
        ),
        patch.object(dispatch, "_call_remote", AsyncMock(return_value=_call_result())) as call_remote,
    ):
        await dispatch.invoke(connection, "get_ticket", {}, uuid4(), AsyncMock())

    assert call_remote.await_args.args[1] == {"Authorization": "Bearer tok"}
