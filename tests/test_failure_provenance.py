"""
Tests for Failure Provenance & Circuit Breaker (app/core/exceptions.py, app/graphs/dispute_graph.py).

Verifies that any unexpected error in the workflow:
1. Fails safe by routing to ROUTE_TO_HITL_QUEUE.
2. Attaches structured FailureProvenance with component, reason, and safe action.
3. Records an audit block on the tamper-evident hash chain without breaking chain continuity.
4. Preserves 100% audit ledger integrity.
"""

import pytest
from unittest.mock import patch
from app.core.exceptions import (
    SentinelError,
    AIProviderError,
    DatabaseUnavailableError,
    EvidenceVerificationFailure,
    FailureProvenance
)
from app.schemas.dispute import DisputePayload
from app.graphs.dispute_graph import execute_dispute_workflow
from app.services.ledger import ledger


@pytest.fixture(autouse=True)
def clean_ledger():
    ledger.reset_for_tests("TEST_FAILSAFE_GENESIS")


def test_exception_provenance_generation():
    err = AIProviderError("OpenAI 503 Service Unavailable", dispute_id="disp_test_503")
    prov = err.to_provenance(action_taken="ROUTE_TO_HITL_QUEUE")
    
    assert prov.failure_type == "AIProviderError"
    assert prov.component == "AI_PROVIDER"
    assert prov.dispute_id == "disp_test_503"
    assert prov.action_taken == "ROUTE_TO_HITL_QUEUE"
    assert "OpenAI 503" in prov.reason
    assert prov.timestamp is not None


def test_pipeline_crash_failsafe_hitl_fallback():
    """When a node encounters an unhandled runtime error, the pipeline must fail-safe to HITL."""
    payload = DisputePayload(
        dispute_id="disp_crash_001",
        payment_id="pay_crash_001",
        amount_inr=7500.0,
        card_network="visa",
        reason_code="10.4"
    )

    with patch("app.graphs.dispute_graph.ai_investigation_agent_node") as mock_node:
        mock_node.side_effect = AIProviderError("Connection reset by peer while contacting LLM endpoint")
        
        dossier = execute_dispute_workflow(payload, mode="sentinel")

        assert dossier.decision == "ROUTE_TO_HITL_QUEUE"
        assert dossier.failure_provenance is not None
        assert dossier.failure_provenance["failure_type"] == "AIProviderError"
        assert dossier.failure_provenance["component"] == "AI_PROVIDER"
        assert dossier.failure_provenance["action_taken"] == "ROUTE_TO_HITL_QUEUE"
        assert "Connection reset" in dossier.failure_provenance["reason"]

    # Verify audit ledger integrity
    report = ledger.verify_integrity()
    assert report.is_valid is True

    # Verify the fallback block was recorded
    blocks = ledger.get_all_blocks()
    fallback_blocks = [b for b in blocks if b.state_transition == "WORKFLOW_ERROR_FALLBACK"]
    assert len(fallback_blocks) == 1
    assert fallback_blocks[0].decision == "ROUTE_TO_HITL_QUEUE"
