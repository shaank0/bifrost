"""Gateway tool listing and call enforcement against real rows."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.principal import UserPrincipal
from src.models.orm.audit import AuditLog
from src.models.orm.external_mcp import (
    MCPConnection,
    MCPConnectionTool,
    MCPGatewayRoleGrant,
    MCPServer,
)
from src.models.orm.organizations import Organization
from src.models.orm.users import Role
from shared.builtin_roles import WILDCARD_PERMISSION
from src.services.authorization.context import (
    AuthorizationContext,
    Boundary,
    BoundaryKind,
    RoleGrant,
)
from src.services.authorization.enforce import Caller
from src.services.mcp_gateway.service import (
    GatewayCallError,
    call_gateway_tool,
    list_gateway_tools,
)

DISPATCH = "src.services.mcp_gateway.service.mcp_dispatch.invoke"


async def _org(db: AsyncSession) -> Organization:
    org = Organization(id=uuid4(), name=f"org-{uuid4().hex[:8]}", is_active=True, created_by="test")
    db.add(org)
    await db.flush()
    return org


async def _role(db: AsyncSession) -> Role:
    role = Role(id=uuid4(), name=f"role-{uuid4().hex[:8]}", created_by="test")
    db.add(role)
    await db.flush()
    return role


async def _connection(
    db: AsyncSession,
    org: Organization,
    *,
    slug: str | None = "autotask",
    enabled: bool = True,
    tools: tuple[str, ...] = ("get_ticket", "delete_ticket", "raw_request"),
) -> MCPConnection:
    server = MCPServer(
        id=uuid4(),
        name=f"server-{uuid4().hex[:8]}",
        server_url="https://example.invalid/mcp",
        is_active=True,
    )
    connection = MCPConnection(
        id=uuid4(),
        server=server,
        organization_id=org.id,
        client_id="unused",
        encrypted_client_secret="unused",
        gateway_enabled=enabled,
        gateway_slug=slug,
    )
    db.add(connection)
    for name in tools:
        db.add(
            MCPConnectionTool(
                connection_id=connection.id,
                tool_name=name,
                tool_schema={"type": "object", "properties": {"id": {"type": "integer"}}},
                description=f"{name} tool",
            )
        )
    await db.flush()
    return connection


async def _grant(db: AsyncSession, connection: MCPConnection, role: Role, rule) -> None:
    db.add(MCPGatewayRoleGrant(connection_id=connection.id, role_id=role.id, rule=rule))
    await db.flush()


def _caller(org: Organization, base_role: Role, *, admin: bool = False) -> Caller:
    user_id = uuid4()
    principal = UserPrincipal(user_id=user_id, email="user@example.com", organization_id=org.id)
    admin_grants = (
        RoleGrant(uuid4(), frozenset({WILDCARD_PERMISSION}), (Boundary(BoundaryKind.PLATFORM),)),
    )
    ctx = AuthorizationContext(
        user_id=user_id,
        home_organization_id=org.id,
        base_role_id=base_role.id,
        is_external=False,
        base_permissions=frozenset(),
        role_grants=admin_grants if admin else (),
    )
    return Caller(principal, ctx)


async def _audit_rows(db: AsyncSession, connection_id: UUID) -> list[AuditLog]:
    rows = await db.execute(
        select(AuditLog).where(
            AuditLog.action == "mcp_gateway.tool_call",
            AuditLog.resource_id == connection_id,
        )
    )
    return list(rows.scalars())


@pytest.mark.asyncio
async def test_lists_only_tools_the_callers_roles_grant(db_session: AsyncSession) -> None:
    org, role = await _org(db_session), await _role(db_session)
    connection = await _connection(db_session, org)
    await _grant(db_session, connection, role, {"categories": ["read"]})

    tools = await list_gateway_tools(db_session, _caller(org, role))

    assert [tool.name for tool in tools] == ["autotask__get_ticket"]
    assert tools[0].category == "read"
    assert tools[0].description == "get_ticket tool"
    assert tools[0].input_schema == {"type": "object", "properties": {"id": {"type": "integer"}}}


@pytest.mark.asyncio
async def test_hides_ungranted_disabled_and_other_org_connections(db_session: AsyncSession) -> None:
    org, other_org, role = await _org(db_session), await _org(db_session), await _role(db_session)
    await _connection(db_session, org, slug="nogrant")
    disabled = await _connection(db_session, org, slug="off", enabled=False)
    elsewhere = await _connection(db_session, other_org, slug="elsewhere")
    await _grant(db_session, disabled, role, None)
    await _grant(db_session, elsewhere, role, None)

    assert await list_gateway_tools(db_session, _caller(org, role)) == []


@pytest.mark.asyncio
async def test_disabled_catalog_tools_are_never_served(db_session: AsyncSession) -> None:
    org, role = await _org(db_session), await _role(db_session)
    connection = await _connection(db_session, org, tools=("get_ticket",))
    await _grant(db_session, connection, role, None)
    for row in (await db_session.execute(select(MCPConnectionTool))).scalars():
        if row.connection_id == connection.id:
            row.enabled = False
    await db_session.flush()

    assert await list_gateway_tools(db_session, _caller(org, role)) == []


@pytest.mark.asyncio
async def test_denied_call_never_dispatches_and_is_audited(db_session: AsyncSession) -> None:
    org, role = await _org(db_session), await _role(db_session)
    connection = await _connection(db_session, org)
    await _grant(db_session, connection, role, {"categories": ["read"]})

    with patch(DISPATCH, new_callable=AsyncMock) as invoke:
        with pytest.raises(GatewayCallError) as excinfo:
            await call_gateway_tool(db_session, _caller(org, role), "autotask__delete_ticket", {})

    assert excinfo.value.code == "not_found"
    invoke.assert_not_awaited()
    [row] = await _audit_rows(db_session, connection.id)
    assert row.outcome == "failure"
    assert row.details["error_code"] == "not_found"
    assert row.details["category"] == "delete"


@pytest.mark.asyncio
async def test_unknown_names_are_not_found(db_session: AsyncSession) -> None:
    org, role = await _org(db_session), await _role(db_session)
    for name in ("no-separator", "missing__get_ticket", "autotask__"):
        with pytest.raises(GatewayCallError) as excinfo:
            await call_gateway_tool(db_session, _caller(org, role), name, {})
        assert excinfo.value.code == "not_found"


@pytest.mark.asyncio
async def test_allowed_call_dispatches_as_the_caller_and_is_audited(db_session: AsyncSession) -> None:
    org, role = await _org(db_session), await _role(db_session)
    connection = await _connection(db_session, org)
    await _grant(db_session, connection, role, ["get_ticket"])
    caller = _caller(org, role)
    envelope = {
        "content": [{"type": "text", "text": "ok"}],
        "structured_content": None,
        "is_error": False,
        "_resolution_path": "user_token",
    }

    with patch(DISPATCH, new_callable=AsyncMock, return_value=envelope) as invoke:
        result = await call_gateway_tool(db_session, caller, "autotask__get_ticket", {"id": 7})

    assert result == {"content": [{"type": "text", "text": "ok"}], "structured_content": None, "is_error": False}
    _, tool_name, arguments = invoke.await_args.args
    assert (tool_name, arguments) == ("get_ticket", {"id": 7})
    assert invoke.await_args.kwargs["caller_user_id"] == caller.principal.user_id
    [row] = await _audit_rows(db_session, connection.id)
    assert row.outcome == "success"
    assert row.details["resolution_path"] == "user_token"


@pytest.mark.asyncio
async def test_platform_admins_need_a_grant_like_everyone_else(db_session: AsyncSession) -> None:
    org, role = await _org(db_session), await _role(db_session)
    await _connection(db_session, org)

    assert await list_gateway_tools(db_session, _caller(org, role, admin=True)) == []
