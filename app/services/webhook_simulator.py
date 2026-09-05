"""
SentinelDispute - Realistic Razorpay Webhook Simulator.

Generates realistic, synthetic dispute payloads marked with source="synthetic_simulator",
signs them with HMAC-SHA256, and dispatches them through the actual HTTP webhook endpoint:
POST /webhooks/razorpay.

Exercises the entire production stack:
HTTP -> HMAC Auth -> Pydantic Validation -> Webhook Idempotency -> Workflow ->
Evidence Engine -> Contradiction Engine -> Rules Engine -> EV Engine -> HITL ->
Rebuttal Synthesizer -> Persistence (DB) -> Cryptographic Ledger.

Provides 5 distinct scenarios:
- Scenario A: Strong Evidence (Visa CE 3.0 Qualifying -> AUTO_DISPATCHED)
- Scenario B: Weak / Missing Evidence (Unqualified -> ROUTE_TO_HITL_QUEUE)
- Scenario C: Contradictory Evidence (Factual conflicts -> ROUTE_TO_HITL_QUEUE)
- Scenario D: Digital Service Dispute (SaaS fulfillment -> Non-fraud representment)
- Scenario E: Negative Expected Value (Unprofitable dispute -> AUTO_ACCEPT_OR_REFUND)
"""

import hmac
import hashlib
import json
import time
from typing import Dict, Any, Tuple, Optional
from app.core.config import settings
from app.core.security import generate_razorpay_signature


def build_scenario_payload(scenario_key: str, timestamp: Optional[int] = None) -> Dict[str, Any]:
    """
    Constructs a realistic Razorpay-shaped webhook payload for the given scenario.
    Explicitly labeled with source="synthetic_simulator".
    """
    ts = timestamp or int(time.time())
    key = scenario_key.upper()

    if key == "A" or "STRONG" in key:
        # Scenario A: Strong Evidence (Visa CE 3.0 Qualified)
        # 2 historical qualifying orders (150d, 220d), matching device/IP, verified carrier + GPS + MFA
        return {
            "entity": "event",
            "event": "payment.dispute.created",
            "source": "synthetic_simulator",
            "scenario": "A_STRONG_EVIDENCE",
            "dispute_id": f"disp_sim_a_{ts}",
            "payment_id": f"pay_sim_a_{ts}",
            "amount": 250000,
            "amount_inr": 2500.0,
            "currency": "INR",
            "card_network": "visa",
            "reason_code": "10.4",
            "status": "open",
            "due_by": ts + (7 * 86400),
            "telemetry": {
                "ip_address": "49.207.180.45",
                "device_id": "dev_macbook_pro_m3_uuid",
                "user_id": "user_arjun_kumar",
                "shipping_address": "Flat 302, Prestige Tower, Indiranagar, Bangalore, 560038",
                "mfa_authenticated": True
            },
            "carrier_proof": {
                "carrier_name": "BlueDart Express",
                "tracking_number": f"BD{ts % 100000000:08d}IN",
                "delivered_status": True,
                "recipient_signature_present": True,
                "gps_latitude": 12.9716,
                "gps_longitude": 77.5946,
                "verified_gps": True
            },
            "historical_transactions": [
                {
                    "transaction_id": f"tx_hist_a1_{ts}",
                    "payment_id": f"pay_hist_a1_{ts}",
                    "amount_inr": 2500.0,
                    "days_ago": 150,
                    "card_last4": "4242",
                    "card_network": "visa",
                    "ip_address": "49.207.180.45",
                    "device_id": "dev_macbook_pro_m3_uuid",
                    "shipping_address": "Flat 302, Prestige Tower, Indiranagar, Bangalore, 560038",
                    "undisputed": True
                },
                {
                    "transaction_id": f"tx_hist_a2_{ts}",
                    "payment_id": f"pay_hist_a2_{ts}",
                    "amount_inr": 3100.0,
                    "days_ago": 220,
                    "card_last4": "4242",
                    "card_network": "visa",
                    "ip_address": "49.207.180.45",
                    "device_id": "dev_macbook_pro_m3_uuid",
                    "shipping_address": "Flat 302, Prestige Tower, Indiranagar, Bangalore, 560038",
                    "undisputed": True
                }
            ]
        }

    elif key == "B" or "WEAK" in key or "MISSING" in key:
        # Scenario B: Weak / Missing Evidence (No carrier proof, no telemetry match, no prior orders)
        return {
            "entity": "event",
            "event": "payment.dispute.created",
            "source": "synthetic_simulator",
            "scenario": "B_WEAK_MISSING_EVIDENCE",
            "dispute_id": f"disp_sim_b_{ts}",
            "payment_id": f"pay_sim_b_{ts}",
            "amount": 480000,
            "amount_inr": 4800.0,
            "currency": "INR",
            "card_network": "visa",
            "reason_code": "10.4",
            "status": "open",
            "due_by": ts + (3 * 86400),
            "telemetry": {
                "ip_address": "185.220.101.5",
                "device_id": "unknown_tor_exit_node",
                "user_id": "anon_shopper_99",
                "shipping_address": "Drop Point Warehouse, Delhi",
                "mfa_authenticated": False
            },
            "carrier_proof": None,
            "historical_transactions": []
        }

    elif key == "C" or "CONTRADICT" in key:
        # Scenario C: Contradictory Evidence
        # delivered_status=True but tracking_number is None
        # AND GPS present but verified_gps=False (>50m distance mismatch)
        return {
            "entity": "event",
            "event": "payment.dispute.created",
            "source": "synthetic_simulator",
            "scenario": "C_CONTRADICTORY_EVIDENCE",
            "dispute_id": f"disp_sim_c_{ts}",
            "payment_id": f"pay_sim_c_{ts}",
            "amount": 750000,
            "amount_inr": 7500.0,
            "currency": "INR",
            "card_network": "visa",
            "reason_code": "10.4",
            "status": "open",
            "due_by": ts + (2 * 86400),
            "telemetry": {
                "ip_address": "103.21.244.2",
                "device_id": "dev_pixel_phone",
                "user_id": "user_siddharth",
                "shipping_address": "42 Cyber City, Gurgaon, Haryana, 122002",
                "mfa_authenticated": True
            },
            "carrier_proof": {
                "carrier_name": "Delhivery",
                "tracking_number": "",  # Contradiction: delivered=True with empty tracking
                "delivered_status": True,
                "recipient_signature_present": False,
                "gps_latitude": 28.5950,  # Contradiction: outside 50m perimeter
                "gps_longitude": 77.1890,
                "verified_gps": False
            },
            "historical_transactions": []
        }

    elif key == "D" or "DIGITAL" in key:
        # Scenario D: Digital Service Dispute (SaaS / Download, Reason 13.1)
        # Active access logs + active user account
        return {
            "entity": "event",
            "event": "payment.dispute.created",
            "source": "synthetic_simulator",
            "scenario": "D_DIGITAL_SERVICE_DISPUTE",
            "dispute_id": f"disp_sim_d_{ts}",
            "payment_id": f"pay_sim_d_{ts}",
            "amount": 850000,
            "amount_inr": 8500.0,
            "currency": "INR",
            "card_network": "visa",
            "reason_code": "13.1",
            "service_type": "digital_saas",
            "status": "open",
            "due_by": ts + (5 * 86400),
            "telemetry": {
                "ip_address": "106.51.78.22",
                "device_id": "dev_ipad_pro_uuid",
                "user_id": "user_ananya_sharma",
                "shipping_address": "Whitefield, Bangalore",
                "mfa_authenticated": True
            },
            "digital_proof": {
                "service_type": "saas_subscription",
                "access_logs_verified": True,
                "download_timestamp": "2026-08-20T10:00:00Z",
                "user_account_active": True
            },
            "historical_transactions": []
        }

    elif key == "E" or "NEGATIVE" in key or "UNPROFITABLE" in key or "REFUND" in key:
        # Scenario E: Negative Expected Value Unprofitable Dispute
        # Amount = ₹350, fee = ₹1500, E[V] is strongly negative -> AUTO_ACCEPT_OR_REFUND
        return {
            "entity": "event",
            "event": "payment.dispute.created",
            "source": "synthetic_simulator",
            "scenario": "E_NEGATIVE_EXPECTED_VALUE",
            "dispute_id": f"disp_sim_e_{ts}",
            "payment_id": f"pay_sim_e_{ts}",
            "amount": 35000,
            "amount_inr": 350.0,
            "currency": "INR",
            "card_network": "visa",
            "reason_code": "10.4",
            "status": "open",
            "due_by": ts + (10 * 86400),
            "telemetry": {
                "ip_address": "115.112.89.12",
                "device_id": "dev_budget_phone",
                "user_id": "user_micro_buyer",
                "shipping_address": "Anna Nagar, Chennai",
                "mfa_authenticated": False
            },
            "carrier_proof": None,
            "historical_transactions": []
        }

    else:
        raise ValueError(f"Unknown simulation scenario '{scenario_key}'. Choose from A, B, C, D, E.")


def generate_signed_request(
    scenario_key: str,
    secret: Optional[str] = None,
    timestamp: Optional[int] = None
) -> Tuple[bytes, Dict[str, str], str]:
    """
    Builds the payload, encodes to JSON bytes, generates HMAC-SHA256 signature,
    and returns (raw_body, headers, event_id).
    """
    ts = timestamp or int(time.time())
    payload = build_scenario_payload(scenario_key, ts)
    raw_body = json.dumps(payload).encode("utf-8")

    webhook_secret = secret or settings.RAZORPAY_WEBHOOK_SECRET
    signature = generate_razorpay_signature(raw_body, webhook_secret)
    event_id = f"evt_sim_{scenario_key.lower()}_{ts}"

    headers = {
        "Content-Type": "application/json",
        "X-Razorpay-Signature": signature,
        "X-Razorpay-Event-Time": str(ts),
        "X-Razorpay-Event-Id": event_id
    }

    return raw_body, headers, event_id


class RazorpayWebhookSimulator:
    """
    Production-path simulator runner. Dispatches signed HTTP requests
    to the real /webhooks/razorpay endpoint via an ASGI TestClient or httpx.AsyncClient.
    """

    def __init__(self, client=None, secret: Optional[str] = None):
        self.client = client
        self.secret = secret or settings.RAZORPAY_WEBHOOK_SECRET

    def run_scenario(self, scenario_key: str, endpoint: str = "/webhooks/razorpay") -> Dict[str, Any]:
        """
        Executes a complete synchronous HTTP simulation test using TestClient.
        """
        if self.client is None:
            from fastapi.testclient import TestClient
            from app.main import app
            self.client = TestClient(app)

        raw_body, headers, event_id = generate_signed_request(scenario_key, self.secret)
        response = self.client.post(endpoint, content=raw_body, headers=headers)
        return {
            "status_code": response.status_code,
            "event_id": event_id,
            "scenario": scenario_key.upper(),
            "response": response.json() if response.status_code in (200, 400, 401, 409, 422) else response.text
        }


webhook_simulator = RazorpayWebhookSimulator()
generate_scenario_payload = build_scenario_payload


def run_simulator(endpoint: str = "/webhooks/razorpay"):
    sim = RazorpayWebhookSimulator()
    results = []
    for sc in ["A", "B", "C", "D", "E"]:
        res = sim.run_scenario(sc, endpoint=endpoint)
        resp_data = res.get("response", {}) if isinstance(res.get("response"), dict) else {}
        results.append({
            "scenario": sc,
            "status_code": res["status_code"],
            "decision": resp_data.get("decision"),
            "confidence_score": resp_data.get("confidence_score", 0.0),
            "response": resp_data
        })
    return results
