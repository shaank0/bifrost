"""Gateway configuration: slugs, static headers, grants and the access preview."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.contracts.mcp_gateway import (
    MCPGatewayCategoryRule,
    MCPGatewayConnectionUpdate,
)
from src.models.orm.external_mcp import MCPConnection, MCPConnectionTool, MCPServer
from src.models.orm.oauth import OAuthProvider
from src.models.orm.organizations import Organization
from src.models.orm.users import Role, User
from src.services.mcp_client.auth_resolution import static_headers
from src.services.mcp_gateway import admin


async def _connection(db: AsyncSession, *, oauth: bool = False) -> MCPConnection:
    org = Organization(id=uuid4(), name=f"org-{uuid4().hex[:8]}", is_active=True, created_by="test")
    db.add(org)
    provider_id = None
    if oauth:
        provider = OAuthProvider(
            id=uuid4(),
            provider_name=f"provider-{uuid4().hex[:8]}",
            client_id="client",
            encrypted_client_secret=b"secret",
            token_url="https://example.invalid/token",
        )
        db.add(provider)
        await db.flush()
        provider_id = provider.id
    server = MCPServer(
        id=uuid4(),
        name=f"server-{uuid4().hex[:8]}",
        server_url="https://example.invalid/mcp",
        oauth_provider_id=provider_id,
        is_active=True,
    )
    connection = MCPConnection(
        id=uuid4(),
        server=server,
        organization_id=org.id,
        client_id="unused",
        encrypted_client_secret="unused",
    )
    db.add(connection)
    for name in ("get_ticket", "update_ticket"):
        db.add(MCPConnectionTool(connection_id=connection.id, tool_name=name, tool_schema={}))
    await db.flush()
    await db.refresh(connection, ["tools", "server"])
    return connection


async def _role(db: AsyncSession, name: str) -> Role:
    role = Role(id=uuid4(), name=f"{name}-{uuid4().hex[:8]}", created_by="test")
    db.add(role)
    await db.flush()
    return role


@pytest.mark.asyncio
async def test_enabling_requires_a_slug(db_session: AsyncSession) -> None:
    connection = await _connection(db_session)
    with pytest.raises(admin.GatewayConfigError):
        await admin.update_connection(
            db_session, connection, MCPGatewayConnectionUpdate(enabled=True)
        )


@pytest.mark.asyncio
async def test_slug_is_unique_per_organization(db_session: AsyncSession) -> None:
    first = await _connection(db_session)
    second = MCPConnection(
        id=uuid4(),
        server=MCPServer(
            id=uuid4(), name=f"server-{uuid4().hex[:8]}", server_url="https://x.invalid", is_active=True
        ),
        organization_id=first.organization_id,
        client_id="unused",
        encrypted_client_secret="unused",
    )
    db_session.add(second)
    await db_session.flush()
    await admin.update_connection(db_session, first, MCPGatewayConnectionUpdate(slug="autotask"))

    with pytest.raises(admin.GatewayConfigError) as excinfo:
        await admin.update_connection(db_session, second, MCPGatewayConnectionUpdate(slug="autotask"))
    assert excinfo.value.conflict


@pytest.mark.asyncio
async def test_static_headers_are_encrypted_and_only_names_are_described(
    db_session: AsyncSession,
) -> None:
    connection = await _connection(db_session)
    await admin.set_static_headers(db_session, connection, {"X-API-Key": "s3cret"})

    assert "s3cret" not in connection.encrypted_static_headers
    assert static_headers(connection) == {"X-API-Key": "s3cret"}
    described = await admin.describe_connection(db_session, connection)
    assert described.static_header_names == ["X-API-Key"]

    await admin.set_static_headers(db_session, connection, None)
    assert static_headers(connection) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [{}, {"Bad Header": "x"}])
async def test_static_headers_reject_empty_or_invalid_names(
    db_session: AsyncSession, headers: dict[str, str]
) -> None:
    connection = await _connection(db_session)
    with pytest.raises(admin.GatewayConfigError):
        await admin.set_static_headers(db_session, connection, headers)


@pytest.mark.asyncio
async def test_static_headers_are_refused_for_oauth_servers(db_session: AsyncSession) -> None:
    connection = await _connection(db_session, oauth=True)
    with pytest.raises(admin.GatewayConfigError):
        await admin.set_static_headers(db_session, connection, {"X-API-Key": "s3cret"})


@pytest.mark.asyncio
async def test_grants_drive_the_per_tool_preview(db_session: AsyncSession) -> None:
    connection = await _connection(db_session)
    readers, editors = await _role(db_session, "readers"), await _role(db_session, "editors")
    admin_user = User(email=f"{uuid4()}@gateway.example", name="Admin", organization_id=connection.organization_id)
    db_session.add(admin_user)
    await db_session.flush()
    granted_by = admin_user.id
    await admin.update_connection(db_session, connection, MCPGatewayConnectionUpdate(slug="psa"))
    await admin.put_grant(
        db_session, connection, readers.id, MCPGatewayCategoryRule(categories=["read"]), granted_by
    )
    await admin.put_grant(db_session, connection, editors.id, None, granted_by)

    described = await admin.describe_connection(db_session, connection)
    by_tool = {tool.tool_name: tool for tool in described.tools}
    assert by_tool["get_ticket"].gateway_name == "psa__get_ticket"
    assert set(by_tool["get_ticket"].granted_role_ids) == {readers.id, editors.id}
    assert by_tool["update_ticket"].granted_role_ids == [editors.id]

    assert await admin.delete_grant(db_session, connection, editors.id)
    assert not await admin.delete_grant(db_session, connection, editors.id)
    described = await admin.describe_connection(db_session, connection)
    assert {tool.tool_name: tool.granted_role_ids for tool in described.tools}["update_ticket"] == []


@pytest.mark.asyncio
async def test_grant_for_unknown_role_is_not_found(db_session: AsyncSession) -> None:
    connection = await _connection(db_session)
    with pytest.raises(admin.GatewayConfigError) as excinfo:
        await admin.put_grant(db_session, connection, uuid4(), None, uuid4())
    assert excinfo.value.not_found
