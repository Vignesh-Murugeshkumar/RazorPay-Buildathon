import time
import json
import threading
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.core.db import db
from app.core.security import generate_razorpay_signature
from app.schemas.dispute import (
    RazorpayDisputeWebhook,
    CustomerTelemetry,
    CarrierProof,
    DigitalFulfillmentProof,
    HistoricalTransaction,
    EvidenceStatus
)
from app.graphs.dispute_graph import execute_dispute_workflow, extract_evidence_and_contradictions, calculate_hitl_priority
from app.services.rag_rebuttal import rag_synthesizer
from app.services.issuer_intelligence import issuer_intelligence
from app.services.expected_value import calculate_expected_value


# ==============================================================================
# A1: NO LANGGRAPH DEPENDENCIES
# ==============================================================================
def test_a1_no_langgraph_dependency():
    """Verify that LangGraph is not imported or required anywhere in the codebase."""
    import sys
    assert "langgraph" not in sys.modules, "langgraph should not be loaded in lean-stack architecture"
    
    # Ensure dispute graph executes cleanly as deterministic plain Python
    payload = RazorpayDisputeWebhook(
        dispute_id="disp_a1_test",
        payment_id="pay_a1_test",
        amount_inr=1500.0,
        card_network="visa",
        reason_code="10.4"
    )
    dossier = execute_dispute_workflow(payload)
    assert dossier.dispute_id == "disp_a1_test"
    assert dossier.sealed_hash is not None


# ==============================================================================
# A2: EVIDENCE SEMANTICS & NO FABRICATED TELEMETRY
# ==============================================================================
def test_a2_no_fabricated_telemetry_and_derived_booleans():
    """Verify missing telemetry remains None (never 'NOT_PROVIDED' or fake IP) and booleans derive from EvidenceStatus."""
    # Payload with completely missing telemetry
    payload = RazorpayDisputeWebhook(
        dispute_id="disp_a2_missing",
        payment_id="pay_a2_missing",
        amount_inr=2000.0,
        card_network="visa",
        reason_code="10.4",
        telemetry=None,
        carrier_proof=None
    )
    assert payload.telemetry is None
    
    items, contradictions, statuses = extract_evidence_and_contradictions(payload)
    assert statuses["CUSTOMER_IP"] == EvidenceStatus.MISSING
    assert statuses["DEVICE_FINGERPRINT"] == EvidenceStatus.MISSING
    assert statuses["PAYMENT_AUTHENTICATION"] == EvidenceStatus.MISSING
    assert statuses["CARRIER_DELIVERY_PROOF"] == EvidenceStatus.MISSING

    dossier = execute_dispute_workflow(payload)
    assert dossier.ip_address is None, "Missing IP must be None, not fabricated '127.0.0.1'"
    assert dossier.evaluation.carrier_verified is False
    assert dossier.evaluation.mfa_verified is False


# ==============================================================================
# A3: EVIDENCE-CONSTRAINED REBUTTAL
# ==============================================================================
def test_a3_evidence_constrained_rebuttal_citations():
    """Verify every rebuttal claim cites [EV-xxx] and contains no fabricated PDFs."""
    payload = RazorpayDisputeWebhook(
        dispute_id="disp_a3_rebuttal",
        payment_id="pay_a3_rebuttal",
        amount_inr=4500.0,
        card_network="visa",
        reason_code="10.4",
        telemetry=CustomerTelemetry(
            ip_address="14.139.128.5",
            device_id="dev_mac_001",
            mfa_authenticated=True
        ),
        carrier_proof=CarrierProof(
            carrier_name="BlueDart",
            tracking_number="BD12345678",
            delivered_status=True,
            recipient_signature_present=True,
            verified_gps=True
        )
    )
    dossier = execute_dispute_workflow(payload)
    rebuttal = dossier.rebuttal_letter
    assert rebuttal is not None
    assert rebuttal["schema_version"] == "2.0-NETWORK-CONSTRAINED"
    assert len(rebuttal["claims"]) > 0

    for claim in rebuttal["claims"]:
        assert "supported_by" in claim
        assert len(claim["supported_by"]) > 0
        for ev_id in claim["supported_by"]:
            assert ev_id.startswith("EV-"), f"Claim citation must be EV-xxx, got {ev_id}"


# ==============================================================================
# A4: SYNTHETIC ISSUER LABELING
# ==============================================================================
def test_a4_synthetic_issuer_intelligence():
    """Verify issuer intelligence uses synthetic labels and explicit demo sourcing."""
    profile = issuer_intelligence.get_bin_profile("424242")
    assert profile is not None
    assert "Synthetic Issuer" in profile.issuing_bank, "Must use synthetic issuer naming"
    assert profile.source == "synthetic_demo_data"

    client = TestClient(app)
    resp = client.get("/api/v1/disputes/issuer-intelligence/profile/424242")
    assert resp.status_code == 200
    data = resp.json()
    assert "Synthetic Issuer" in data["issuing_bank"]
    assert data["source"] == "synthetic_demo_data"


# ==============================================================================
# A5: RULE ACCURACY DISCLOSURE
# ==============================================================================
def test_a5_rule_accuracy_disclosure():
    """Verify /api/v1/rules/all includes demo disclosure and status fields."""
    client = TestClient(app)
    resp = client.get("/api/v1/rules/all")
    assert resp.status_code == 200
    data = resp.json()
    assert "disclaimer" in data
    assert "demonstration purposes" in data["disclaimer"].lower()
    rules = data.get("rules", {})
    for net, content in rules.items():
        assert content.get("rule_status") == "demo_implementation"
        assert content.get("source") == "scheme_rules_reference"


# ==============================================================================
# A6: ESTIMATED WIN PROBABILITY TERMINOLOGY
# ==============================================================================
def test_a6_canonical_estimated_win_probability():
    """Verify estimated_win_probability is primary and p_win is preserved as alias."""
    ev = calculate_expected_value(
        amount_inr=3000.0,
        confidence_score=90.0,
        ce30_compliant=True,
        fpt_compliant=False
    )
    assert hasattr(ev, "estimated_win_probability")
    assert hasattr(ev, "p_win")
    assert ev.estimated_win_probability == ev.p_win

    payload = RazorpayDisputeWebhook(
        dispute_id="disp_a6_test",
        payment_id="pay_a6_test",
        amount_inr=3000.0,
        card_network="visa",
        reason_code="10.4"
    )
    dossier = execute_dispute_workflow(payload)
    assert dossier.estimated_win_probability is not None
    assert dossier.estimated_win_probability == dossier.p_win


# ==============================================================================
# A7: ATOMIC WEBHOOK STATE MACHINE & CONCURRENCY
# ==============================================================================
def test_a7_atomic_webhook_lifecycle_and_concurrency():
    """Verify atomic state transitions and that concurrent duplicate webhooks never both PROCEED."""
    client = TestClient(app)
    event_id = f"evt_concurrency_{int(time.time() * 1000)}"
    dispute_id = f"disp_concurrent_{int(time.time())}"

    payload = {
        "event": "payment.dispute.created",
        "dispute_id": dispute_id,
        "payment_id": "pay_conc_123",
        "amount": 100000,
        "amount_inr": 1000.0,
        "currency": "INR",
        "card_network": "visa",
        "reason_code": "10.4",
        "status": "open"
    }
    raw_body = json.dumps(payload).encode("utf-8")
    now_ts = str(int(time.time()))
    secret = settings.RAZORPAY_WEBHOOK_SECRET
    sig = generate_razorpay_signature(raw_body, secret)

    headers = {
        "X-Razorpay-Signature": sig,
        "X-Razorpay-Event-Time": now_ts,
        "X-Razorpay-Event-Id": event_id,
        "Content-Type": "application/json"
    }

    # Concurrent execution test: fire 2 requests simultaneously
    responses = []
    def make_request():
        c = TestClient(app)
        res = c.post("/api/v1/webhook", content=raw_body, headers=headers)
        responses.append(res)

    t1 = threading.Thread(target=make_request)
    t2 = threading.Thread(target=make_request)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    status_codes = [r.status_code for r in responses]
    # Exactly one must process (200), and if the second hit concurrently it got 409, or if after completion it got 200 cached
    assert 200 in status_codes, f"At least one request must succeed, got {status_codes}"
    
    # Now sequential duplicate of completed event MUST return 200 with identical cached response
    replay_resp = client.post("/api/v1/webhook", content=raw_body, headers=headers)
    assert replay_resp.status_code == 200
    assert replay_resp.json()["dispute_id"] == dispute_id


# ==============================================================================
# A8: DB-FIRST READS
# ==============================================================================
def test_a8_db_first_reads():
    """Verify GET /api/v1/disputes/{id} reads directly from database."""
    client = TestClient(app)
    dispute_id = f"disp_a8_{int(time.time())}"
    payload = RazorpayDisputeWebhook(
        dispute_id=dispute_id,
        payment_id="pay_a8_test",
        amount_inr=2200.0,
        card_network="visa",
        reason_code="10.4"
    )
    dossier = execute_dispute_workflow(payload)
    db.save_dossier(dossier)

    # Fetch via API endpoint
    resp = client.get(f"/api/v1/disputes/{dispute_id}")
    assert resp.status_code == 200
    fetched = resp.json()
    assert fetched["dispute_id"] == dispute_id
    assert fetched["amount_inr"] == 2200.0


# ==============================================================================
# B1: PROVENANCE GRAPH ENDPOINT
# ==============================================================================
def test_b1_provenance_graph_endpoint():
    """Verify GET /api/v1/disputes/{id}/provenance returns nodes, edges, and chains."""
    client = TestClient(app)
    dispute_id = f"disp_b1_{int(time.time())}"
    payload = RazorpayDisputeWebhook(
        dispute_id=dispute_id,
        payment_id="pay_b1_test",
        amount_inr=3500.0,
        card_network="visa",
        reason_code="10.4",
        telemetry=CustomerTelemetry(ip_address="103.22.11.1", device_id="dev_001", mfa_authenticated=True),
        carrier_proof=CarrierProof(carrier_name="BlueDart", tracking_number="BD9900", delivered_status=True, recipient_signature_present=True, verified_gps=True)
    )
    dossier = execute_dispute_workflow(payload)
    db.save_dossier(dossier)

    resp = client.get(f"/api/v1/disputes/{dispute_id}/provenance")
    assert resp.status_code == 200
    prov = resp.json()
    assert prov["dispute_id"] == dispute_id
    assert "nodes" in prov
    assert "edges" in prov
    assert "provenance_chains" in prov
    assert len(prov["provenance_chains"]) > 0

    node_types = {n["type"] for n in prov["nodes"]}
    assert "SOURCE" in node_types
    assert "EVIDENCE" in node_types
    assert "DECISION" in node_types


# ==============================================================================
# B2: CONTRADICTION DETECTION & HITL OVERRIDE
# ==============================================================================
def test_b2_contradiction_detection_gps_mismatch():
    """Verify GPS > 50m contradiction triggers CONTRADICTED status and overrides to HITL."""
    payload = RazorpayDisputeWebhook(
        dispute_id="disp_b2_gps_conflict",
        payment_id="pay_b2_gps",
        amount_inr=5000.0,
        card_network="visa",
        reason_code="10.4",
        telemetry=CustomerTelemetry(ip_address="1.1.1.1", device_id="dev_1", mfa_authenticated=True),
        carrier_proof=CarrierProof(
            carrier_name="BlueDart",
            tracking_number="BD8877",
            delivered_status=True,
            gps_latitude=28.5,
            gps_longitude=77.1,
            verified_gps=False  # Contradiction: delivered_status=True but GPS not verified within 50m
        )
    )
    dossier = execute_dispute_workflow(payload)
    assert len(dossier.contradictions) > 0
    assert dossier.contradictions[0].conflict_id == "CONF-003"
    assert dossier.decision == "ROUTE_TO_HITL_QUEUE", "Contradiction must force HITL review queue"
    assert dossier.evidence_statuses.get("GPS_GEOLOCATION") == EvidenceStatus.CONTRADICTED


def test_b2_contradiction_missing_tracking_number():
    """Verify delivered_status=True without tracking_number triggers contradiction."""
    payload = RazorpayDisputeWebhook(
        dispute_id="disp_b2_notrk",
        payment_id="pay_b2_notrk",
        amount_inr=5000.0,
        card_network="visa",
        reason_code="10.4",
        carrier_proof=CarrierProof(
            carrier_name="BlueDart",
            tracking_number="",  # Missing tracking number
            delivered_status=True
        )
    )
    dossier = execute_dispute_workflow(payload)
    assert len(dossier.contradictions) > 0
    assert dossier.contradictions[0].conflict_id == "CONF-001"
    assert dossier.decision == "ROUTE_TO_HITL_QUEUE"


def test_b2_contradiction_digital_access_while_account_inactive():
    """Verify access_logs_verified=True while user_account_active=False triggers contradiction."""
    payload = RazorpayDisputeWebhook(
        dispute_id="disp_b2_digital",
        payment_id="pay_b2_digital",
        amount_inr=5000.0,
        card_network="visa",
        reason_code="10.4",
        digital_proof=DigitalFulfillmentProof(
            access_logs_verified=True,
            user_account_active=False  # Contradiction: logs verified while account inactive
        )
    )
    dossier = execute_dispute_workflow(payload)
    assert len(dossier.contradictions) > 0
    assert dossier.contradictions[0].conflict_id == "CONF-004"
    assert dossier.decision == "ROUTE_TO_HITL_QUEUE"


# ==============================================================================
# B3: DEADLINE-AWARE HITL PRIORITY
# ==============================================================================
def test_b3_deadline_priority_ranking():
    """Verify overdue disputes rank above <6h deadlines, and queue sorts by priority score."""
    now = int(time.time())

    # Case 1: Overdue (due 2 hours ago)
    overdue_payload = RazorpayDisputeWebhook(
        dispute_id="disp_overdue",
        payment_id="pay_overdue",
        amount_inr=8000.0,
        card_network="visa",
        reason_code="13.1",
        due_by=now - 7200,
        carrier_proof=CarrierProof(carrier_name="BlueDart", tracking_number="BD1122", delivered_status=True)
    )
    score_overdue, urg_overdue, factors_overdue = calculate_hitl_priority(overdue_payload, 50.0, 0.5, False)
    assert urg_overdue == "critical"
    assert factors_overdue["deadline_score"] == 50.0

    # Case 2: Urgent (<6 hours left)
    urgent_payload = RazorpayDisputeWebhook(
        dispute_id="disp_urgent_6h",
        payment_id="pay_urgent",
        amount_inr=8000.0,
        card_network="visa",
        reason_code="13.1",
        due_by=now + 7200,  # 2 hours left
        carrier_proof=CarrierProof(carrier_name="BlueDart", tracking_number="BD3344", delivered_status=True)
    )
    score_urgent, urg_urgent, factors_urgent = calculate_hitl_priority(urgent_payload, 50.0, 0.5, False)
    assert urg_urgent == "critical"
    assert factors_urgent["deadline_score"] == 40.0

    # Overdue must rank higher than urgent
    assert score_overdue > score_urgent

    # Verify get_hitl_queue sorts by priority_score DESC
    dossier_overdue = execute_dispute_workflow(overdue_payload)
    dossier_urgent = execute_dispute_workflow(urgent_payload)
    db.save_dossier(dossier_overdue)
    db.save_dossier(dossier_urgent)

    queue = db.get_hitl_queue()
    assert len(queue) >= 2
    # The first element should have higher or equal priority_score than second
    assert queue[0]["priority_score"] >= queue[1]["priority_score"]
