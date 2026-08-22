from typing import List, Dict, Any
from app.models.dispute import (
    DisputePayload,
    CustomerTelemetry,
    CarrierProof,
    HistoricalTransaction
)


def generate_benchmark_dataset() -> List[Dict[str, Any]]:
    """
    Generates 60 realistic synthetic dispute test scenarios across 4 key cohorts:
    - Cohort A: 25 Visa 10.4 CE 3.0 Fully Compliant (Expected: AUTO_DISPATCH, Sc >= 85)
    - Cohort B: 15 Mastercard 4837/4855 FPT Fully Compliant (Expected: AUTO_DISPATCH, Sc >= 85)
    - Cohort C: 10 Borderline HITL Cases (Expected: ROUTE_TO_HITL_QUEUE, Sc < 85)
    - Cohort D: 10 Unqualified / Fraudulent Cases (Expected: ROUTE_TO_HITL_QUEUE, Sc < 85)
    """
    dataset: List[Dict[str, Any]] = []

    # ==========================================
    # COHORT A: 25 Visa CE 3.0 Qualifying Cases
    # ==========================================
    for i in range(1, 26):
        user_id = f"cust_visa_{i:03d}"
        ip_addr = f"49.207.180.{i}"
        device_id = f"fp_visa_dev_{i:03d}_uuid"
        address = f"{100 + i}, MG Road, Indiranagar, Bengaluru, Karnataka 560038"
        amount = 1500.0 + (i * 250.0)
        
        # 2 historical qualifying orders (lookback 140d and 280d)
        h1 = HistoricalTransaction(
            transaction_id=f"tx_hist_{i}_1",
            payment_id=f"pay_hist_{i}_1",
            amount_inr=amount - 100.0,
            days_ago=140,
            card_last4="4242",
            card_network="visa",
            ip_address=ip_addr,
            device_id=device_id,
            user_id=user_id,
            shipping_address=address,
            undisputed=True
        )
        h2 = HistoricalTransaction(
            transaction_id=f"tx_hist_{i}_2",
            payment_id=f"pay_hist_{i}_2",
            amount_inr=amount + 50.0,
            days_ago=280,
            card_last4="4242",
            card_network="visa",
            ip_address=ip_addr,
            device_id=device_id,
            user_id=user_id,
            shipping_address=address,
            undisputed=True
        )
        
        carrier = CarrierProof(
            carrier_name="BlueDart Express",
            tracking_number=f"BD_VISA_{i:05d}",
            delivered_status=True,
            delivery_date="2026-08-10",
            recipient_signature_present=True,
            gps_latitude=12.9716,
            gps_longitude=77.5946,
            verified_gps=(i % 2 == 0)  # half with verified GPS bonus
        )
        
        payload = DisputePayload(
            event="payment.dispute.created",
            dispute_id=f"disp_visa_ce30_{i:03d}",
            payment_id=f"pay_visa_live_{i:03d}",
            amount_inr=amount,
            card_network="visa",
            reason_code="10.4",
            telemetry=CustomerTelemetry(
                ip_address=ip_addr,
                device_id=device_id,
                user_id=user_id,
                shipping_address=address,
                mfa_authenticated=(i % 3 == 0)
            ),
            carrier_proof=carrier,
            historical_transactions=[h1, h2]
        )
        
        dataset.append({
            "category": "Visa CE 3.0 Compliant",
            "expected_decision": "AUTO_DISPATCH",
            "payload": payload
        })

    # ===============================================
    # COHORT B: 15 Mastercard FPT Qualifying Cases
    # ===============================================
    for i in range(1, 16):
        user_id = f"cust_mc_{i:03d}"
        ip_addr = f"103.211.54.{i}"
        device_id = f"fp_mc_dev_{i:03d}_uuid"
        address = f"Flat {200 + i}, Hiranandani Gardens, Powai, Mumbai, Maharashtra 400076"
        amount = 2200.0 + (i * 300.0)
        
        h1 = HistoricalTransaction(
            transaction_id=f"tx_mc_hist_{i}_1",
            payment_id=f"pay_mc_hist_{i}_1",
            amount_inr=amount,
            days_ago=90,
            card_last4="5555",
            card_network="mastercard",
            ip_address=ip_addr,
            device_id=device_id,
            user_id=user_id,
            shipping_address=address,
            undisputed=True
        )
        h2 = HistoricalTransaction(
            transaction_id=f"tx_mc_hist_{i}_2",
            payment_id=f"pay_mc_hist_{i}_2",
            amount_inr=amount + 200.0,
            days_ago=210,
            card_last4="5555",
            card_network="mastercard",
            ip_address=ip_addr,
            device_id=device_id,
            user_id=user_id,
            shipping_address=address,
            undisputed=True
        )
        
        carrier = CarrierProof(
            carrier_name="Delhivery Logistics",
            tracking_number=f"DL_MC_{i:05d}",
            delivered_status=True,
            delivery_date="2026-08-12",
            recipient_signature_present=True,
            gps_latitude=19.0760,
            gps_longitude=72.8777,
            verified_gps=True
        )
        
        payload = DisputePayload(
            event="payment.dispute.created",
            dispute_id=f"disp_mc_fpt_{i:03d}",
            payment_id=f"pay_mc_live_{i:03d}",
            amount_inr=amount,
            card_network="mastercard",
            reason_code="4837",
            telemetry=CustomerTelemetry(
                ip_address=ip_addr,
                device_id=device_id,
                user_id=user_id,
                shipping_address=address,
                mfa_authenticated=True
            ),
            carrier_proof=carrier,
            historical_transactions=[h1, h2]
        )
        
        dataset.append({
            "category": "Mastercard FPT Compliant",
            "expected_decision": "AUTO_DISPATCH",
            "payload": payload
        })

    # ==========================================
    # COHORT C: 10 Borderline HITL Cases
    # ==========================================
    # Lookback out of window (e.g. only 45 days ago), or carrier unconfirmed
    for i in range(1, 11):
        user_id = f"cust_hitl_{i:03d}"
        ip_addr = f"115.112.89.{i}"
        device_id = f"fp_hitl_{i:03d}"
        address = f"House {i*10}, Anna Nagar, Chennai, Tamil Nadu 600040"
        amount = 1800.0 + (i * 150.0)
        
        # Historical orders too recent (< 120 days for Visa CE 3.0)
        h1 = HistoricalTransaction(
            transaction_id=f"tx_hitl_hist_{i}_1",
            payment_id=f"pay_hitl_hist_{i}_1",
            amount_inr=amount,
            days_ago=45,  # Too recent for Visa CE 3.0 window [120, 365]
            card_last4="4242",
            card_network="visa",
            ip_address=ip_addr,
            device_id=device_id,
            user_id=user_id,
            shipping_address=address,
            undisputed=True
        )
        
        carrier = CarrierProof(
            carrier_name="Shadowfax",
            tracking_number=f"SF_HITL_{i:05d}",
            delivered_status=(i % 2 == 0),  # Some delivered, some in transit
            delivery_date=None,
            recipient_signature_present=False,
            verified_gps=False
        )
        
        payload = DisputePayload(
            event="payment.dispute.created",
            dispute_id=f"disp_hitl_{i:03d}",
            payment_id=f"pay_hitl_live_{i:03d}",
            amount_inr=amount,
            card_network="visa",
            reason_code="10.4",
            telemetry=CustomerTelemetry(
                ip_address=ip_addr,
                device_id=device_id,
                user_id=user_id,
                shipping_address=address,
                mfa_authenticated=False
            ),
            carrier_proof=carrier,
            historical_transactions=[h1]  # Only 1 transaction, requires >= 2
        )
        
        dataset.append({
            "category": "Borderline / Insufficient Historical Lookback",
            "expected_decision": "ROUTE_TO_HITL_QUEUE",
            "payload": payload
        })

    # ==========================================
    # COHORT D: 10 Unqualified / Fraudulent Cases
    # ==========================================
    for i in range(1, 11):
        user_id = f"cust_fraud_{i:03d}"
        ip_addr = f"185.220.101.{i}"  # Tor exit / VPN
        device_id = f"spoofed_device_{i:03d}"
        address = f"Unknown Postal Drop {i}, New Delhi 110001"
        amount = 5000.0 + (i * 1000.0)
        
        # First-time buyer: 0 historical transactions
        payload = DisputePayload(
            event="payment.dispute.created",
            dispute_id=f"disp_unqualified_{i:03d}",
            payment_id=f"pay_fraud_live_{i:03d}",
            amount_inr=amount,
            card_network="visa",
            reason_code="10.4",
            telemetry=CustomerTelemetry(
                ip_address=ip_addr,
                device_id=device_id,
                user_id=user_id,
                shipping_address=address,
                mfa_authenticated=False
            ),
            carrier_proof=None,  # No carrier proof
            historical_transactions=[]  # 0 prior transactions
        )
        
        dataset.append({
            "category": "Unqualified / First-Time Fraud",
            "expected_decision": "ROUTE_TO_HITL_QUEUE",
            "payload": payload
        })

    return dataset
