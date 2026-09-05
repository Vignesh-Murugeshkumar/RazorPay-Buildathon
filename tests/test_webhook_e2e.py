import time
import json
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.core.security import generate_razorpay_signature
from app.core.db import db
from app.services.ledger import ledger


@pytest.fixture(autouse=True)
def clean_db():
    db.clear_all_data()
    yield
    db.clear_all_data()


def test_real_razorpay_webhook_e2e_lifecycle():
    client = TestClient(app)
    dispute_id = "disp_e2e_test_987654"
    payment_id = "pay_e2e_test_123456"

    payload = {
        "event": "payment.dispute.created",
        "dispute_id": dispute_id,
        "payment_id": payment_id,
        "amount": 250000,
        "amount_inr": 2500.0,
        "currency": "INR",
        "card_network": "visa",
        "reason_code": "10.4",
        "status": "open",
        "telemetry": {
            "ip_address": "103.21.244.2",
            "device_id": "fp_device_abc123",
            "user_id": "usr_998877",
            "shipping_address": "42 Cyber City, Gurgaon, Haryana, 122002",
            "mfa_authenticated": True
        },
        "carrier_proof": {
            "carrier_name": "BlueDart Express",
            "tracking_number": "BD987654321IN",
            "delivered_status": True,
            "delivery_date": "2026-08-15T14:30:00Z",
            "recipient_signature_present": True,
            "gps_latitude": 28.4950,
            "gps_longitude": 77.0890,
            "verified_gps": True
        },
        "historical_transactions": [
            {
                "transaction_id": "txn_hist_01",
                "payment_id": "pay_hist_01",
                "amount_inr": 2500.0,
                "days_ago": 150,
                "card_last4": "4242",
                "card_network": "visa",
                "ip_address": "103.21.244.2",
                "device_id": "fp_device_abc123",
                "user_id": "usr_998877",
                "shipping_address": "42 Cyber City, Gurgaon, Haryana, 122002",
                "undisputed": True
            },
            {
                "transaction_id": "txn_hist_02",
                "payment_id": "pay_hist_02",
                "amount_inr": 3200.0,
                "days_ago": 210,
                "card_last4": "4242",
                "card_network": "visa",
                "ip_address": "103.21.244.2",
                "device_id": "fp_device_abc123",
                "user_id": "usr_998877",
                "shipping_address": "42 Cyber City, Gurgaon, Haryana, 122002",
                "undisputed": True
            }
        ]
    }

    raw_body = json.dumps(payload).encode("utf-8")
    now_ts = str(int(time.time()))
    event_id = "evt_razorpay_e2e_001"
    secret = settings.RAZORPAY_WEBHOOK_SECRET
    signature = generate_razorpay_signature(raw_body, secret)

    headers = {
        "X-Razorpay-Signature": signature,
        "X-Razorpay-Event-Time": now_ts,
        "X-Razorpay-Event-Id": event_id,
        "Content-Type": "application/json"
    }

    # 1. Ingest Webhook (Initial Submission)
    resp = client.post("/api/v1/webhook", content=raw_body, headers=headers)
    assert resp.status_code == 200, f"Webhook ingestion failed: {resp.text}"
    data = resp.json()
    assert data["status"] in ("processed", "success")
    assert data["dispute_id"] == dispute_id
    assert "sealed_hash" in data

    # 2. Idempotent Replay (A7 Lifecycle): Submitting identical event_id once completed returns 200 with cached result
    replay_resp = client.post("/api/v1/webhook", content=raw_body, headers=headers)
    assert replay_resp.status_code == 200, "Idempotent replay failed"
    replay_data = replay_resp.json()
    assert replay_data["dispute_id"] == dispute_id
    assert replay_data["sealed_hash"] == data["sealed_hash"]

    # 3. Ledger Integrity Verification
    integrity = ledger.verify_integrity()
    assert integrity.is_valid is True, "Ledger integrity check failed"
    assert ledger.get_total_count() > 0

    # 4. Timeline Events Verification
    timeline_resp = client.get(f"/api/v1/disputes/{dispute_id}/timeline")
    assert timeline_resp.status_code == 200
    events = timeline_resp.json()
    assert len(events) >= 4, f"Expected at least 4 timeline events, got {len(events)}"
    event_types = [e["event_type"] for e in events]
    assert "WEBHOOK_RECEIVED" in event_types
    assert "EVIDENCE_AGGREGATED" in event_types
    assert "RULES_EVALUATED" in event_types
    assert "DECISION_SEALED" in event_types

    # 5. Representment Package JSON Verification
    pkg_resp = client.get(f"/api/v1/disputes/{dispute_id}/representment-package")
    assert pkg_resp.status_code == 200
    pkg_data = pkg_resp.json()
    assert pkg_data["dispute_id"] == dispute_id
    assert pkg_data["card_network"] == "VISA"
    assert "evidence_intelligence" in pkg_data
    assert pkg_data["evidence_intelligence"]["mfa_verification"] is True
    assert pkg_data["evidence_intelligence"]["delivery_proof"]["delivered_status"] is True
    assert "decision_explanation" in pkg_data
    assert len(pkg_data["decision_explanation"]["top_positive_factors"]) > 0

    # 6. Representment Package PDF Generation Verification
    pdf_resp = client.get(f"/api/v1/disputes/{dispute_id}/representment-pdf")
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"
    assert pdf_resp.content.startswith(b"%PDF"), "Generated file is not a valid PDF header"
    assert len(pdf_resp.content) > 1000, "PDF content appears incomplete"

    # 7. Dashboard Stats Reflected
    dash_resp = client.get("/api/v1/dashboard/summary")
    assert dash_resp.status_code == 200
    dash_data = dash_resp.json()
    assert dash_data["total_disputes"] >= 1
    assert dash_data["total_amount_inr"] >= 2500.0
    assert len(dash_data["recent_disputes"]) >= 1
    assert dash_data["recent_disputes"][0]["dispute_id"] == dispute_id
