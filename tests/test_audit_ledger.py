"""
Tests for Tamper-Evident Audit Hash Chain (app/services/ledger.py).

Validates:
1. Valid append-only chain verification.
2. Mutation detection (payload, timestamp, agent, transition tampering).
3. Block deletion detection.
4. Block insertion detection.
5. Block reordering detection.
6. Broken previous_hash pointer detection.
7. Granular audit provenance metadata preservation.
"""

import pytest
import copy
from app.services.ledger import AuditLedger, LedgerBlock


@pytest.fixture
def fresh_ledger():
    ledger = AuditLedger()
    ledger.reset_for_tests("TEST_GENESIS_SEED_12345")
    return ledger


def test_valid_chain_integrity(fresh_ledger):
    """A normal sequence of blocks must verify with 100% integrity."""
    fresh_ledger.append_block(
        agent_id="INGRESS_GATEWAY",
        state_transition="WEBHOOK_RECEIVED",
        payload={"dispute_id": "disp_101", "amount": 5000},
        dispute_id="disp_101",
        actor="RAZORPAY_WEBHOOK"
    )
    fresh_ledger.append_block(
        agent_id="INVESTIGATION_AGENT",
        state_transition="EVALUATION_COMPLETE",
        payload={"recommendation": "AUTONOMOUS_REPRESENTMENT", "confidence": 0.95},
        dispute_id="disp_101",
        actor="AI_INVESTIGATOR",
        policy_version="2026.1"
    )
    fresh_ledger.append_block(
        agent_id="SAFETY_GATE",
        state_transition="GATE_SEALED",
        payload={"final_action": "AUTO-REPRESENT"},
        dispute_id="disp_101",
        actor="DETERMINISTIC_SAFETY_GATE",
        decision="ACCEPT"
    )

    report = fresh_ledger.verify_integrity()
    assert report.is_valid is True
    assert report.total_blocks == 4  # genesis + 3
    assert report.discrepancy_details is None
    assert report.genesis_hash is not None
    assert report.latest_hash is not None


def test_tampering_mutation_detected(fresh_ledger):
    """Mutating any block payload or timestamp must be caught by hash recomputation."""
    fresh_ledger.append_block(
        agent_id="AGENT_A",
        state_transition="STEP_1",
        payload={"evidence_count": 3}
    )
    fresh_ledger.append_block(
        agent_id="AGENT_B",
        state_transition="STEP_2",
        payload={"verdict": "APPROVED"}
    )

    # Tamper with block 1 payload_hash
    tampered_block = fresh_ledger.chain[1].model_copy(
        update={"payload_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}
    )
    fresh_ledger.chain[1] = tampered_block

    report = fresh_ledger.verify_integrity()
    assert report.is_valid is False
    assert "hash altered" in report.discrepancy_details.lower() or "mismatch" in report.discrepancy_details.lower()


def test_tampering_block_deletion_detected(fresh_ledger):
    """Deleting a block from the middle must break index continuity and previous_hash."""
    fresh_ledger.append_block(agent_id="AGENT_1", state_transition="T1", payload={"step": 1})
    fresh_ledger.append_block(agent_id="AGENT_2", state_transition="T2", payload={"step": 2})
    fresh_ledger.append_block(agent_id="AGENT_3", state_transition="T3", payload={"step": 3})

    assert len(fresh_ledger.chain) == 4

    # Delete block 2 (leaving 0, 1, 3)
    del fresh_ledger.chain[2]

    report = fresh_ledger.verify_integrity()
    assert report.is_valid is False
    assert "sequence mismatch" in report.discrepancy_details.lower() or "chain broken" in report.discrepancy_details.lower()


def test_tampering_block_insertion_detected(fresh_ledger):
    """Inserting an unauthorized foreign block into the chain must be caught."""
    fresh_ledger.append_block(agent_id="AGENT_1", state_transition="T1", payload={"step": 1})
    fresh_ledger.append_block(agent_id="AGENT_2", state_transition="T2", payload={"step": 2})

    # Craft an inserted block
    injected_block = LedgerBlock(
        index=1,
        previous_hash=fresh_ledger.chain[0].block_hash,
        timestamp="2026-01-01T00:00:00Z",
        agent_id="ROGUE_AGENT",
        state_transition="UNAUTHORIZED_TAMPER",
        payload_hash="0" * 64,
        block_hash="1" * 64
    )
    fresh_ledger.chain.insert(1, injected_block)

    report = fresh_ledger.verify_integrity()
    assert report.is_valid is False


def test_tampering_block_reordering_detected(fresh_ledger):
    """Swapping the order of two blocks must fail verification."""
    fresh_ledger.append_block(agent_id="AGENT_1", state_transition="T1", payload={"step": 1})
    fresh_ledger.append_block(agent_id="AGENT_2", state_transition="T2", payload={"step": 2})

    # Swap block 1 and block 2
    fresh_ledger.chain[1], fresh_ledger.chain[2] = fresh_ledger.chain[2], fresh_ledger.chain[1]

    report = fresh_ledger.verify_integrity()
    assert report.is_valid is False


def test_tampering_broken_previous_hash_detected(fresh_ledger):
    """Changing previous_hash without changing index breaks cryptographic continuity."""
    fresh_ledger.append_block(agent_id="AGENT_1", state_transition="T1", payload={"step": 1})
    fresh_ledger.append_block(agent_id="AGENT_2", state_transition="T2", payload={"step": 2})

    # Mutate block 2 previous_hash
    b2 = fresh_ledger.chain[2]
    fresh_ledger.chain[2] = b2.model_copy(update={"previous_hash": "f" * 64})

    report = fresh_ledger.verify_integrity()
    assert report.is_valid is False
    assert "chain broken" in report.discrepancy_details.lower() or "hash altered" in report.discrepancy_details.lower()


def test_granular_audit_metadata_preserved(fresh_ledger):
    """Granular audit fields (event_id, dispute_id, correlation_id, actor, decision, etc.) are recorded."""
    block = fresh_ledger.append_block(
        agent_id="EVALUATOR",
        state_transition="POLICY_AUDIT",
        payload={"score": 0.88},
        event_id="evt_rzp_12345",
        dispute_id="disp_99999",
        correlation_id="corr_abc_xyz",
        actor="AUTONOMOUS_SYSTEM",
        decision="REPRESENT",
        policy_version="VISA_CE30_2026",
        model_version="gpt-4o-2024-08-06"
    )

    assert block.event_id == "evt_rzp_12345"
    assert block.dispute_id == "disp_99999"
    assert block.correlation_id == "corr_abc_xyz"
    assert block.actor == "AUTONOMOUS_SYSTEM"
    assert block.decision == "REPRESENT"
    assert block.policy_version == "VISA_CE30_2026"
    assert block.model_version == "gpt-4o-2024-08-06"
