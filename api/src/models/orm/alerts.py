"""Failure alerts: unattended work that broke and needs someone to look.

One row per occurrence streak of a subject (a workflow, or an integration's
connection for one organization). While a row is open or acknowledged, further
failures of the same subject add to it; the subject's next success resolves it,
and a later failure opens a new row.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.orm.base import Base

if TYPE_CHECKING:
    from src.models.orm.organizations import Organization


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        # At most one unresolved alert per subject.
        Index(
            "uq_alerts_active_subject",
            "subject_key",
            unique=True,
            postgresql_where=text("status <> 'resolved'"),
        ),
        Index("ix_alerts_status_last_seen", "status", "last_seen_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # workflow_failed | integration_refresh_failed
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(200), nullable=False)
    # open | acknowledged | resolved
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", server_default="open")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    workflow_id: Mapped[UUID | None] = mapped_column(nullable=True, default=None)
    integration_id: Mapped[UUID | None] = mapped_column(nullable=True, default=None)
    last_execution_id: Mapped[UUID | None] = mapped_column(nullable=True, default=None)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, server_default=text("NOW()")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, server_default=text("NOW()")
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    acknowledged_by: Mapped[str | None] = mapped_column(String(320), nullable=True, default=None)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    # When the alert email went out; None when email is off or not sent yet.
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)

    organization: Mapped["Organization | None"] = relationship("Organization")
