"""Serve external MCP connections' tools directly on ``/mcp/gateway``.

Each gateway-enabled connection in the caller's home organization contributes
its enabled catalog tools as ``{gateway_slug}__{tool_name}``. A caller sees a
tool only when one of their roles in that organization holds a grant whose
rule allows it — platform admins included; there is no bypass.

A call re-runs the same checks against current rows before anything else
happens, in this order: resolve the namespaced name, check the grant, apply
the per-user rate limit, then dispatch (which resolves credentials). Every
call — allowed, denied, or failed — writes an audit row.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.rate_limit import RateLimiter
from src.models.orm.external_mcp import (
    MCPConnection,
    MCPConnectionTool,
    MCPGatewayRoleGrant,
    MCPServer,
)
from src.services.audit import emit_audit
from src.services.audit_context import ActorContext
from src.services.authorization.enforce import Caller
from src.services.mcp_client import dispatch as mcp_dispatch
from src.services.mcp_client.errors import (
    MisconfigError,
    NeedsReauthError,
    ToolDispatchError,
)
from src.services.mcp_gateway.access import (
    is_tool_allowed_for_any,
    roles_in_organization,
)
from src.services.mcp_gateway.classifier import ToolCategory, classify_tool

logger = logging.getLogger(__name__)

TOOL_SEPARATOR = "__"
GATEWAY_CALLS_PER_MINUTE = 120

_rate_limiter = RateLimiter(max_requests=GATEWAY_CALLS_PER_MINUTE, window_seconds=60)


class GatewayCallError(Exception):
    """A gateway call that failed before or during dispatch.

    ``code`` is one of ``not_found`` (unknown or not granted — the two are
    indistinguishable to the caller), ``rate_limited``, ``needs_reauth``,
    ``misconfigured``, or ``dispatch_failed``.
    """

    def __init__(self, code: str, message: str, connection_id: UUID | None = None) -> None:
        self.code = code
        self.message = message
        self.connection_id = connection_id
        super().__init__(message)


@dataclass(frozen=True)
class GatewayTool:
    name: str
    connection_id: UUID
    tool_name: str
    category: ToolCategory
    description: str
    input_schema: dict[str, Any]


def gateway_tool_name(slug: str, tool_name: str) -> str:
    return f"{slug}{TOOL_SEPARATOR}{tool_name}"


def split_gateway_tool_name(name: str) -> tuple[str, str] | None:
    """Split on the FIRST separator; slugs never contain one."""
    slug, separator, tool_name = name.partition(TOOL_SEPARATOR)
    if not separator or not slug or not tool_name:
        return None
    return slug, tool_name


def _to_gateway_tool(slug: str, row: MCPConnectionTool) -> GatewayTool:
    return GatewayTool(
        name=gateway_tool_name(slug, row.tool_name),
        connection_id=row.connection_id,
        tool_name=row.tool_name,
        category=classify_tool(row.tool_name),
        # Catalog rows hold the canonical descriptor: {inputSchema, description?, outputSchema?}.
        description=(row.tool_schema or {}).get("description") or row.tool_name,
        input_schema=(row.tool_schema or {}).get("inputSchema") or {"type": "object", "properties": {}},
    )


def _gateway_organization(caller: Caller) -> UUID | None:
    return None if caller.ctx is None else caller.ctx.home_organization_id


async def _grant_rules(
    db: AsyncSession, caller: Caller, organization_id: UUID, connection_ids: Sequence[UUID]
) -> dict[UUID, list[Any]]:
    """Rules of the caller's roles in ``organization_id``, per connection."""
    assert caller.ctx is not None
    role_ids = roles_in_organization(caller.ctx, organization_id)
    if not role_ids or not connection_ids:
        return {}
    rows = await db.execute(
        select(MCPGatewayRoleGrant.connection_id, MCPGatewayRoleGrant.rule).where(
            MCPGatewayRoleGrant.connection_id.in_(connection_ids),
            MCPGatewayRoleGrant.role_id.in_(role_ids),
        )
    )
    rules: dict[UUID, list[Any]] = {}
    for connection_id, rule in rows:
        rules.setdefault(connection_id, []).append(rule)
    return rules


def _served(rules: list[Any] | None, tool_name: str) -> bool:
    return bool(rules) and is_tool_allowed_for_any(tool_name, rules)


async def list_gateway_tools(db: AsyncSession, caller: Caller) -> list[GatewayTool]:
    """Every gateway tool the caller may see, ordered by name."""
    organization_id = _gateway_organization(caller)
    if organization_id is None:
        return []
    connections = (
        await db.execute(
            select(MCPConnection)
            .where(
                MCPConnection.organization_id == organization_id,
                MCPConnection.gateway_enabled.is_(True),
                MCPConnection.gateway_slug.is_not(None),
            )
            .options(selectinload(MCPConnection.tools))
        )
    ).scalars().all()
    rules = await _grant_rules(db, caller, organization_id, [c.id for c in connections])

    tools: list[GatewayTool] = []
    for connection in connections:
        assert connection.gateway_slug is not None
        connection_rules = rules.get(connection.id)
        for row in connection.tools:
            if row.enabled and _served(connection_rules, row.tool_name):
                tools.append(_to_gateway_tool(connection.gateway_slug, row))
    return sorted(tools, key=lambda tool: tool.name)


async def _resolve_call_target(
    db: AsyncSession, caller: Caller, name: str
) -> tuple[MCPConnection, MCPConnectionTool]:
    """Load the connection and catalog row for ``name`` if the caller may call it."""
    not_found = GatewayCallError("not_found", f"Tool '{name}' is not available on this gateway")
    organization_id = _gateway_organization(caller)
    parts = split_gateway_tool_name(name)
    if organization_id is None or parts is None:
        raise not_found
    slug, tool_name = parts
    connection = (
        await db.execute(
            select(MCPConnection)
            .where(
                MCPConnection.organization_id == organization_id,
                MCPConnection.gateway_enabled.is_(True),
                MCPConnection.gateway_slug == slug,
            )
            .options(
                selectinload(MCPConnection.service_oauth_token),
                selectinload(MCPConnection.server).selectinload(MCPServer.oauth_provider),
            )
        )
    ).scalar_one_or_none()
    if connection is None:
        raise not_found
    # Past this point a denial still names the connection in the audit row.
    not_found.connection_id = connection.id
    row = (
        await db.execute(
            select(MCPConnectionTool).where(
                MCPConnectionTool.connection_id == connection.id,
                MCPConnectionTool.tool_name == tool_name,
            )
        )
    ).scalar_one_or_none()
    if row is None or not row.enabled:
        raise not_found
    rules = await _grant_rules(db, caller, organization_id, [connection.id])
    if not _served(rules.get(connection.id), tool_name):
        raise not_found
    return connection, row


def _audit_actor(caller: Caller) -> ActorContext:
    principal = caller.principal
    return ActorContext(
        user_id=principal.user_id,
        organization_id=principal.organization_id,
        email=principal.email,
        name=principal.name,
        source="http",
        surface="mcp",
    )


async def call_gateway_tool(
    db: AsyncSession,
    caller: Caller,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Check, rate-limit, dispatch, and audit one gateway tool call.

    Returns the normalized dispatch envelope (``content``,
    ``structured_content``, ``is_error``). Raises ``GatewayCallError``.
    """
    started = time.monotonic()
    details: dict[str, Any] = {"tool": name}
    parts = split_gateway_tool_name(name)
    if parts is not None:
        details["category"] = classify_tool(parts[1])
    connection_id: UUID | None = None
    try:
        connection, row = await _resolve_call_target(db, caller, name)
        connection_id = connection.id
        try:
            await _rate_limiter.check("mcp_gateway", str(caller.principal.user_id))
        except HTTPException as exc:
            raise GatewayCallError(
                "rate_limited",
                f"Rate limit of {GATEWAY_CALLS_PER_MINUTE} gateway calls per minute exceeded",
            ) from exc
        try:
            envelope = await mcp_dispatch.invoke(
                connection,
                row.tool_name,
                arguments,
                caller_user_id=caller.principal.user_id,
                db=db,
            )
        except NeedsReauthError as exc:
            raise GatewayCallError(
                "needs_reauth",
                f"Connect your account for this tool first: {exc.reauth_url}",
            ) from exc
        except MisconfigError as exc:
            raise GatewayCallError("misconfigured", exc.reason) from exc
        except ToolDispatchError as exc:
            raise GatewayCallError("dispatch_failed", str(exc)) from exc
    except GatewayCallError as exc:
        details.update(error_code=exc.code, duration_ms=_elapsed_ms(started))
        await emit_audit(
            db,
            "mcp_gateway.tool_call",
            resource_type="mcp_connection",
            resource_id=connection_id or exc.connection_id,
            outcome="failure",
            details=details,
            actor_override=_audit_actor(caller),
        )
        raise

    details.update(
        resolution_path=envelope.pop("_resolution_path", None),
        is_error=envelope.get("is_error", False),
        duration_ms=_elapsed_ms(started),
    )
    await emit_audit(
        db,
        "mcp_gateway.tool_call",
        resource_type="mcp_connection",
        resource_id=connection_id,
        outcome="success",
        details=details,
        actor_override=_audit_actor(caller),
    )
    return envelope


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
