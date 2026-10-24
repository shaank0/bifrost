"""MCP connection tools: store the vendor's tool description

Revision ID: 20261024_mcp_tool_description
Revises: 20261023_mcp_gateway
Create Date: 2026-10-24

Catalog sync stored only the tool's input schema, so agents and the MCP
gateway described every external tool by its name alone. Rows fill in on
the next catalog refresh.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261024_mcp_tool_description"
down_revision: Union[str, None] = "20261023_mcp_gateway"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "mcp_connection_tools",
        sa.Column("description", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mcp_connection_tools", "description")
