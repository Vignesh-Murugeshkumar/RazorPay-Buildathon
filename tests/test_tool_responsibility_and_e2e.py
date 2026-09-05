import json
import time
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.core.security import generate_razorpay_signature
from app.core.db import db
from app.services.ledger import ledger
from app.services.evidence_engine import (
    extract_evidence_items,
    detect_contradictions,
    calculate_hitl_priority,
    EvidenceStatus
)
from app.services.rebuttal_synthesizer import (
    rebuttal_synthesizer,
    SynthesizedClaim
)
from app.services.issuer_intelligence import issuer_intel
from app.services.webhook_simulator import (
    webhook_simulator,
    generate_scenario_payload,
    run_simulator
)
from app.schemas.dispute import (
    RazorpayDisputeWebhook,
    CustomerTelemetry,
    CarrierProof,
    DigitalFulfillmentProof,
    HistoricalTransaction,
    EvidenceItem,
    EvidenceContradiction
)
from app.rules.card_rules import (
    evaluate_visa_ce30,
    evaluate_mastercard_fpt,
    evaluate_dispute_compliance
)
from app.services.expected_value import (
    calculate_expected_value,
    estimate_win_probability,
    ExpectedValueResult
)


@pytest.fixture(autouse=True)
def clean_db():
    db.clear_all_data()
    ledger.reset_for_tests()
    yield
    db.clear_all_data()
    ledger.reset_for_tests()


# --------------------------------------------------------------------------
# 1. Valid HMAC Webhook
# --------------------------------------------------------------------------
def test_01_valid_hmac_webhook():
    client = TestClient(app)
    payload = generate_scenario_payload("A")
    raw_body = json.dumps(payload).encode("utf-8")
    now_ts = str(int(time.time()))
    event_id = "evt_test_valid_hmac_01"
    signature = generate_razorpay_signature(raw_body, settings.RAZORPAY_WEBHOOK_SECRET)

    headers = {
        "X-Razorpay-Signature": signature,
        "X-Razorpay-Event-Time": now_ts,
        "X-Razorpay-Event-Id": event_id,
        "Content-Type": "application/json"
    }

    resp = client.post("/webhooks/razorpay", content=raw_body, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["dispute_id"] == payload["dispute_id"]
    assert "sealed_hash" in data


# --------------------------------------------------------------------------
# 2. Invalid HMAC Webhook
# --------------------------------------------------------------------------
def test_02_invalid_hmac_webhook():
    client = TestClient(app)
    payload = generate_scenario_payload("A")
    raw_body = json.dumps(payload).encode("utf-8")
    now_ts = str(int(time.time()))
    event_id = "evt_test_invalid_hmac_02"

    headers = {
        "X-Razorpay-Signature": "invalid_hmac_signature_hex_digest_123456",
        "X-Razorpay-Event-Time": now_ts,
        "X-Razorpay-Event-Id": event_id,
        "Content-Type": "application/json"
    }

    resp = client.post("/webhooks/razorpay", content=raw_body, headers=headers)
    assert resp.status_code == 401
    assert "Invalid Razorpay webhook HMAC-SHA256 signature" in resp.json()["detail"]


# --------------------------------------------------------------------------
# 3. Duplicate Completed Webhook -> Cached 200
# --------------------------------------------------------------------------
def test_03_duplicate_completed_webhook_cached_200():
    client = TestClient(app)
    payload = generate_scenario_payload("A")
    raw_body = json.dumps(payload).encode("utf-8")
    now_ts = str(int(time.time()))
    event_id = "evt_test_duplicate_03"
    signature = generate_razorpay_signature(raw_body, settings.RAZORPAY_WEBHOOK_SECRET)

    headers = {
        "X-Razorpay-Signature": signature,
        "X-Razorpay-Event-Time": now_ts,
        "X-Razorpay-Event-Id": event_id,
        "Content-Type": "application/json"
    }

    # First attempt -> succeeds
    resp1 = client.post("/webhooks/razorpay", content=raw_body, headers=headers)
    assert resp1.status_code == 200
    first_res = resp1.json()

    # Second attempt with same event_id -> returns cached 200 result
    resp2 = client.post("/webhooks/razorpay", content=raw_body, headers=headers)
    assert resp2.status_code == 200
    second_res = resp2.json()
    assert second_res["dispute_id"] == first_res["dispute_id"]
    assert second_res["sealed_hash"] == first_res["sealed_hash"]


# --------------------------------------------------------------------------
# 4. Concurrent PROCESSING Duplicate -> 409 Conflict
# --------------------------------------------------------------------------
def test_04_concurrent_processing_duplicate_409():
    client = TestClient(app)
    event_id = "evt_test_concurrent_04"
    signature = "dummy_sig_04"

    # Register the event directly as currently PROCESSING in the database
    action, _ = db.register_webhook_event(event_id, signature)
    assert action == "PROCEED"  # Initial insert claims PROCESSING

    # A concurrent incoming request with the same event_id must receive 409 Conflict
    payload = generate_scenario_payload("A")
    raw_body = json.dumps(payload).encode("utf-8")
    now_ts = str(int(time.time()))
    real_sig = generate_razorpay_signature(raw_body, settings.RAZORPAY_WEBHOOK_SECRET)

    headers = {
        "X-Razorpay-Signature": real_sig,
        "X-Razorpay-Event-Time": now_ts,
        "X-Razorpay-Event-Id": event_id,
        "Content-Type": "application/json"
    }

    resp = client.post("/webhooks/razorpay", content=raw_body, headers=headers)
    assert resp.status_code == 409
    assert "currently being processed" in resp.json()["detail"]


# --------------------------------------------------------------------------
# 5. Failed Webhook Retry Allowed
# --------------------------------------------------------------------------
def test_05_failed_webhook_retry():
    client = TestClient(app)
    event_id = "evt_test_failed_retry_05"
    payload = generate_scenario_payload("A")
    raw_body = json.dumps(payload).encode("utf-8")
    now_ts = str(int(time.time()))
    signature = generate_razorpay_signature(raw_body, settings.RAZORPAY_WEBHOOK_SECRET)

    # First simulate an event that failed
    db.register_webhook_event(event_id, signature)
    db.fail_webhook_event(event_id, "Simulated transient timeout")

    headers = {
        "X-Razorpay-Signature": signature,
        "X-Razorpay-Event-Time": now_ts,
        "X-Razorpay-Event-Id": event_id,
        "Content-Type": "application/json"
    }

    # Retry should be allowed to proceed and complete
    resp = client.post("/webhooks/razorpay", content=raw_body, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"


# --------------------------------------------------------------------------
# 6. Evidence Statuses Correctness
# --------------------------------------------------------------------------
def test_06_evidence_statuses():
    # Construct a webhook with distinct evidence states
    dispute = RazorpayDisputeWebhook(
        dispute_id="disp_ev_status_test",
        payment_id="pay_ev_status_test",
        amount=10000,
        amount_inr=100.0,
        currency="INR",
        card_network="visa",
        reason_code="10.4",
        status="open",
        telemetry=CustomerTelemetry(
            ip_address="192.168.1.100",
            device_id="dev_status_01",
            mfa_authenticated=True,
            user_id="usr_01"
        ),
        carrier_proof=CarrierProof(
            carrier_name="BlueDart",
            tracking_number=None, # Missing tracking -> UNVERIFIED / PARTIALLY_VERIFIED
            delivered_status=True
        ),
        historical_transactions=[]
    )

    items, _ = extract_evidence_items(dispute)
    item_map = {it.evidence_id: it for it in items}

    # EV-001 (IP) should be VERIFIED
    assert item_map["EV-001"].status == EvidenceStatus.VERIFIED
    # EV-002 (Device ID) should be VERIFIED
    assert item_map["EV-002"].status == EvidenceStatus.VERIFIED
    # EV-003 (MFA) should be VERIFIED
    assert item_map["EV-003"].status == EvidenceStatus.VERIFIED
    # EV-005 (GPS) missing -> MISSING
    assert item_map["EV-005"].status == EvidenceStatus.MISSING
    # EV-006 (Historical Transactions) empty -> MISSING
    assert item_map["EV-006"].status == EvidenceStatus.MISSING


# --------------------------------------------------------------------------
# 7. Deterministic Contradiction Detection
# --------------------------------------------------------------------------
def test_07_contradiction_detection():
    # 1. delivered=True + missing tracking number
    d1 = RazorpayDisputeWebhook(
        dispute_id="disp_c1",
        payment_id="pay_c1",
        amount=1000,
        amount_inr=10.0,
        currency="INR",
        card_network="visa",
        reason_code="10.4",
        carrier_proof=CarrierProof(
            delivered_status=True,
            tracking_number=None,
            carrier_name="BlueDart"
        )
    )
    c1 = detect_contradictions(d1)
    assert any(c.conflict_id == "CONF-001" for c in c1)

    # 2. delivered=False + recipient signature present
    d2 = RazorpayDisputeWebhook(
        dispute_id="disp_c2",
        payment_id="pay_c2",
        amount=1000,
        amount_inr=10.0,
        currency="INR",
        card_network="visa",
        reason_code="10.4",
        carrier_proof=CarrierProof(
            delivered_status=False,
            tracking_number="BD123",
            recipient_signature_present=True
        )
    )
    c2 = detect_contradictions(d2)
    assert any(c.conflict_id == "CONF-002" for c in c2)

    # 3. GPS mismatch > 50m (gps present, delivered=True, verified_gps=False)
    d3 = RazorpayDisputeWebhook(
        dispute_id="disp_c3",
        payment_id="pay_c3",
        amount=1000,
        amount_inr=10.0,
        currency="INR",
        card_network="visa",
        reason_code="10.4",
        carrier_proof=CarrierProof(
            delivered_status=True,
            tracking_number="BD123",
            gps_latitude=28.4950,
            gps_longitude=77.0890,
            verified_gps=False
        )
    )
    c3 = detect_contradictions(d3)
    assert any(c.conflict_id == "CONF-003" for c in c3)

    # 4. Digital access logs present + account inactive
    d4 = RazorpayDisputeWebhook(
        dispute_id="disp_c4",
        payment_id="pay_c4",
        amount=1000,
        amount_inr=10.0,
        currency="INR",
        card_network="visa",
        reason_code="10.4",
        digital_proof=DigitalFulfillmentProof(
            access_logs_verified=True,
            user_account_active=False
        )
    )
    c4 = detect_contradictions(d4)
    assert any(c.conflict_id == "CONF-004" for c in c4)


# --------------------------------------------------------------------------
# 8. HITL Priority Scoring
# --------------------------------------------------------------------------
def test_08_hitl_priority_scoring():
    d_clean = RazorpayDisputeWebhook(
        dispute_id="disp_hitl_1",
        payment_id="pay_hitl_1",
        amount=50000,
        amount_inr=500.0,
        currency="INR",
        card_network="visa",
        reason_code="10.4"
    )
    score_clean, tier_clean, reasons_clean = calculate_hitl_priority(
        payload=d_clean,
        confidence_score=0.90,
        estimated_win_probability=0.85,
        has_contradictions=False
    )

    score_contra, tier_contra, reasons_contra = calculate_hitl_priority(
        payload=d_clean,
        confidence_score=0.60,
        estimated_win_probability=0.50,
        has_contradictions=True
    )

    # Contradiction presence must boost the priority score and flag in reasons
    assert score_contra > score_clean
    assert any("contradiction" in r.lower() for r in reasons_contra)


# --------------------------------------------------------------------------
# 9. Visa Rules Engine (CE 3.0)
# --------------------------------------------------------------------------
def test_09_visa_rules_engine():
    # CE 3.0 requires 2+ qualifying historical transactions with matching IP or device
    d_qualifying = RazorpayDisputeWebhook(
        dispute_id="disp_visa_01",
        payment_id="pay_visa_01",
        amount=250000,
        amount_inr=2500.0,
        currency="INR",
        card_network="visa",
        reason_code="10.4",
        telemetry=CustomerTelemetry(ip_address="10.0.0.1", device_id="dev_01"),
        historical_transactions=[
            HistoricalTransaction(
                transaction_id="tx_1",
                payment_id="pay_1",
                amount_inr=2500.0,
                days_ago=150,
                ip_address="10.0.0.1",
                device_id="dev_01",
                undisputed=True
            ),
            HistoricalTransaction(
                transaction_id="tx_2",
                payment_id="pay_2",
                amount_inr=3000.0,
                days_ago=180,
                ip_address="10.0.0.1",
                device_id="dev_01",
                undisputed=True
            )
        ]
    )

    is_compliant, qualifying_count, matched_ids, ip_or_device, gaps = evaluate_visa_ce30(d_qualifying)
    assert is_compliant is True
    assert qualifying_count >= 2
    assert ip_or_device is True
    assert "ip_address" in matched_ids or "device_id" in matched_ids


# --------------------------------------------------------------------------
# 10. Mastercard Rules Engine (FPT)
# --------------------------------------------------------------------------
def test_10_mastercard_rules_engine():
    d_fpt = RazorpayDisputeWebhook(
        dispute_id="disp_mc_01",
        payment_id="pay_mc_01",
        amount=250000,
        amount_inr=2500.0,
        currency="INR",
        card_network="mastercard",
        reason_code="4837",
        telemetry=CustomerTelemetry(ip_address="10.0.0.2", device_id="dev_02", mfa_authenticated=True),
        carrier_proof=CarrierProof(carrier_name="BlueDart", tracking_number="MC9988", delivered_status=True),
        historical_transactions=[
            HistoricalTransaction(
                transaction_id="tx_mc1",
                payment_id="pay_mc1",
                amount_inr=1500.0,
                days_ago=90,
                ip_address="10.0.0.2",
                device_id="dev_02",
                undisputed=True
            ),
            HistoricalTransaction(
                transaction_id="tx_mc2",
                payment_id="pay_mc2",
                amount_inr=2000.0,
                days_ago=120,
                ip_address="10.0.0.2",
                device_id="dev_02",
                undisputed=True
            )
        ]
    )

    is_compliant, qualifying_count, matched_ids, tier1, gaps = evaluate_mastercard_fpt(d_fpt)
    assert is_compliant is True
    assert qualifying_count >= 2
    assert tier1 is True


# --------------------------------------------------------------------------
# 11. Expected Value Engine Mathematical Output
# --------------------------------------------------------------------------
def test_11_expected_value_math():
    res = calculate_expected_value(
        amount_inr=5000.0,
        confidence_score=95.0,
        issuer_fee_inr=1200.0,
        operational_cost_inr=300.0,
        ce30_compliant=True
    )
    # Expected value: E[V] = p_win * 5000 - (1 - p_win) * 1200 - 300
    p = res.estimated_win_probability
    expected = round((p * 5000.0) - ((1.0 - p) * 1200.0) - 300.0, 2)
    assert res.expected_value_inr == expected
    assert res.decision in ("AUTO_SUBMIT_REPRESENTMENT", "ROUTE_TO_HITL_QUEUE")


# --------------------------------------------------------------------------
# 12. estimated_win_probability Terminology (No fake calibration)
# --------------------------------------------------------------------------
def test_12_estimated_win_probability_terminology():
    res = calculate_expected_value(
        amount_inr=100.0,
        confidence_score=10.0,
        issuer_fee_inr=500.0,
        operational_cost_inr=200.0
    )
    # The field must be estimated_win_probability, not "calibrated_win_probability"
    assert hasattr(res, "estimated_win_probability")
    assert not hasattr(res, "calibrated_win_probability")


# --------------------------------------------------------------------------
# 13. Claim -> Evidence -> Rule Provenance (CL-xxx -> EV-xxx -> RULE-xxx)
# --------------------------------------------------------------------------
def test_13_claim_evidence_rule_provenance():
    d = RazorpayDisputeWebhook(
        dispute_id="disp_prov_01",
        payment_id="pay_prov_01",
        amount=100000,
        amount_inr=1000.0,
        currency="INR",
        card_network="visa",
        reason_code="10.4",
        telemetry=CustomerTelemetry(
            ip_address="203.0.113.1",
            device_id="dev_prov_01",
            mfa_authenticated=True
        ),
        carrier_proof=CarrierProof(
            carrier_name="BlueDart",
            tracking_number="BD777",
            delivered_status=True,
            verified_gps=True
        )
    )

    items, _ = extract_evidence_items(d)
    letter = rebuttal_synthesizer.synthesize_rebuttal(
        payload=d,
        confidence_score=0.92,
        p_win=0.85,
        evidence_items=items
    )

    assert len(letter.claims) > 0
    for claim in letter.claims:
        # Every claim must have a valid claim_id, supported_by EV references, and rule_id
        assert claim.claim_id.startswith("CL-")
        assert len(claim.supported_by) > 0
        for ev_id in claim.supported_by:
            assert ev_id.startswith("EV-")
        assert claim.rule_id.startswith("RULE-")
        # Ensure the mapped evidence exists in items and is verified
        mapped = next((it for it in items if it.evidence_id in claim.supported_by), None)
        assert mapped is not None
        assert mapped.status in (EvidenceStatus.VERIFIED, EvidenceStatus.PARTIALLY_VERIFIED)


# --------------------------------------------------------------------------
# 14. No Unsupported Claims (Missing evidence = no claim)
# --------------------------------------------------------------------------
def test_14_no_unsupported_claims_when_evidence_missing():
    # Empty dispute with no carrier proof, no telemetry, no transactions
    d_empty = RazorpayDisputeWebhook(
        dispute_id="disp_empty_01",
        payment_id="pay_empty_01",
        amount=50000,
        amount_inr=500.0,
        currency="INR",
        card_network="visa",
        reason_code="10.4"
    )

    items, _ = extract_evidence_items(d_empty)
    letter = rebuttal_synthesizer.synthesize_rebuttal(
        payload=d_empty,
        confidence_score=0.10,
        p_win=0.05,
        evidence_items=items
    )

    # Because no evidence is VERIFIED, zero unsupported claims must be synthesized
    assert len(letter.claims) == 0
    assert "Awaiting human evidence remediation" in letter.rebuttal_statement


# --------------------------------------------------------------------------
# 15. Synthetic Issuer Intelligence Labeling
# --------------------------------------------------------------------------
def test_15_synthetic_issuer_labeling():
    intel = issuer_intel.get_bin_profile("424242")
    # Must explicitly state synthetic demo source and not claim to be live network telemetry
    assert intel.source == "synthetic_demo_data"
    assert "synthetic" in intel.issuing_bank.lower()


# --------------------------------------------------------------------------
# 16. Database Persistence Isolation & Strict Production Requirement
# --------------------------------------------------------------------------
def test_16_db_persistence_strict_production():
    # In test mode, fallback is SQLite and works without crashing
    assert db._is_postgres is False

    # In production mode without PostgreSQL URL, it must strictly raise RuntimeError
    with patch("os.getenv") as mock_env:
        def getenv_side_effect(k, default=None):
            if k == "ENVIRONMENT":
                return "production"
            if k in ("DATABASE_URL", "SUPABASE_DATABASE_URL", "POSTGRES_URL", "TEST_MODE"):
                return None
            return default

        mock_env.side_effect = getenv_side_effect
        with pytest.raises(RuntimeError) as exc_info:
            db._init_db()
        assert "strictly required in PRODUCTION environment" in str(exc_info.value)


# --------------------------------------------------------------------------
# 17. Complete Webhook -> Dossier -> Ledger Flow
# --------------------------------------------------------------------------
def test_17_complete_webhook_dossier_ledger_flow():
    client = TestClient(app)
    payload = generate_scenario_payload("A")
    raw_body = json.dumps(payload).encode("utf-8")
    now_ts = str(int(time.time()))
    event_id = "evt_test_ledger_flow_17"
    signature = generate_razorpay_signature(raw_body, settings.RAZORPAY_WEBHOOK_SECRET)

    headers = {
        "X-Razorpay-Signature": signature,
        "X-Razorpay-Event-Time": now_ts,
        "X-Razorpay-Event-Id": event_id,
        "Content-Type": "application/json"
    }

    resp = client.post("/webhooks/razorpay", content=raw_body, headers=headers)
    assert resp.status_code == 200
    res_data = resp.json()

    # Check dossier saved in DB
    dossier = db.get_dossier(payload["dispute_id"])
    assert dossier is not None
    assert dossier.sealed_hash == res_data["sealed_hash"]

    # Check SHA-256 ledger integrity
    is_valid, err = ledger.verify_chain()
    assert is_valid is True, f"Ledger chain validation failed: {err}"


# --------------------------------------------------------------------------
# 18. All Five Simulator Scenarios
# --------------------------------------------------------------------------
def test_18_all_five_simulator_scenarios():
    results = run_simulator()
    assert len(results) == 5

    scenarios = {r["scenario"]: r for r in results}

    # Scenario A: Strong Evidence -> 200, AUTO_DISPATCHED
    assert scenarios["A"]["status_code"] == 200
    assert scenarios["A"]["decision"] == "AUTO_DISPATCHED"

    # Scenario B: Weak/Missing Evidence -> 200, AUTO_ACCEPT_OR_REFUND
    assert scenarios["B"]["status_code"] == 200
    assert scenarios["B"]["decision"] in ("AUTO_ACCEPT_OR_REFUND", "ROUTE_TO_HITL_QUEUE")

    # Scenario C: Contradictory Evidence -> 200, lower confidence than A
    assert scenarios["C"]["status_code"] == 200
    assert scenarios["C"]["confidence_score"] < scenarios["A"]["confidence_score"]

    # Scenario D: Digital Service Dispute -> 200
    assert scenarios["D"]["status_code"] == 200

    # Scenario E: Negative Expected Value -> 200, AUTO_ACCEPT_OR_REFUND
    assert scenarios["E"]["status_code"] == 200
    assert scenarios["E"]["decision"] == "AUTO_ACCEPT_OR_REFUND"
