import time
import json
import pytest
from app.core.security import (
    verify_razorpay_webhook,
    validate_webhook_timestamp,
    generate_razorpay_signature,
    compute_sha256_hash
)
from app.core.db import db


def test_valid_signature_verification():
    secret = "test_webhook_secret_xyz_123"
    raw_payload = b'{"event":"payment.dispute.created","dispute_id":"disp_001"}'
    
    valid_sig = generate_razorpay_signature(raw_payload, secret)
    assert verify_razorpay_webhook(raw_payload, valid_sig, secret) is True


def test_invalid_signature_rejection():
    secret = "test_webhook_secret_xyz_123"
    raw_payload = b'{"event":"payment.dispute.created","dispute_id":"disp_001"}'
    
    invalid_sig = "deadbeef1234567890abcdef1234567890abcdef1234567890abcdef12345678"
    assert verify_razorpay_webhook(raw_payload, invalid_sig, secret) is False


def test_tampered_payload_rejection():
    secret = "test_webhook_secret_xyz_123"
    original_payload = b'{"event":"payment.dispute.created","dispute_id":"disp_001","amount":1000}'
    tampered_payload = b'{"event":"payment.dispute.created","dispute_id":"disp_001","amount":9999}'
    
    sig = generate_razorpay_signature(original_payload, secret)
    assert verify_razorpay_webhook(tampered_payload, sig, secret) is False


def test_empty_signature_or_secret():
    payload = b'{"dispute_id":"disp_001"}'
    assert verify_razorpay_webhook(payload, None, "secret") is False
    assert verify_razorpay_webhook(payload, "sig", "") is False
    assert verify_razorpay_webhook(payload, "", "secret") is False


def test_webhook_timestamp_tolerance():
    now = time.time()
    # Fresh timestamp (10 seconds ago) -> True
    assert validate_webhook_timestamp(now - 10, tolerance_seconds=300) is True
    # Stale timestamp (10 minutes ago) -> False
    assert validate_webhook_timestamp(now - 600, tolerance_seconds=300) is False
    # Future timestamp within tolerance -> True
    assert validate_webhook_timestamp(now + 10, tolerance_seconds=300) is True
    # Invalid timestamp format -> False
    assert validate_webhook_timestamp("invalid_ts") is False


def test_webhook_replay_guard_nonce():
    event_id = f"evt_test_replay_{int(time.time()*1000)}"
    # First submission: fresh -> True
    assert db.record_and_verify_event(event_id, "sig_123") is True
    # Second submission with same event_id: replay -> False
    assert db.record_and_verify_event(event_id, "sig_123") is False


def test_compute_sha256_hash():
    data = "test_string_for_hashing"
    h1 = compute_sha256_hash(data)
    h2 = compute_sha256_hash(data.encode('utf-8'))
    assert len(h1) == 64
    assert h1 == h2

