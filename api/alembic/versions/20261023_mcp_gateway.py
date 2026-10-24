"""MCP gateway: connection exposure, static headers, role grants

Revision ID: 20261023_mcp_gateway
Revises: 20261023_worker_memory_pressure
Create Date: 2026-10-23

A connection can be served on /mcp/gateway under a per-org slug, and a
connection to a server with no OAuth provider can carry encrypted static
headers. Role grants decide which tools each role sees on the gateway.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261023_mcp_gateway"
down_revision: Union[str, None] = "20261023_worker_memory_pressure"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "mcp_connections",
        sa.Column("encrypted_static_headers", sa.Text(), nullable=True),
    )
    op.add_column(
        "mcp_connections",
        sa.Column("gateway_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "mcp_connections",
        sa.Column("gateway_slug", sa.String(length=40), nullable=True),
    )
    op.create_index(
        "ix_mcp_connections_unique_gateway_slug",
        "mcp_connections",
        ["organization_id", "gateway_slug"],
        unique=True,
        postgresql_where=sa.text("gateway_slug IS NOT NULL"),
    )

    op.create_table(
        "mcp_gateway_role_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("rule", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("granted_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["mcp_connections.id"], ondelete="CASCADE", onupdate="CASCADE"
        ),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mcp_gateway_role_grants_role_id", "mcp_gateway_role_grants", ["role_id"])
    op.create_index(
        "ix_mcp_gateway_role_grants_unique",
        "mcp_gateway_role_grants",
        ["connection_id", "role_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_mcp_gateway_role_grants_unique", table_name="mcp_gateway_role_grants")
    op.drop_index("ix_mcp_gateway_role_grants_role_id", table_name="mcp_gateway_role_grants")
    op.drop_table("mcp_gateway_role_grants")
    op.drop_index("ix_mcp_connections_unique_gateway_slug", table_name="mcp_connections")
    op.drop_column("mcp_connections", "gateway_slug")
    op.drop_column("mcp_connections", "gateway_enabled")
    op.drop_column("mcp_connections", "encrypted_static_headers")
