"""MCP gateway configuration and per-user tool listing.

The gateway itself is the ``/mcp/gateway`` MCP endpoint. These routes
configure it per connection: exposure and slug, static headers for servers
with no OAuth provider, and the role grants that decide who sees which
tools. Reads require ``mcp.readbasic`` and mutations ``mcp.readwrite`` at the
connection's organization. ``GET /api/mcp-gateway/me/tools`` lists what the
current user is served.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from src.core.auth import Context, CurrentActiveUser
from src.models.contracts.mcp_gateway import (
    MCPGatewayConnectionPublic,
    MCPGatewayConnectionUpdate,
    MCPGatewayGrantUpdate,
    MCPGatewayMyTool,
    MCPGatewayStaticHeadersUpdate,
)
from src.models.orm.external_mcp import MCPConnection
from src.repositories.external_mcp import MCPConnectionRepository
from src.services.audit import emit_audit
from src.services.authorization.enforce import (
    load_caller,
    operation_reach,
    org_target,
    require_operation,
)
from src.services.mcp_gateway import admin
from src.services.mcp_gateway.service import list_gateway_tools

router = APIRouter(prefix="/api/mcp-gateway", tags=["MCP Gateway"])


async def _authorized_connection(
    ctx: Context, user: CurrentActiveUser, connection_id: UUID, *, operation: str
) -> MCPConnection:
    caller = await load_caller(ctx.db, user)
    reach = operation_reach(caller, operation)
    connection = await MCPConnectionRepository(session=ctx.db, org_id=None).get_connection(
        connection_id
    )
    if connection is None or not reach.covers(connection.organization_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP connection not found")
    require_operation(caller, operation, org_target(connection.organization_id))
    return connection


def _config_error(exc: admin.GatewayConfigError) -> HTTPException:
    if exc.not_found:
        code = status.HTTP_404_NOT_FOUND
    elif exc.conflict:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    return HTTPException(status_code=code, detail=str(exc))


@router.get(
    "/me/tools",
    response_model=list[MCPGatewayMyTool],
    summary="List the gateway tools served to the current user",
)
async def list_my_gateway_tools(ctx: Context, user: CurrentActiveUser) -> list[MCPGatewayMyTool]:
    caller = await load_caller(ctx.db, user)
    return [
        MCPGatewayMyTool(
            name=tool.name,
            connection_id=tool.connection_id,
            tool_name=tool.tool_name,
            category=tool.category,
            description=tool.description,
        )
        for tool in await list_gateway_tools(ctx.db, caller)
    ]


@router.get(
    "/connections/{connection_id}",
    response_model=MCPGatewayConnectionPublic,
    summary="Get a connection's gateway settings, grants, and tool access",
)
async def get_gateway_connection(
    connection_id: UUID, ctx: Context, user: CurrentActiveUser
) -> MCPGatewayConnectionPublic:
    connection = await _authorized_connection(
        ctx, user, connection_id, operation="GET /api/mcp-gateway/connections/{connection_id}"
    )
    return await admin.describe_connection(ctx.db, connection)


@router.patch(
    "/connections/{connection_id}",
    response_model=MCPGatewayConnectionPublic,
    summary="Update a connection's gateway exposure and slug",
)
async def update_gateway_connection(
    connection_id: UUID,
    request: MCPGatewayConnectionUpdate,
    ctx: Context,
    user: CurrentActiveUser,
) -> MCPGatewayConnectionPublic:
    connection = await _authorized_connection(
        ctx, user, connection_id, operation="PATCH /api/mcp-gateway/connections/{connection_id}"
    )
    try:
        await admin.update_connection(ctx.db, connection, request)
    except admin.GatewayConfigError as exc:
        raise _config_error(exc) from exc
    await emit_audit(
        ctx.db,
        "mcp_gateway.connection.update",
        resource_type="mcp_connection",
        resource_id=connection.id,
        details=request.model_dump(exclude_unset=True),
    )
    return await admin.describe_connection(ctx.db, connection)


@router.put(
    "/connections/{connection_id}/static-headers",
    response_model=MCPGatewayConnectionPublic,
    summary="Set or clear a connection's static headers",
)
async def set_gateway_static_headers(
    connection_id: UUID,
    request: MCPGatewayStaticHeadersUpdate,
    ctx: Context,
    user: CurrentActiveUser,
) -> MCPGatewayConnectionPublic:
    connection = await _authorized_connection(
        ctx, user, connection_id, operation="PUT /api/mcp-gateway/connections/{connection_id}/static-headers"
    )
    try:
        await admin.set_static_headers(ctx.db, connection, request.headers)
    except admin.GatewayConfigError as exc:
        raise _config_error(exc) from exc
    await emit_audit(
        ctx.db,
        "mcp_gateway.static_headers.update",
        resource_type="mcp_connection",
        resource_id=connection.id,
        details={"header_names": sorted(request.headers or {})},
    )
    return await admin.describe_connection(ctx.db, connection)


@router.put(
    "/connections/{connection_id}/grants/{role_id}",
    response_model=MCPGatewayConnectionPublic,
    summary="Grant a role access to a connection's gateway tools",
)
async def put_gateway_grant(
    connection_id: UUID,
    role_id: UUID,
    request: MCPGatewayGrantUpdate,
    ctx: Context,
    user: CurrentActiveUser,
) -> MCPGatewayConnectionPublic:
    connection = await _authorized_connection(
        ctx, user, connection_id, operation="PUT /api/mcp-gateway/connections/{connection_id}/grants/{role_id}"
    )
    try:
        await admin.put_grant(ctx.db, connection, role_id, request.rule, user.user_id)
    except admin.GatewayConfigError as exc:
        raise _config_error(exc) from exc
    await emit_audit(
        ctx.db,
        "mcp_gateway.grant.update",
        resource_type="mcp_connection",
        resource_id=connection.id,
        details={"role_id": str(role_id), "rule": request.model_dump(mode="json")["rule"]},
    )
    return await admin.describe_connection(ctx.db, connection)


@router.delete(
    "/connections/{connection_id}/grants/{role_id}",
    response_model=MCPGatewayConnectionPublic,
    summary="Remove a role's gateway grant on a connection",
)
async def delete_gateway_grant(
    connection_id: UUID,
    role_id: UUID,
    ctx: Context,
    user: CurrentActiveUser,
) -> MCPGatewayConnectionPublic:
    connection = await _authorized_connection(
        ctx, user, connection_id, operation="DELETE /api/mcp-gateway/connections/{connection_id}/grants/{role_id}"
    )
    if not await admin.delete_grant(ctx.db, connection, role_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grant not found")
    await emit_audit(
        ctx.db,
        "mcp_gateway.grant.delete",
        resource_type="mcp_connection",
        resource_id=connection.id,
        details={"role_id": str(role_id)},
    )
    return await admin.describe_connection(ctx.db, connection)
