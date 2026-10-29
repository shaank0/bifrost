"""Which built-in events open or resolve a failure alert."""

from src.services.alert_signals import MAX_DETAIL_CHARS, signal_from_event

ORG = {"id": "org-1", "name": "Acme"}
EVENT_TRIGGER = {"type": "event", "event_type": "schedule", "event_id": "ev-1"}


def _workflow_body(trigger=EVENT_TRIGGER, **error) -> dict:
    return {
        "organization": ORG,
        "workflow": {"id": "wf-1", "name": "receipts_scan_mailbox"},
        "execution": {"id": "ex-1"},
        "trigger": trigger,
        "error": {"type": "QboError", "message": "QuickBooks GET /query failed (401)", **error},
    }


def test_unattended_workflow_failure_opens_an_alert_for_the_workflow():
    signal = signal_from_event("workflow.retry_exhausted", _workflow_body())
    assert signal is not None
    assert (signal.action, signal.kind, signal.subject_key) == ("open", "workflow_failed", "workflow:wf-1")
    assert signal.title == "receipts_scan_mailbox failed"
    assert signal.detail == "QboError: QuickBooks GET /query failed (401)"
    assert (signal.organization_id, signal.execution_id) == ("org-1", "ex-1")


def test_a_failure_a_retry_may_still_fix_does_not_alert():
    assert signal_from_event("workflow.failed", _workflow_body()) is None


def test_a_run_a_person_started_does_not_alert():
    manual = {"type": "manual", "event_type": None, "event_id": None}
    assert signal_from_event("workflow.retry_exhausted", _workflow_body(trigger=manual)) is None


def test_the_next_unattended_success_resolves_it():
    body = {"organization": ORG, "workflow": {"id": "wf-1", "name": "x"}, "execution": {"id": "ex-2"}, "trigger": EVENT_TRIGGER}
    signal = signal_from_event("workflow.completed", body)
    assert signal is not None
    assert (signal.action, signal.subject_key) == ("resolve", "workflow:wf-1")


def test_a_script_without_a_workflow_does_not_alert():
    body = _workflow_body()
    body["workflow"] = {"id": None, "name": None}
    assert signal_from_event("workflow.retry_exhausted", body) is None


def test_long_errors_are_cut():
    signal = signal_from_event("workflow.retry_exhausted", _workflow_body(message="x" * 10_000))
    assert signal is not None and len(signal.detail) == MAX_DETAIL_CHARS


def _integration_body(**error) -> dict:
    return {
        "organization": ORG,
        "integration": {"id": "int-1", "name": "QuickBooks Online"},
        "error": {"message": "invalid_grant", "retryable": False, **error},
    }


def test_an_integration_that_needs_reconnecting_alerts_once_per_organization():
    signal = signal_from_event("integration.refresh_failed", _integration_body())
    assert signal is not None
    assert (signal.action, signal.subject_key) == ("open", "integration:int-1:org-1")
    assert signal.title == "QuickBooks Online needs reconnecting for Acme"
    assert signal.detail == "invalid_grant"


def test_a_refresh_that_will_be_retried_does_not_alert():
    assert signal_from_event("integration.refresh_failed", _integration_body(retryable=True)) is None


def test_recovering_or_reconnecting_resolves_it():
    for topic in ("integration.refresh_recovered", "integration.connected"):
        signal = signal_from_event(topic, {"organization": ORG, "integration": {"id": "int-1"}})
        assert signal is not None
        assert (signal.action, signal.subject_key) == ("resolve", "integration:int-1:org-1")


def test_other_topics_are_ignored():
    assert signal_from_event("user.invited", {"organization": ORG}) is None
