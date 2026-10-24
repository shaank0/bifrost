"""Configure a connection's MCP gateway exposure, static headers, and grants.

Callers authorize the connection first (``mcp.readwrite`` at its
organization); these functions only validate and persist.
"""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import decrypt_secret, encrypt_secret
from src.models.contracts.mcp_gateway import (
    MCPGatewayCategoryRule,
    MCPGatewayConnectionPublic,
    MCPGatewayConnectionUpdate,
    MCPGatewayGrantPublic,
    MCPGatewayRule,
    MCPGatewayToolPublic,
)
from src.models.orm.external_mcp import MCPConnection, MCPGatewayRoleGrant
from src.models.orm.users import Role
from src.services.mcp_gateway.access import is_tool_allowed, parse_rule
from src.services.mcp_gateway.classifier import classify_tool
from src.services.mcp_gateway.service import gateway_tool_name

# RFC 9110 field-name token characters.
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


class GatewayConfigError(ValueError):
    """A gateway configuration request that cannot be applied as given."""

    def __init__(self, message: str, *, conflict: bool = False, not_found: bool = False) -> None:
        self.conflict = conflict
        self.not_found = not_found
        super().__init__(message)


def _stored_rule(rule: MCPGatewayRule) -> Any:
    if isinstance(rule, MCPGatewayCategoryRule):
        return rule.model_dump()
    return rule


def _public_rule(raw: Any) -> MCPGatewayRule:
    parsed = parse_rule(raw)
    if parsed is None:
        return None
    if isinstance(parsed, frozenset):
        return sorted(parsed)
    return MCPGatewayCategoryRule(
        categories=sorted(parsed.categories),  # type: ignore[arg-type]
        allow=sorted(parsed.allow),
        deny=sorted(parsed.deny),
    )


def static_header_names(connection: MCPConnection) -> list[str]:
    if connection.encrypted_static_headers is None:
        return []
    return sorted(json.loads(decrypt_secret(connection.encrypted_static_headers)))


async def describe_connection(
    db: AsyncSession, connection: MCPConnection
) -> MCPGatewayConnectionPublic:
    """Gateway settings, grants, and which roles each tool is served to."""
    grant_rows = (
        await db.execute(
            select(MCPGatewayRoleGrant, Role.name)
            .join(Role, Role.id == MCPGatewayRoleGrant.role_id)
            .where(MCPGatewayRoleGrant.connection_id == connection.id)
            .order_by(Role.name)
        )
    ).all()
    parsed = [(grant.role_id, parse_rule(grant.rule)) for grant, _ in grant_rows]
    tools = [
        MCPGatewayToolPublic(
            tool_name=row.tool_name,
            gateway_name=(
                gateway_tool_name(connection.gateway_slug, row.tool_name)
                if connection.gateway_slug
                else None
            ),
            category=classify_tool(row.tool_name),
            enabled=row.enabled,
            granted_role_ids=[
                role_id for role_id, access in parsed if is_tool_allowed(row.tool_name, access)
            ],
        )
        for row in sorted(connection.tools, key=lambda tool: tool.tool_name)
    ]
    return MCPGatewayConnectionPublic(
        connection_id=connection.id,
        organization_id=connection.organization_id,
        enabled=connection.gateway_enabled,
        slug=connection.gateway_slug,
        static_header_names=static_header_names(connection),
        grants=[
            MCPGatewayGrantPublic(role_id=grant.role_id, role_name=name, rule=_public_rule(grant.rule))
            for grant, name in grant_rows
        ],
        tools=tools,
    )


async def update_connection(
    db: AsyncSession, connection: MCPConnection, update: MCPGatewayConnectionUpdate
) -> None:
    fields = update.model_dump(exclude_unset=True)
    if "slug" in fields and fields["slug"] != connection.gateway_slug:
        slug = fields["slug"]
        if slug is not None:
            taken = await db.scalar(
                select(MCPConnection.id).where(
                    MCPConnection.organization_id == connection.organization_id,
                    MCPConnection.gateway_slug == slug,
                    MCPConnection.id != connection.id,
                )
            )
            if taken is not None:
                raise GatewayConfigError(
                    f"Another connection in this organization already uses the slug '{slug}'",
                    conflict=True,
                )
        connection.gateway_slug = slug
    if "enabled" in fields and fields["enabled"] is not None:
        connection.gateway_enabled = fields["enabled"]
    if connection.gateway_enabled and connection.gateway_slug is None:
        raise GatewayConfigError("Set a slug before enabling the connection on the gateway")
    await db.flush()


async def set_static_headers(
    db: AsyncSession, connection: MCPConnection, headers: dict[str, str] | None
) -> None:
    if headers is None:
        connection.encrypted_static_headers = None
        await db.flush()
        return
    if connection.server.oauth_provider_id is not None:
        raise GatewayConfigError(
            "This server authenticates with OAuth; static headers are only for servers without an OAuth provider"
        )
    if not headers:
        raise GatewayConfigError("Provide at least one header, or null to clear them")
    invalid = sorted(name for name in headers if not _HEADER_NAME.match(name))
    if invalid:
        raise GatewayConfigError(f"Invalid header names: {', '.join(invalid)}")
    connection.encrypted_static_headers = encrypt_secret(json.dumps(headers))
    await db.flush()


async def put_grant(
    db: AsyncSession,
    connection: MCPConnection,
    role_id: UUID,
    rule: MCPGatewayRule,
    granted_by: UUID,
) -> None:
    if await db.scalar(select(Role.id).where(Role.id == role_id)) is None:
        raise GatewayConfigError("Role not found", not_found=True)
    grant = await db.scalar(
        select(MCPGatewayRoleGrant).where(
            MCPGatewayRoleGrant.connection_id == connection.id,
            MCPGatewayRoleGrant.role_id == role_id,
        )
    )
    if grant is None:
        db.add(
            MCPGatewayRoleGrant(
                connection_id=connection.id,
                role_id=role_id,
                rule=_stored_rule(rule),
                granted_by=granted_by,
            )
        )
    else:
        grant.rule = _stored_rule(rule)
        grant.granted_by = granted_by
    await db.flush()


async def delete_grant(db: AsyncSession, connection: MCPConnection, role_id: UUID) -> bool:
    result = await db.execute(
        delete(MCPGatewayRoleGrant).where(
            MCPGatewayRoleGrant.connection_id == connection.id,
            MCPGatewayRoleGrant.role_id == role_id,
        )
    )
    await db.flush()
    return bool(result.rowcount)
