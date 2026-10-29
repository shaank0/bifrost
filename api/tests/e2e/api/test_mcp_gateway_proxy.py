"""E2E: an API-key MCP server served through /mcp/gateway under role grants.

The test runner hosts a real MCP server that requires an ``X-API-Key``
header. Bifrost syncs its catalog with the connection's static headers, and
an org user sees and calls only the tools their role's grant allows.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from uuid import uuid4

import pytest
import uvicorn
from fastmcp import FastMCP

from shared.builtin_roles import USER_ROLE_ID

API_KEY = "e2e-gateway-key"
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def _downstream_app():
    server = FastMCP("tickets")

    @server.tool
    def get_ticket(ticket_id: int) -> str:
        """Get a ticket by id."""
        return f"ticket {ticket_id} is open"

    @server.tool
    def delete_ticket(ticket_id: int) -> str:
        """Delete a ticket."""
        return f"deleted {ticket_id}"

    app = server.http_app(path="/mcp", json_response=True, stateless_http=True)

    async def require_api_key(scope, receive, send):
        if scope["type"] == "http" and dict(scope["headers"]).get(b"x-api-key") != API_KEY.encode():
            await send({"type": "http.response.start", "status": 401, "headers": []})
            await send({"type": "http.response.body", "body": b"missing api key"})
            return
        await app(scope, receive, send)

    require_api_key.lifespan = app.lifespan  # type: ignore[attr-defined]
    return app, require_api_key


@pytest.fixture
def downstream_url() -> Iterator[str]:
    app, guarded = _downstream_app()
    with socket.socket() as probe:
        probe.bind(("0.0.0.0", 0))
        port = probe.getsockname()[1]

    async def lifespan_app(scope, receive, send):
        if scope["type"] == "lifespan":
            await app(scope, receive, send)
        else:
            await guarded(scope, receive, send)

    server = uvicorn.Server(uvicorn.Config(lifespan_app, host="0.0.0.0", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "downstream MCP server did not start"
        time.sleep(0.05)
    host = socket.gethostbyname(socket.gethostname())
    yield f"http://{host}:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def gateway_connection(e2e_client, platform_admin, org1, downstream_url) -> Iterator[dict]:
    admin = platform_admin.headers
    server = e2e_client.post(
        "/api/mcp-servers",
        headers=admin,
        json={"name": f"e2e_gateway_{uuid4().hex[:8]}", "server_url": downstream_url},
    )
    assert server.status_code == 201, server.text
    connection = e2e_client.post(
        "/api/mcp-connections",
        headers=admin,
        json={"server_id": server.json()["id"], "organization_id": org1["id"]},
    )
    assert connection.status_code == 201, connection.text
    yield connection.json()
    e2e_client.delete(f"/api/mcp-connections/{connection.json()['id']}", headers=admin)
    e2e_client.delete(f"/api/mcp-servers/{server.json()['id']}?hard=true", headers=admin)


def _mcp(e2e_client, user, method: str, params: dict) -> dict:
    response = e2e_client.post(
        "/mcp/gateway",
        headers={**user.headers, **MCP_HEADERS},
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def gateway_feature(e2e_client, platform_admin):
    """The MCP Gateway is an optional feature, off by default: on for the test, off after."""
    def switch(on: bool) -> None:
        response = e2e_client.put(
            "/api/settings/features", headers=platform_admin.headers, json={"enabled": {"mcp_gateway": on}}
        )
        assert response.status_code == 200, response.text

    switch(True)
    yield
    switch(False)


@pytest.mark.e2e
def test_org_user_calls_granted_tools_through_the_gateway(
    e2e_client, platform_admin, org1_user, gateway_connection, gateway_feature
) -> None:
    admin = platform_admin.headers
    connection_id = gateway_connection["id"]
    base = f"/api/mcp-gateway/connections/{connection_id}"

    headers = e2e_client.put(f"{base}/static-headers", headers=admin, json={"headers": {"X-API-Key": API_KEY}})
    assert headers.status_code == 200, headers.text
    assert headers.json()["static_header_names"] == ["X-API-Key"]
    refreshed = e2e_client.post(f"/api/mcp-connections/{connection_id}/refresh-tools", headers=admin)
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["total"] == 2

    enabled = e2e_client.patch(base, headers=admin, json={"slug": "tickets", "enabled": True})
    assert enabled.status_code == 200, enabled.text
    granted = e2e_client.put(
        f"{base}/grants/{USER_ROLE_ID}", headers=admin, json={"rule": {"categories": ["read"]}}
    )
    assert granted.status_code == 200, granted.text
    preview = {tool["tool_name"]: tool["granted_role_ids"] for tool in granted.json()["tools"]}
    assert preview == {"delete_ticket": [], "get_ticket": [str(USER_ROLE_ID)]}

    listed = _mcp(e2e_client, org1_user, "tools/list", {})
    assert [tool["name"] for tool in listed["result"]["tools"]] == ["tickets__get_ticket"]
    served = listed["result"]["tools"][0]
    assert served["description"] == "Get a ticket by id."
    assert served["inputSchema"]["properties"]["ticket_id"]["type"] == "integer"
    mine = e2e_client.get("/api/mcp-gateway/me/tools", headers=org1_user.headers)
    assert [tool["name"] for tool in mine.json()] == ["tickets__get_ticket"]

    called = _mcp(
        e2e_client, org1_user, "tools/call", {"name": "tickets__get_ticket", "arguments": {"ticket_id": 7}}
    )
    assert not called["result"].get("isError"), called
    assert "ticket 7 is open" in called["result"]["content"][0]["text"]

    denied = _mcp(
        e2e_client, org1_user, "tools/call", {"name": "tickets__delete_ticket", "arguments": {"ticket_id": 7}}
    )
    assert denied["result"]["isError"], denied
    assert "not available" in denied["result"]["content"][0]["text"]

    audit = e2e_client.get(
        "/api/audit", headers=admin, params={"action": "mcp_gateway.tool_call"}
    )
    assert audit.status_code == 200, audit.text
    outcomes = sorted(
        row["outcome"] for row in audit.json()["entries"] if row["resource_id"] == connection_id
    )
    assert outcomes == ["failure", "success"]


@pytest.mark.e2e
def test_oauth_server_connections_still_require_client_credentials(
    e2e_client, platform_admin, org1
) -> None:
    admin = platform_admin.headers
    server = e2e_client.post(
        "/api/mcp-servers",
        headers=admin,
        json={
            "name": f"e2e_gateway_oauth_{uuid4().hex[:8]}",
            "server_url": "https://example.invalid/mcp",
            "oauth_provider": {
                "oauth_flow_type": "client_credentials",
                "token_url": "https://example.invalid/token",
            },
        },
    )
    assert server.status_code == 201, server.text
    try:
        response = e2e_client.post(
            "/api/mcp-connections",
            headers=admin,
            json={"server_id": server.json()["id"], "organization_id": org1["id"]},
        )
        assert response.status_code == 422, response.text
    finally:
        e2e_client.delete(f"/api/mcp-servers/{server.json()['id']}?hard=true", headers=admin)
