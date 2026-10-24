"""Gateway grant rules: fail-closed parsing, category rules, union across roles."""

from uuid import uuid4

import pytest

from src.core.constants import PROVIDER_ORG_ID
from src.services.authorization.context import (
    AuthorizationContext,
    Boundary,
    BoundaryKind,
    RoleGrant,
)
from src.services.mcp_gateway.access import (
    ToolRule,
    is_tool_allowed,
    is_tool_allowed_for_any,
    parse_rule,
    roles_in_organization,
)


@pytest.mark.parametrize("raw", ["read", 7, {"allow": ["x"]}, {"categories": "read"}])
def test_unrecognized_rules_grant_nothing(raw) -> None:
    assert parse_rule(raw) == frozenset()
    assert not is_tool_allowed("get_ticket", parse_rule(raw))


def test_null_rule_serves_every_tool() -> None:
    assert is_tool_allowed("autotask_raw_request", parse_rule(None))


def test_list_rule_serves_exactly_the_named_tools() -> None:
    access = parse_rule(["get_ticket", 3])
    assert access == frozenset({"get_ticket"})
    assert is_tool_allowed("get_ticket", access)
    assert not is_tool_allowed("list_tickets", access)


def test_category_rule_drops_unknown_categories() -> None:
    assert parse_rule({"categories": ["read", "dangerous", "admin"]}) == ToolRule(
        categories=frozenset({"read"})
    )


def test_category_rule_applies_categories_allow_and_deny() -> None:
    access = parse_rule(
        {"categories": ["read"], "allow": ["create_ticket"], "deny": ["list_secrets"]}
    )
    assert is_tool_allowed("get_ticket", access)
    assert is_tool_allowed("create_ticket", access)
    assert not is_tool_allowed("list_secrets", access)
    assert not is_tool_allowed("update_ticket", access)


def test_dangerous_tools_need_an_explicit_allow() -> None:
    every_category = {"categories": ["read", "create", "modify", "delete"]}
    assert not is_tool_allowed("raw_request", parse_rule(every_category))
    assert is_tool_allowed("raw_request", parse_rule({**every_category, "allow": ["raw_request"]}))


def test_access_is_the_union_across_roles() -> None:
    read_only = {"categories": ["read"], "deny": ["get_salary"]}
    payroll = ["get_salary"]
    assert is_tool_allowed_for_any("get_salary", [read_only, payroll])
    assert not is_tool_allowed_for_any("update_salary", [read_only, payroll])
    assert not is_tool_allowed_for_any("get_salary", [])


def _ctx(home, role_grants=()) -> AuthorizationContext:
    return AuthorizationContext(
        user_id=uuid4(),
        home_organization_id=home,
        base_role_id=uuid4(),
        is_external=False,
        base_permissions=frozenset(),
        role_grants=tuple(role_grants),
    )


def test_roles_in_organization_follow_boundaries() -> None:
    home, other = uuid4(), uuid4()
    org_role, managed_role, platform_role = uuid4(), uuid4(), uuid4()
    ctx = _ctx(
        home,
        [
            RoleGrant(org_role, frozenset(), (Boundary(BoundaryKind.ORGANIZATION, other),)),
            RoleGrant(managed_role, frozenset(), (Boundary(BoundaryKind.MANAGED_ORGANIZATIONS),)),
            RoleGrant(platform_role, frozenset(), (Boundary(BoundaryKind.PLATFORM),)),
        ],
    )
    assert roles_in_organization(ctx, home) == {ctx.base_role_id, managed_role, platform_role}
    assert roles_in_organization(ctx, other) == {org_role, managed_role, platform_role}
    assert roles_in_organization(ctx, PROVIDER_ORG_ID) == {platform_role}
