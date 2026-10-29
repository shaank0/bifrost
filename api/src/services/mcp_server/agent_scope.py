"""
ASGI middleware that extracts agent_id from /mcp/{agent_id} paths.

Intercepts requests to /mcp/{uuid}, stores the agent_id in the ASGI scope
as scope["mcp_agent_id"], and rewrites the path to /mcp so FastMCP's
route matcher works. Requests to /mcp/gateway are marked with
scope["mcp_gateway"] and rewritten the same way. Other paths (including
/mcp/callback) pass through.
"""

import contextvars
import re
from uuid import UUID

_REQUEST_SCOPE: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "mcp_request_scope", default=None
)

# Match /mcp/{uuid} but not /mcp/callback or other non-UUID suffixes
_AGENT_PATH_RE = re.compile(
    r"^(/mcp)/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(/.*)?$",
    re.IGNORECASE,
)


_GATEWAY_PATH_RE = re.compile(r"^(/mcp)/gateway(/.*)?$")


def is_gateway_request() -> bool:
    """Whether the current MCP request came in on /mcp/gateway."""
    scope = _REQUEST_SCOPE.get()
    return bool(scope and scope.get("mcp_gateway"))


def get_scoped_agent_id() -> UUID | None:
    """Read the agent UUID written to the current MCP HTTP request scope."""
    try:
        scope = _REQUEST_SCOPE.get()
        agent_id = None if scope is None else scope.get("mcp_agent_id")
        return UUID(agent_id) if agent_id else None
    except (RuntimeError, ValueError, AttributeError):
        # No HTTP context, malformed UUID, or an unexpected scope shape.
        return None


class AgentScopeMCPMiddleware:
    """ASGI middleware that rewrites /mcp/{agent_id} to /mcp."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        scope_token = None
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "")
            match = _AGENT_PATH_RE.match(path)
            gateway_match = _GATEWAY_PATH_RE.match(path)
            if match:
                scope["mcp_agent_id"] = match.group(2)
                # Rewrite path to /mcp (preserving any trailing path like /mcp/sse)
                scope["path"] = match.group(1) + (match.group(3) or "")
            elif gateway_match:
                scope["mcp_gateway"] = True
                scope["path"] = gateway_match.group(1) + (gateway_match.group(2) or "")
            scope_token = _REQUEST_SCOPE.set(scope)
        try:
            await self.app(scope, receive, send)
        finally:
            if scope_token is not None:
                _REQUEST_SCOPE.reset(scope_token)
