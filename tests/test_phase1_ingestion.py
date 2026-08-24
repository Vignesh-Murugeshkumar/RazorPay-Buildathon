import json
import pytest
from app.core.config import settings
from app.core.security import verify_razorpay_webhook, generate_razorpay_signature, compute_sha256_hash
from app.schemas.dispute import RazorpayDisputeWebhook, CustomerTelemetry, CarrierProof
from app.services.ledger import AuditLedger


def test_phase1_security_verification():
    secret = "test_phase1_secret_999"
    payload_bytes = b'{"event":"payment.dispute.created","dispute_id":"disp_phase1_01"}'
    
    valid_sig = generate_razorpay_signature(payload_bytes, secret)
    assert verify_razorpay_webhook(payload_bytes, valid_sig, secret) is True
    assert verify_razorpay_webhook(payload_bytes, "invalid_sig_xxx", secret) is False
    assert verify_razorpay_webhook(payload_bytes, None, secret) is False


def test_phase1_pydantic_schema_validation():
    data = {
        "event": "payment.dispute.created",
        "dispute_id": "disp_p1_test",
        "payment_id": "pay_p1_test",
        "amount": 250000, # paise or inr
        "currency": "INR",
        "reason_code": "10.4",
        "status": "open",
        "due_by": 1787400000,
        "telemetry": {
            "ip_address": "49.207.180.1",
            "device_id": "dev_fingerprint_01",
            "user_id": "cust_123",
            "shipping_address": "123 Indiranagar, Bangalore",
            "mfa_authenticated": True
        }
    }
    
    model = RazorpayDisputeWebhook.model_validate(data)
    assert model.dispute_id == "disp_p1_test"
    assert model.payment_id == "pay_p1_test"
    assert model.amount_inr == 250000.0
    assert model.telemetry.ip_address == "49.207.180.1"


def test_phase1_ledger_genesis_and_chaining():
    test_ledger = AuditLedger(genesis_signature="SIG_HMAC_GENESIS_WEBHOOK_001")
    test_ledger.reset_for_tests()
    
    # Check Genesis block
    assert len(test_ledger.chain) == 1
    genesis = test_ledger.chain[0]
    assert genesis.index == 0
    assert genesis.state_transition == "GENESIS_INIT"
    
    # Append state transitions
    b1 = test_ledger.append_block("INGRESS_GATEWAY", "WEBHOOK_VERIFIED", {"dispute_id": "disp_01"})
    b2 = test_ledger.append_block("TRIAGE_AGENT", "DISPUTE_TRIAGED", {"status": "normalized"})
    
    assert b1.previous_hash == genesis.block_hash
    assert b2.previous_hash == b1.block_hash
    
    integrity = test_ledger.verify_integrity()
    assert integrity.is_valid is True
    assert integrity.total_blocks == 3
    
    test_ledger.reset_for_tests()
