"""Tool classifier parity with the MCP_Gateway classifier.

The corpus fixtures are every tool name served by production backends and the
subset a human reviewed as genuine reads. A ``{"categories": ["read"]}`` grant
serves exactly the read set, so a classifier change that alters it must fail
here until the read list is re-reviewed by hand.
"""

import json
from pathlib import Path

import pytest

from src.services.mcp_gateway.classifier import classify_tool, tokenize_tool_name

FIXTURES = Path(__file__).parent / "fixtures"
ALL_TOOLS: dict[str, list[str]] = json.loads((FIXTURES / "production_tool_names.json").read_text())
REVIEWED_READS: dict[str, list[str]] = json.loads((FIXTURES / "production_read_tools.json").read_text())


@pytest.mark.parametrize("backend", sorted(ALL_TOOLS))
def test_corpus_read_set_matches_reviewed_list(backend: str) -> None:
    classified = [name for name in ALL_TOOLS[backend] if classify_tool(name) == "read"]
    assert classified == REVIEWED_READS.get(backend, [])


@pytest.mark.parametrize(
    ("name", "category"),
    [
        ("autotask_get_ticket_details", "read"),
        ("datto_list_devices", "read"),
        ("hudu_test_connection", "read"),
        ("autotask_create_ticket", "create"),
        ("autotask_delete_service_call", "delete"),
        ("hudu_archive_company", "delete"),
        ("autotask_update_ticket", "modify"),
        ("hudu_unarchive_company", "modify"),
        ("frobnicate_widget", "modify"),
        ("autotask_raw_request", "dangerous"),
        ("autotask_execute_tool", "dangerous"),
        ("datto_run_quickjob", "dangerous"),
        ("autotask_router", "dangerous"),
        ("update-sharepoint-list-item", "modify"),
        ("send_test_email", "modify"),
        ("get_create_templates", "read"),
        ("Autotask_Create_Ticket", "create"),
        ("ExecTool", "dangerous"),
        ("ListGraphRequest", "dangerous"),
        ("raw_query", "dangerous"),
        ("GetDoc", "read"),
        ("constructor", "modify"),
        ("getter_widget", "modify"),
    ],
)
def test_classify_tool(name: str, category: str) -> None:
    assert classify_tool(name) == category


@pytest.mark.parametrize(
    ("name", "tokens"),
    [
        ("ExecTool", ["exec", "tool"]),
        ("ListGraphRequest", ["list", "graph", "request"]),
        ("XMLParser_get", ["xml", "parser", "get"]),
        ("autotask__raw_request", ["autotask", "raw", "request"]),
    ],
)
def test_tokenize_tool_name(name: str, tokens: list[str]) -> None:
    assert tokenize_tool_name(name) == tokens
