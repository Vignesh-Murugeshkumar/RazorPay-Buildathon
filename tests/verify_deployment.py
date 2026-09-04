import sys
import os
import requests
import json

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.security import generate_razorpay_signature


def verify_deployment(base_url: str = "http://localhost:3000", webhook_secret: str = "sentinel_secret_key_dev"):
    """
    Runs automated post-deployment smoke tests against a local or live Vercel deployment:
    1. Docs endpoint /docs accessibility.
    2. Health endpoint /api/v1/health.
    3. Rejection of invalid HMAC signature (HTTP 401).
    4. Successful processing of valid CE 3.0 dispute webhook (HTTP 200, Sc >= 85, Auto-Dispatch).
    5. Cryptographic ledger integrity check (/api/v1/audit/integrity -> is_valid: True).
    """
    print(f"🚀 Starting SentinelDispute Smoke Test Suite against: {base_url}")
    print("-" * 70)

    # 1. Check Health
    try:
        r_health = requests.get(f"{base_url}/api/v1/health", timeout=10)
        assert r_health.status_code == 200, f"Health check failed: {r_health.status_code}"
        print("✅ [1/5] Health endpoint responding (200 OK)")
    except Exception as e:
        print(f"❌ [1/5] Health check failed: {e}")
        return False

    # 2. Check OpenAPI / Docs
    try:
        r_docs = requests.get(f"{base_url}/docs", timeout=10)
        assert r_docs.status_code == 200, f"Docs check failed: {r_docs.status_code}"
        print("✅ [2/5] API Documentation /docs reachable (200 OK)")
    except Exception as e:
        print(f"❌ [2/5] Docs check failed: {e}")
        return False

    # 3. Test Invalid Signature Rejection (HTTP 401)
    payload = {
        "event": "payment.dispute.created",
        "dispute_id": "disp_smoke_test_001",
        "payment_id": "pay_smoke_001",
        "amount_inr": 2500.0,
        "card_network": "visa",
        "reason_code": "10.4",
        "telemetry": {
            "ip_address": "49.207.180.1",
            "device_id": "dev_smoke_123",
            "user_id": "user_smoke",
            "shipping_address": "Smoke Test St 101, Bangalore"
        }
    }
    raw_body = json.dumps(payload).encode('utf-8')
    headers_invalid = {
        "Content-Type": "application/json",
        "X-Razorpay-Signature": "invalid_bad_signature_deadbeef"
    }

    try:
        r_invalid = requests.post(f"{base_url}/api/v1/webhook/dispute", data=raw_body, headers=headers_invalid, timeout=10)
        assert r_invalid.status_code == 401, f"Expected 401 for bad signature, got {r_invalid.status_code}"
        print("✅ [3/5] Unauthorized HMAC signature rejected with HTTP 401")
    except Exception as e:
        print(f"❌ [3/5] Security test failed: {e}")
        return False

    # 4. Test Valid Webhook Ingestion with Correct Signature
    valid_sig = generate_razorpay_signature(raw_body, webhook_secret)
    headers_valid = {
        "Content-Type": "application/json",
        "X-Razorpay-Signature": valid_sig
    }

    # Add historical data and carrier proof to ensure auto-dispatch
    payload_valid = {
        **payload,
        "carrier_proof": {
            "carrier_name": "BlueDart",
            "tracking_number": "BD_SMOKE_999",
            "delivered_status": True,
            "verified_gps": True
        },
        "historical_transactions": [
            {
                "transaction_id": "tx_smoke_1",
                "payment_id": "pay_smoke_h1",
                "amount_inr": 2400.0,
                "days_ago": 150,
                "card_last4": "4242",
                "card_network": "visa",
                "ip_address": "49.207.180.1",
                "device_id": "dev_smoke_123",
                "user_id": "user_smoke",
                "shipping_address": "Smoke Test St 101, Bangalore",
                "undisputed": True
            },
            {
                "transaction_id": "tx_smoke_2",
                "payment_id": "pay_smoke_h2",
                "amount_inr": 2600.0,
                "days_ago": 270,
                "card_last4": "4242",
                "card_network": "visa",
                "ip_address": "49.207.180.1",
                "device_id": "dev_smoke_123",
                "user_id": "user_smoke",
                "shipping_address": "Smoke Test St 101, Bangalore",
                "undisputed": True
            }
        ]
    }
    raw_body_valid = json.dumps(payload_valid).encode('utf-8')
    valid_sig2 = generate_razorpay_signature(raw_body_valid, webhook_secret)
    headers_valid["X-Razorpay-Signature"] = valid_sig2

    try:
        r_valid = requests.post(f"{base_url}/api/v1/webhook/dispute", data=raw_body_valid, headers=headers_valid, timeout=10)
        assert r_valid.status_code == 200, f"Valid webhook failed with {r_valid.status_code}: {r_valid.text}"
        res = r_valid.json()
        assert res["decision"] == "AUTO_DISPATCHED", f"Expected AUTO_DISPATCHED, got {res['decision']}"
        assert res["confidence_score"] >= 85.0, f"Expected Sc >= 85, got {res['confidence_score']}"
        print(f"✅ [4/5] Valid CE 3.0 dispute ingested -> Auto-Dispatched (Sc={res['confidence_score']}/100, Seal={res['sealed_hash'][:12]}...)")
    except Exception as e:
        print(f"❌ [4/5] Valid webhook test failed: {e}")
        return False

    # 5. Test Cryptographic Ledger Integrity
    try:
        r_ledger = requests.get(f"{base_url}/api/v1/audit/integrity", timeout=10)
        assert r_ledger.status_code == 200
        leg = r_ledger.json()
        assert leg["is_valid"] is True
        print(f"✅ [5/5] Cryptographic Hash Chain Verified (Total Blocks: {leg['total_blocks']}, 0 Tampering Detected)")
    except Exception as e:
        print(f"❌ [5/5] Ledger integrity test failed: {e}")
        return False

    print("-" * 70)
    print("🎉 ALL 5 SMOKE TESTS PASSED SUCCESSFULLY!")
    return True


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000"
    verify_deployment(target)
