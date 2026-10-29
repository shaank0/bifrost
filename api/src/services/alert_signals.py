"""Which built-in platform events open or resolve a failure alert.

An alert stands for one thing that is broken and that nobody is watching: an
unattended workflow (started by a schedule, webhook or topic event) that failed
after its last retry, or an integration connection that can no longer refresh
its token without someone reconnecting it. Runs a person started show their
failure to that person, so they never alert.

One alert exists per subject at a time. Repeated failures add to it; the next
success resolves it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

AlertKind = Literal["workflow_failed", "integration_refresh_failed"]

# Long enough for a useful error line, short enough for a list row and an email subject.
MAX_DETAIL_CHARS = 2000


@dataclass(frozen=True)
class AlertSignal:
    action: Literal["open", "resolve"]
    kind: AlertKind
    # Identifies the broken thing across occurrences, e.g. "workflow:<id>".
    subject_key: str
    organization_id: str | None
    title: str = ""
    detail: str = ""
    workflow_id: str | None = None
    integration_id: str | None = None
    execution_id: str | None = None


def _org_id(body: dict[str, Any]) -> str | None:
    return (body.get("organization") or {}).get("id")


def _workflow_signal(topic: str, body: dict[str, Any]) -> AlertSignal | None:
    workflow = body.get("workflow") or {}
    workflow_id = workflow.get("id")
    if not workflow_id or (body.get("trigger") or {}).get("type") != "event":
        return None
    name = workflow.get("name") or "A workflow"
    common = {
        "kind": "workflow_failed",
        "subject_key": f"workflow:{workflow_id}",
        "organization_id": _org_id(body),
        "workflow_id": str(workflow_id),
        "execution_id": (body.get("execution") or {}).get("id"),
    }
    if topic == "workflow.completed":
        return AlertSignal(action="resolve", **common)
    error = body.get("error") or {}
    message = (error.get("message") or "").strip()
    detail = f"{error.get('type') or 'Error'}: {message}" if message else (error.get("type") or "Failed")
    return AlertSignal(
        action="open",
        title=f"{name} failed",
        detail=detail[:MAX_DETAIL_CHARS],
        **common,
    )


def _integration_signal(topic: str, body: dict[str, Any]) -> AlertSignal | None:
    integration = body.get("integration") or {}
    integration_id = integration.get("id")
    if not integration_id:
        return None
    org_id = _org_id(body)
    common = {
        "kind": "integration_refresh_failed",
        # One connection per integration and organization.
        "subject_key": f"integration:{integration_id}:{org_id or 'global'}",
        "organization_id": org_id,
        "integration_id": str(integration_id),
    }
    if topic in ("integration.refresh_recovered", "integration.connected"):
        return AlertSignal(action="resolve", **common)
    error = body.get("error") or {}
    if error.get("retryable"):
        return None  # the refresh job tries again on its own
    name = integration.get("name") or "An integration"
    org_name = (body.get("organization") or {}).get("name")
    return AlertSignal(
        action="open",
        title=f"{name} needs reconnecting" + (f" for {org_name}" if org_name else ""),
        detail=(error.get("message") or "Token refresh failed.")[:MAX_DETAIL_CHARS],
        **common,
    )


def signal_from_event(topic: str, body: dict[str, Any]) -> AlertSignal | None:
    """The alert change a built-in event implies, or None.

    ``workflow.retry_exhausted`` (not ``workflow.failed``) opens an alert, so a
    failure that a retry later fixes never alerts.
    """
    if topic in ("workflow.retry_exhausted", "workflow.completed"):
        return _workflow_signal(topic, body)
    if topic in ("integration.refresh_failed", "integration.refresh_recovered", "integration.connected"):
        return _integration_signal(topic, body)
    return None
