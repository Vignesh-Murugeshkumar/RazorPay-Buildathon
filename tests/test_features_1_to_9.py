import json
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import db
from app.schemas.dispute import RazorpayDisputeWebhook
from app.graphs.dispute_graph import execute_dispute_workflow
from app.services.issuer_intelligence import issuer_intelligence


@pytest.fixture(autouse=True)
def clean_db():
    db.clear_all_data()
    yield
    db.clear_all_data()


def create_sample_dispute(dispute_id="disp_test_f19", amount=1500.0, network="visa", reason="10.4", mfa=True):
    payload = RazorpayDisputeWebhook(
        event="payment.dispute.created",
        dispute_id=dispute_id,
        payment_id=f"pay_{dispute_id}",
        amount_inr=amount,
        card_network=network,
        reason_code=reason,
        telemetry={
            "ip_address": "192.168.1.50",
            "device_id": "fp_test_dev",
            "user_id": "usr_test",
            "shipping_address": "MG Road, Bengaluru, Karnataka",
            "mfa_authenticated": mfa
        },
        carrier_proof={
            "carrier_name": "Delhivery",
            "tracking_number": "DEL123456789",
            "delivered_status": True,
            "delivery_date": "2026-08-10T10:00:00Z",
            "recipient_signature_present": True,
            "gps_latitude": 12.9716,
            "gps_longitude": 77.5946,
            "verified_gps": True
        },
        historical_transactions=[
            {
                "transaction_id": "txn_h1",
                "payment_id": "pay_h1",
                "amount_inr": amount,
                "days_ago": 140,
                "card_last4": "4242",
                "card_network": network,
                "ip_address": "192.168.1.50",
                "device_id": "fp_test_dev",
                "user_id": "usr_test",
                "shipping_address": "MG Road, Bengaluru, Karnataka",
                "undisputed": True
            },
            {
                "transaction_id": "txn_h2",
                "payment_id": "pay_h2",
                "amount_inr": amount,
                "days_ago": 180,
                "card_last4": "4242",
                "card_network": network,
                "ip_address": "192.168.1.50",
                "device_id": "fp_test_dev",
                "user_id": "usr_test",
                "shipping_address": "MG Road, Bengaluru, Karnataka",
                "undisputed": True
            }
        ]
    )
    dossier = execute_dispute_workflow(payload)
    db.save_dossier(dossier, payload)
    return dossier


def test_feature_1_dashboard_summary():
    client = TestClient(app)
    create_sample_dispute("disp_dash_1", 2000.0, "visa", "10.4")
    create_sample_dispute("disp_dash_2", 3500.0, "mastercard", "4837")

    resp = client.get("/api/v1/dashboard/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_disputes"] == 2
    assert data["total_amount_inr"] == 5500.0
    assert data["win_rate"] > 0
    assert data["auto_decision_rate"] >= 50.0
    assert len(data["network_breakdown"]) >= 2
    assert len(data["recent_disputes"]) == 2


def test_feature_2_explainable_ai_decision():
    client = TestClient(app)
    create_sample_dispute("disp_exp_1", 1800.0, "visa", "10.4")

    resp = client.get("/api/v1/disputes/disp_exp_1")
    assert resp.status_code == 200
    data = resp.json()
    assert "decision_explanation" in data
    exp = data["decision_explanation"]
    assert exp is not None
    assert "top_positive_factors" in exp
    assert len(exp["top_positive_factors"]) > 0
    assert "win_probability" in exp
    assert exp["win_probability"] > 0.5
    assert "rule_applied" in exp


def test_feature_3_evidence_intelligence():
    client = TestClient(app)
    create_sample_dispute("disp_evi_1", 4000.0, "visa", "10.4", mfa=True)

    resp = client.get("/api/v1/disputes/disp_evi_1")
    assert resp.status_code == 200
    data = resp.json()
    assert "payment_authentication" in data
    assert "3DS" in data["payment_authentication"]
    assert data["mfa_verification"] is True
    assert data["delivery_proof"]["delivered_status"] is True
    assert data["gps_verification"]["verified_within_50m"] is True
    assert data["customer_history_summary"]["total_historical_orders"] == 2


def test_feature_4_evidence_timeline():
    client = TestClient(app)
    create_sample_dispute("disp_time_1", 1200.0, "visa", "10.4")

    resp = client.get("/api/v1/disputes/disp_time_1/timeline")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) >= 3
    event_types = [e["event_type"] for e in events]
    assert "WEBHOOK_RECEIVED" in event_types
    assert "DECISION_SEALED" in event_types


def test_feature_5_representment_package():
    client = TestClient(app)
    create_sample_dispute("disp_pkg_1", 3000.0, "visa", "10.4")

    # JSON package
    json_resp = client.get("/api/v1/disputes/disp_pkg_1/representment-package")
    assert json_resp.status_code == 200
    pkg = json_resp.json()
    assert pkg["dispute_id"] == "disp_pkg_1"
    assert "evidence_intelligence" in pkg
    assert "cryptographic_verification" in pkg

    # PDF package
    pdf_resp = client.get("/api/v1/disputes/disp_pkg_1/representment-pdf")
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"
    assert pdf_resp.content.startswith(b"%PDF")


def test_feature_6_win_prob_ev_breakdown():
    client = TestClient(app)
    create_sample_dispute("disp_ev_1", 5000.0, "visa", "10.4")

    resp = client.get("/api/v1/disputes/disp_ev_1")
    assert resp.status_code == 200
    data = resp.json()
    assert "win_probability" in data
    assert "expected_value" in data
    assert "ev_breakdown" in data
    breakdown = data["ev_breakdown"]
    assert breakdown is not None
    assert "gross_recovery" in breakdown
    assert "risk_adjusted_fee" in breakdown
    assert "operational_cost_inr" in breakdown


def test_feature_7_hitl_review_queue_and_assignment():
    client = TestClient(app)
    create_sample_dispute("disp_hitl_1", 1500.0, "visa", "10.4")

    # Queue check
    q_resp = client.get("/api/v1/review-queue")
    assert q_resp.status_code == 200
    assert "disputes" in q_resp.json()

    # Assignment
    assign_resp = client.post("/api/v1/disputes/disp_hitl_1/assign", json={"assigned_to": "senior_analyst_raj"})
    assert assign_resp.status_code == 200
    assert assign_resp.json()["assigned_to"] == "senior_analyst_raj"

    # Verify dossier shows assigned_to
    disp_resp = client.get("/api/v1/disputes/disp_hitl_1")
    assert disp_resp.status_code == 200
    assert disp_resp.json()["assigned_to"] == "senior_analyst_raj"

    # Verify timeline recorded assignment
    tl_resp = client.get("/api/v1/disputes/disp_hitl_1/timeline")
    assert tl_resp.status_code == 200
    tl_types = [e["event_type"] for e in tl_resp.json()]
    assert "ASSIGNED" in tl_types


def test_feature_8_outcome_learning_loop():
    client = TestClient(app)
    create_sample_dispute("disp_out_1", 2200.0, "visa", "10.4")

    # Ingest gateway outcome won
    resp = client.post("/api/v1/disputes/outcome", json={
        "event": "payment.dispute.won",
        "dispute_id": "disp_out_1",
        "card_bin": "424242",
        "issuing_bank": "Synthetic Issuer A",
        "network": "visa",
        "reason_code": "10.4",
        "outcome": "won",
        "amount_inr": 2200.0,
        "confidence_score": 90.0
    })
    assert resp.status_code == 200

    # Verify BIN profile updated
    profile_resp = client.get("/api/v1/disputes/issuer-intelligence/profile/424242")
    assert profile_resp.status_code == 200
    prof = profile_resp.json()
    assert prof["won_disputes"] >= 1

    # Verify timeline event added
    tl_resp = client.get("/api/v1/disputes/disp_out_1/timeline")
    assert tl_resp.status_code == 200
    tl_types = [e["event_type"] for e in tl_resp.json()]
    assert "OUTCOME_RECORDED" in tl_types


def test_feature_9_rules_registry():
    client = TestClient(app)
    
    # Visa rules
    v_resp = client.get("/api/v1/rules/visa")
    assert v_resp.status_code == 200
    v_data = v_resp.json()
    assert v_data["network"] == "Visa"
    assert len(v_data["regulations"]) >= 2

    # Mastercard rules
    mc_resp = client.get("/api/v1/rules/mastercard")
    assert mc_resp.status_code == 200
    mc_data = mc_resp.json()
    assert mc_data["network"] == "Mastercard"

    # All rules
    all_resp = client.get("/api/v1/rules/all")
    assert all_resp.status_code == 200
    assert "visa" in all_resp.json()["networks"]
