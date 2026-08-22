import pytest
from app.models.dispute import (
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
from app.ledger.audit_chain import AuditLedger


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
