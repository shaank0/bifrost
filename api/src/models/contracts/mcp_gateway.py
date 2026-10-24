"""MCP gateway contract models.

The gateway serves a connection's tools directly on ``/mcp/gateway`` as
``{slug}__{tool_name}``. These models configure that exposure per connection,
the role grants that decide who sees which tools, and the write-only static
headers used by servers with no OAuth provider.
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

GatewayCategory = Literal["read", "create", "modify", "delete"]
ToolCategory = Literal["read", "create", "modify", "delete", "dangerous"]

GATEWAY_SLUG_PATTERN = r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$"


class MCPGatewayCategoryRule(BaseModel):
    """Serve tools whose category is listed, plus ``allow``, minus ``deny``.

    Dangerous tools (raw requests, generic executors) belong to no category
    and are served only when named in ``allow``.
    """

    categories: list[GatewayCategory] = Field(default_factory=list)
    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)


# None = every tool; a list = exactly those tool names; or a category rule.
MCPGatewayRule = MCPGatewayCategoryRule | list[str] | None


class MCPGatewayConnectionUpdate(BaseModel):
    enabled: bool | None = Field(
        default=None, description="Serve this connection's tools on /mcp/gateway"
    )
    slug: str | None = Field(
        default=None,
        pattern=GATEWAY_SLUG_PATTERN,
        description="Tool-name prefix on the gateway, e.g. 'autotask' → autotask__search_tickets",
    )


class MCPGatewayStaticHeadersUpdate(BaseModel):
    headers: dict[str, str] | None = Field(
        default=None,
        description=(
            "HTTP headers sent on every call to a server with no OAuth provider, "
            "e.g. an API key. Stored encrypted and never returned. Null clears them."
        ),
    )


class MCPGatewayGrantUpdate(BaseModel):
    rule: MCPGatewayRule = Field(
        default=None,
        description="Null = every tool; a list of tool names; or a category rule",
    )


class MCPGatewayGrantPublic(BaseModel):
    role_id: UUID
    role_name: str
    rule: MCPGatewayRule


class MCPGatewayToolPublic(BaseModel):
    tool_name: str
    gateway_name: str | None = Field(
        description="Name served on /mcp/gateway; null until the connection has a slug"
    )
    category: ToolCategory
    enabled: bool
    granted_role_ids: list[UUID] = Field(
        description="Roles whose grant serves this tool"
    )


class MCPGatewayConnectionPublic(BaseModel):
    connection_id: UUID
    organization_id: UUID
    enabled: bool
    slug: str | None
    static_header_names: list[str] = Field(
        description="Names of the configured static headers; values are never returned"
    )
    grants: list[MCPGatewayGrantPublic]
    tools: list[MCPGatewayToolPublic]


class MCPGatewayMyTool(BaseModel):
    name: str
    connection_id: UUID
    tool_name: str
    category: ToolCategory
    description: str
