import pytest
import time
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings, Settings
from app.core.db import db
from app.core.security import generate_razorpay_signature

client = TestClient(app)


def test_production_readiness_secret_validation():
    """Verify that insecure secrets are blocked when running in production."""
    # Default secret in production -> ValueError
    bad_settings = Settings(
        ENVIRONMENT="production",
        RAZORPAY_WEBHOOK_SECRET="sentinel_secret_key_dev"
    )
    with pytest.raises(ValueError, match="Insecure configuration detected"):
        bad_settings.validate_production_readiness()

    # Short secret (< 16 chars) in production -> ValueError
    short_settings = Settings(
        ENVIRONMENT="production",
        RAZORPAY_WEBHOOK_SECRET="short_secret"
    )
    with pytest.raises(ValueError, match="at least 16 characters"):
        short_settings.validate_production_readiness()

    # Valid strong secret in production -> passes
    good_settings = Settings(
        ENVIRONMENT="production",
        RAZORPAY_WEBHOOK_SECRET="a_very_strong_production_webhook_secret_key_2026"
    )
    good_settings.validate_production_readiness()


def test_database_ping():
    """Verify database health ping returns healthy with latency."""
    ping_result = db.ping()
    assert ping_result["healthy"] is True
    assert "latency_ms" in ping_result
    assert ping_result["engine"] in ("sqlite", "postgresql")


def test_deep_health_check_endpoint():
    """Verify /api/v1/health probe returns 200 OK and includes DB & audit details."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"]["healthy"] is True
    assert "audit_ledger" in data
    assert data["audit_ledger"]["integrity_verified"] is True


def test_security_headers_present():
    """Verify production security headers are set on all responses."""
    response = client.get("/api/v1/health")
    headers = response.headers
    assert "x-correlation-id" in headers
    assert headers.get("x-content-type-options") == "nosniff"
    assert headers.get("x-frame-options") == "DENY"
    assert headers.get("x-xss-protection") == "1; mode=block"


def test_webhook_payload_size_limit():
    """Verify payloads exceeding MAX_REQUEST_BODY_BYTES are rejected with 413."""
    # Create payload larger than 2MB
    huge_body = b"{" + b'"data": "' + b"A" * (2 * 1024 * 1024 + 10) + b'"}'
    response = client.post(
        "/api/v1/webhook/dispute",
        content=huge_body,
        headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


def test_production_webhook_missing_signature_rejection(monkeypatch):
    """Verify that in production mode, missing signature header is rejected with 401."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    
    payload = {
        "dispute_id": "disp_prod_test_001",
        "payment_id": "pay_prod_test_001",
        "amount": 5000,
        "amount_deducted": 5000,
        "currency": "INR",
        "reason_code": "10.4",
        "status": "open",
        "card_network": "visa"
    }
    
    # Request without X-Razorpay-Signature in production
    response = client.post(
        "/api/v1/webhook/dispute",
        json=payload
    )
    assert response.status_code == 401
    assert "Missing required X-Razorpay-Signature" in response.json()["detail"]
