"""MCP SDK adapter for the ``/mcp/gateway`` proxy surface.

Translates between the MCP SDK's tool objects and the connection-backed tools
served by ``src.services.mcp_gateway.service``. The tool list is built per
request from the caller's current role grants; nothing is registered on the
SDK server itself.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import CallToolResult, ContentBlock, Tool, ToolAnnotations
from pydantic import TypeAdapter

from src.core.database import get_db_context
from src.services.mcp_gateway.service import (
    GatewayCallError,
    GatewayTool,
    call_gateway_tool,
    list_gateway_tools,
)
from src.services.mcp_server.authorization import load_mcp_caller
from src.services.mcp_server.server import _get_context_from_token

_content_blocks = TypeAdapter(list[ContentBlock])


def _to_mcp_tool(tool: GatewayTool) -> Tool:
    return Tool(
        name=tool.name,
        description=tool.description,
        inputSchema=tool.input_schema,
        annotations=ToolAnnotations(
            readOnlyHint=tool.category == "read",
            destructiveHint=tool.category in ("delete", "dangerous"),
        ),
    )


async def list_proxy_tools() -> list[Tool]:
    async with get_db_context() as db:
        caller = await load_mcp_caller(db, _get_context_from_token())
        return [_to_mcp_tool(tool) for tool in await list_gateway_tools(db, caller)]


def _envelope_text(envelope: dict[str, Any]) -> str:
    texts = [
        block.get("text", "")
        for block in envelope.get("content") or []
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return "\n".join(text for text in texts if text) or "The tool reported an error"


async def call_proxy_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
    """Call a gateway tool, keeping the remote server's content and structured content as they are.
    A failure raises ToolError, which the SDK reports as an error result."""
    async with get_db_context() as db:
        caller = await load_mcp_caller(db, _get_context_from_token())
        try:
            envelope = await call_gateway_tool(db, caller, name, arguments)
        except GatewayCallError as exc:
            # Keep the failure's audit row: the context rolls back on raise.
            await db.commit()
            raise ToolError(exc.message) from exc
    if envelope.get("is_error"):
        raise ToolError(_envelope_text(envelope))
    structured = envelope.get("structured_content")
    return CallToolResult(
        content=_content_blocks.validate_python(envelope.get("content") or []),
        structuredContent=structured if isinstance(structured, dict) else None,
    )
