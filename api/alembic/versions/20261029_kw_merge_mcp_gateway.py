"""Join the MCP gateway migrations to main, and move tool descriptions into the canonical descriptor.

Revision ID: 20261029_kw_merge_mcp_gateway
Revises: 20261025_remote_worker_ownership, 20261024_mcp_tool_description
Create Date: 2026-10-29

The MCP gateway branch (20261023_mcp_gateway, 20261024_mcp_tool_description)
was applied to KW's production database before main's later migrations. This
revision merges the two lines so both apply in either order.

20261024_mcp_tool_description stored each external tool's description in its
own ``mcp_connection_tools.description`` column. Main's
20261023_mcp_tool_descriptors settled on keeping it inside the canonical
``tool_schema`` descriptor instead, which is what the code now reads. Copy any
description the descriptor lacks, then drop the column.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261029_kw_merge_mcp_gateway"
down_revision: tuple[str, str] = ("20261025_remote_worker_ownership", "20261024_mcp_tool_description")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE mcp_connection_tools
            SET tool_schema = tool_schema || jsonb_build_object('description', description)
            WHERE description IS NOT NULL
              AND jsonb_typeof(tool_schema) = 'object'
              AND NOT tool_schema ? 'description'
            """
        )
    )
    op.drop_column("mcp_connection_tools", "description")


def downgrade() -> None:
    op.add_column("mcp_connection_tools", sa.Column("description", sa.Text(), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE mcp_connection_tools
            SET description = tool_schema ->> 'description'
            WHERE jsonb_typeof(tool_schema) = 'object'
            """
        )
    )
