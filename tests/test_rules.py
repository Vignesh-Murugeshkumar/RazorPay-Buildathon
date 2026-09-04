import pytest
from app.schemas.dispute import (
    DisputePayload,
    CustomerTelemetry,
    CarrierProof,
    HistoricalTransaction
)
from app.rules.card_rules import (
    evaluate_visa_ce30,
    evaluate_mastercard_fpt,
    calculate_confidence_score,
    evaluate_dispute_compliance
)
from app.services.ledger import AuditLedger


def create_sample_payload(network="visa", reason_code="10.4", days1=150, days2=250, match_ip=True, match_device=True, carrier_deliv=True, gps=True):
    ip = "49.207.180.1"
    device = "device_fingerprint_abc"
    user = "user_123"
    addr = "123 Indiranagar Bangalore"

    h1 = HistoricalTransaction(
        transaction_id="tx_1",
        payment_id="pay_1",
        amount_inr=1000.0,
        days_ago=days1,
        card_last4="1111",
        card_network=network,
        ip_address=ip if match_ip else "1.1.1.1",
        device_id=device if match_device else "device_xyz",
        user_id=user,
        shipping_address=addr,
        undisputed=True
    )
    h2 = HistoricalTransaction(
        transaction_id="tx_2",
        payment_id="pay_2",
        amount_inr=1200.0,
        days_ago=days2,
        card_last4="1111",
        card_network=network,
        ip_address=ip if match_ip else "1.1.1.1",
        device_id=device if match_device else "device_xyz",
        user_id=user,
        shipping_address=addr,
        undisputed=True
    )

    carrier = CarrierProof(
        carrier_name="BlueDart",
        tracking_number="BD12345",
        delivered_status=carrier_deliv,
        recipient_signature_present=True,
        verified_gps=gps
    )

    return DisputePayload(
        event="payment.dispute.created",
        dispute_id="disp_unit_001",
        payment_id="pay_unit_001",
        amount_inr=1500.0,
        card_network=network,
        reason_code=reason_code,
        telemetry=CustomerTelemetry(
            ip_address=ip,
            device_id=device,
            user_id=user,
            shipping_address=addr,
            mfa_authenticated=True
        ),
        carrier_proof=carrier,
        historical_transactions=[h1, h2]
    )


def test_visa_ce30_qualifying():
    payload = create_sample_payload(network="visa", reason_code="10.4", days1=150, days2=250)
    is_compliant, count, matched, ip_dev, gaps = evaluate_visa_ce30(payload)
    assert is_compliant is True
    assert count == 2
    assert "ip_address" in matched
    assert "device_id" in matched
    assert ip_dev is True
    assert len(gaps) == 0


def test_visa_ce30_fails_lookback_too_recent():
    # Lookback 60 days is < 120 days
    payload = create_sample_payload(network="visa", reason_code="10.4", days1=60, days2=80)
    is_compliant, count, matched, ip_dev, gaps = evaluate_visa_ce30(payload)
    assert is_compliant is False
    assert count == 0
    assert len(gaps) > 0


def test_visa_ce30_fails_mandatory_ip_or_device():
    # Only user_id and shipping_address match, neither IP nor device
    payload = create_sample_payload(network="visa", match_ip=False, match_device=False)
    is_compliant, count, matched, ip_dev, gaps = evaluate_visa_ce30(payload)
    assert is_compliant is False
    assert ip_dev is False


def test_mastercard_fpt_qualifying():
    payload = create_sample_payload(network="mastercard", reason_code="4837", days1=45, days2=120)
    is_compliant, count, matched, tier1, gaps = evaluate_mastercard_fpt(payload)
    assert is_compliant is True
    assert count == 2
    assert tier1 is True


def test_confidence_score_calculation():
    # All verified: CE 3.0 (55) + Carrier (35) + GPS (10) + MFA (5) -> capped at 100
    score, bd = calculate_confidence_score(
        network_compliant=True,
        carrier_delivered=True,
        carrier_gps_verified=True,
        mfa_verified=True
    )
    assert score == 100.0
    assert bd["network_compliance_points"] == 55.0
    assert bd["carrier_delivery_points"] == 35.0

    # No carrier: CE 3.0 (55) + MFA (5) = 60 (< 85)
    score_no_carrier, _ = calculate_confidence_score(
        network_compliant=True,
        carrier_delivered=False,
        carrier_gps_verified=False,
        mfa_verified=True
    )
    assert score_no_carrier == 60.0


def test_audit_ledger_integrity_and_tamper_detection():
    test_ledger = AuditLedger(genesis_seed="TEST_SEED_123")
    test_ledger.reset_for_tests()
    
    # Append 3 valid blocks
    b1 = test_ledger.append_block("AGENT_A", "STEP_1", {"key": "val1"})
    b2 = test_ledger.append_block("AGENT_B", "STEP_2", {"key": "val2"})
    b3 = test_ledger.append_block("AGENT_C", "STEP_3", {"key": "val3"})
    
    report = test_ledger.verify_integrity()
    assert report.is_valid is True
    assert report.total_blocks == 4  # genesis + 3 blocks
    
    # Simulate tampering: directly mutate a payload hash in block 1
    original_hash = test_ledger.chain[1].payload_hash
    test_ledger.chain[1].payload_hash = "tampered_payload_hash_0000000000000000000000000000000000000000"
    
    tampered_report = test_ledger.verify_integrity()
    assert tampered_report.is_valid is False
    assert "altered" in tampered_report.discrepancy_details or "broken" in tampered_report.discrepancy_details
    
    # Reset
    test_ledger.reset_for_tests()


def test_saas_and_digital_goods_rule_evaluation():
    from app.schemas.dispute import DigitalFulfillmentProof
    from app.rules.card_rules import evaluate_dispute_compliance
    
    payload = create_sample_payload(network="visa", reason_code="10.4", days1=150, days2=200)
    payload.carrier_proof = None
    payload.service_type = "digital_saas"
    payload.digital_proof = DigitalFulfillmentProof(
        service_type="saas_subscription",
        access_logs_verified=True,
        ip_subnet_matched=True,
        user_account_active=True
    )
    
    result = evaluate_dispute_compliance(payload)
    assert result.ce30_compliant is True
    assert result.digital_verified is True
    # Compliance (55) + Digital Fulfillment (35) + Active/Subnet Bonus (10) + MFA (5) = 100.0 (Capped at 100)
    assert result.confidence_score == 100.0
    assert result.route_decision == "AUTO_DISPATCH"


def test_sqlite_database_dossier_persistence():
    from app.core.db import db
    from app.graphs.dispute_graph import execute_dispute_workflow
    
    payload = create_sample_payload(network="visa", reason_code="10.4", days1=150, days2=200)
    payload.dispute_id = f"disp_test_persist_{payload.payment_id}"
    
    dossier = execute_dispute_workflow(payload)
    db.save_dossier(dossier, payload)
    
    # Load back from DB
    loaded = db.get_dossier(dossier.dispute_id)
    assert loaded is not None
    assert loaded.dispute_id == dossier.dispute_id
    assert loaded.confidence_score == dossier.confidence_score
    assert loaded.decision == dossier.decision


@pytest.mark.asyncio
async def test_hitl_evidence_remediation_promotes_to_auto_dispatched():
    from app.main import remediate_dispute_evidence
    from app.schemas.remediation import RemediationEvidencePayload
    from app.graphs.dispute_graph import execute_dispute_workflow
    from app.core.db import db

    # Create a dispute with missing carrier (Score = 60 -> HITL)
    payload = create_sample_payload(network="visa", reason_code="10.4", days1=150, days2=200)
    payload.carrier_proof = None
    payload.dispute_id = "disp_test_hitl_remediation"

    initial_dossier = execute_dispute_workflow(payload)
    assert initial_dossier.confidence_score == 60.0
    assert initial_dossier.decision == "ROUTE_TO_HITL_QUEUE"
    db.save_dossier(initial_dossier, payload)

    # Perform remediation: analyst uploads verified BlueDart delivery & GPS
    remediation_input = RemediationEvidencePayload(
        analyst_id="ANALYST_SHERLOCK",
        analyst_notes="Uploaded physical POD signed by recipient.",
        carrier_name="BlueDart",
        tracking_number="BD987654321",
        delivered_status=True,
        verified_gps=True,
        gps_latitude=12.9716,
        gps_longitude=77.5946,
        mfa_authenticated=True
    )

    remediated_dossier = await remediate_dispute_evidence(payload.dispute_id, remediation_input)
    assert remediated_dossier.confidence_score == 100.0
    assert remediated_dossier.decision == "AUTO_DISPATCHED"
    assert remediated_dossier.carrier_proof is not None
    assert remediated_dossier.carrier_proof.delivered_status is True

