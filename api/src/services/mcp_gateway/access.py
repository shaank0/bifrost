"""Role-based tool access for the MCP gateway.

A grant row (``mcp_gateway_role_grants``) gives one role access to one
connection's tools. Its ``rule`` is one of:

- ``None``: every tool on the connection.
- ``list[str]``: exactly these tool names.
- ``{"categories": [...], "allow": [...], "deny": [...]}``: a tool is served
  iff ``(classify(tool) in categories OR tool in allow) AND tool not in deny``.
  Dangerous tools match no category — only ``allow`` serves them.

Anything else parses as an empty explicit list, so a corrupt row can only
ever narrow access. Across a caller's roles, access is the UNION: one role's
``deny`` never vetoes another role's ``allow``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from src.core.constants import PROVIDER_ORG_ID
from src.services.authorization.context import AuthorizationContext, BoundaryKind
from src.services.mcp_gateway.classifier import GRANTABLE_CATEGORIES, classify_tool


@dataclass(frozen=True)
class ToolRule:
    categories: frozenset[str] = field(default_factory=frozenset)
    allow: frozenset[str] = field(default_factory=frozenset)
    deny: frozenset[str] = field(default_factory=frozenset)


# None = all tools; frozenset = explicit list; ToolRule = category rule.
ToolAccess = frozenset[str] | ToolRule | None


def _strings(value: Any) -> frozenset[str]:
    if not isinstance(value, list):
        return frozenset()
    return frozenset(item for item in value if isinstance(item, str))


def parse_rule(raw: Any) -> ToolAccess:
    """Parse a stored grant rule, failing closed on anything unrecognized."""
    if raw is None:
        return None
    if isinstance(raw, list):
        return _strings(raw)
    if isinstance(raw, Mapping) and isinstance(raw.get("categories"), list):
        return ToolRule(
            categories=_strings(raw["categories"]) & frozenset(GRANTABLE_CATEGORIES),
            allow=_strings(raw.get("allow")),
            deny=_strings(raw.get("deny")),
        )
    return frozenset()


def is_tool_allowed(tool_name: str, access: ToolAccess) -> bool:
    """Evaluate one parsed rule against one original (un-prefixed) tool name."""
    if access is None:
        return True
    if isinstance(access, frozenset):
        return tool_name in access
    if tool_name in access.deny:
        return False
    if tool_name in access.allow:
        return True
    category = classify_tool(tool_name)
    if category == "dangerous":
        return False
    return category in access.categories


def is_tool_allowed_for_any(tool_name: str, rules: Iterable[Any]) -> bool:
    """Union across roles: served if at least one role's rule allows it."""
    return any(is_tool_allowed(tool_name, parse_rule(rule)) for rule in rules)


def roles_in_organization(ctx: AuthorizationContext, organization_id: UUID) -> frozenset[UUID]:
    """Roles the person holds that apply in ``organization_id``.

    The base role applies at the person's home org. Additional roles apply
    where their boundaries cover the org: an exact ``organization`` boundary,
    ``managed_organizations`` for any org other than the provider org, or a
    ``platform`` boundary, which covers every org. A role still serves tools
    only through a gateway grant naming it; holding it is not a bypass.
    """
    roles: set[UUID] = set()
    if ctx.home_organization_id == organization_id:
        roles.add(ctx.base_role_id)
    for grant in ctx.role_grants:
        for boundary in grant.boundaries:
            if (
                boundary.kind == BoundaryKind.ORGANIZATION
                and boundary.organization_id == organization_id
            ) or (
                boundary.kind == BoundaryKind.MANAGED_ORGANIZATIONS
                and organization_id != PROVIDER_ORG_ID
            ) or boundary.kind == BoundaryKind.PLATFORM:
                roles.add(grant.role_id)
                break
    return frozenset(roles)
