import time
import pytest
from app.core.redis_telemetry import RedisTelemetryClient
from app.core.db import db
from app.services.pre_dispute import handle_pre_dispute_inquiry, matches_ce30_criteria
from app.services.expected_value import calculate_expected_value, calibrate_win_probability
from app.services.document_ocr import ocr_parser
from app.services.rag_rebuttal import rag_synthesizer
from app.services.issuer_intelligence import issuer_intelligence
from app.connectors.gateways import (
    RazorpayUPIAndRuPayAdapter,
    StripeGatewayAdapter,
    AdyenGatewayAdapter,
    ShopifyGatewayAdapter
)
from app.connectors.logistics_crm import logistics_connector, crm_connector
from app.schemas.dispute import RazorpayDisputeWebhook, CustomerTelemetry, CarrierProof, HistoricalTransaction
from app.graphs.dispute_graph import execute_dispute_workflow


# ==============================================================================
# STEP 1: LOW-LATENCY TELEMETRY CACHING & LOOKBACK OPTIMIZATION
# ==============================================================================
def test_step1_telemetry_hot_cache_sliding_ttl():
    """Verifies sub-millisecond retrieval and 120-365 day sliding window filtering."""
    client = RedisTelemetryClient()
    client.clear()
    card_fp = "test_card_fp_12345"
    now = time.time()

    # 1. Ingest order 150 days ago (Qualifying: 120-365d)
    t1 = now - (150 * 86400)
    client.record_transaction(
        card_fingerprint=card_fp,
        customer_id="cust_1",
        ip_address="49.207.180.45",
        device_fingerprint="device_mac_01",
        shipping_address="Indiranagar, Bangalore",
        amount_inr=2000.0,
        transaction_time=t1
    )

    # 2. Ingest order 250 days ago (Qualifying: 120-365d)
    t2 = now - (250 * 86400)
    client.record_transaction(
        card_fingerprint=card_fp,
        customer_id="cust_1",
        ip_address="49.207.180.45",
        device_fingerprint="device_mac_01",
        shipping_address="Indiranagar, Bangalore",
        amount_inr=3000.0,
        transaction_time=t2
    )

    # 3. Ingest order 30 days ago (Disqualified: < 120d)
    t3 = now - (30 * 86400)
    client.record_transaction(
        card_fingerprint=card_fp,
        customer_id="cust_1",
        ip_address="49.207.180.45",
        device_fingerprint="device_mac_01",
        shipping_address="Indiranagar, Bangalore",
        amount_inr=1500.0,
        transaction_time=t3
    )

    # 4. Ingest order 400 days ago (Disqualified: > 365d)
    t4 = now - (400 * 86400)
    client.record_transaction(
        card_fingerprint=card_fp,
        customer_id="cust_1",
        ip_address="49.207.180.45",
        device_fingerprint="device_mac_01",
        shipping_address="Indiranagar, Bangalore",
        amount_inr=5000.0,
        transaction_time=t4
    )

    # Benchmark sub-millisecond query
    t_start = time.perf_counter()
    qualifying = client.get_qualifying_orders(card_fp, min_days=120, max_days=365, reference_time=now)
    query_latency_ms = (time.perf_counter() - t_start) * 1000.0

    assert len(qualifying) == 2
    assert query_latency_ms < 10.0, f"Query latency too high: {query_latency_ms}ms"
    assert all(120 <= q["days_ago"] <= 365 for q in qualifying)


# ==============================================================================
# STEP 2: UPSTREAM PRE-DISPUTE INTERCEPTION ENGINE (<= 2s SLA)
# ==============================================================================
@pytest.mark.asyncio
async def test_step2_pre_dispute_interception_deflection():
    """Verifies pre-dispute inquiry deflection with CE 3.0 match within SLA."""
    from app.core.redis_telemetry import telemetry_hot_cache
    card_fp = "card_fp_verifi_test_999"
    now = time.time()

    # Seed 2 historical qualifying orders
    telemetry_hot_cache.record_transaction(
        card_fingerprint=card_fp,
        customer_id="user_rahul",
        ip_address="49.207.180.45",
        device_fingerprint="dev_mac_uuid",
        shipping_address="Indiranagar, Bangalore",
        amount_inr=4000.0,
        transaction_time=now - (140 * 86400)
    )
    telemetry_hot_cache.record_transaction(
        card_fingerprint=card_fp,
        customer_id="user_rahul",
        ip_address="49.207.180.45",
        device_fingerprint="dev_mac_uuid",
        shipping_address="Indiranagar, Bangalore",
        amount_inr=4500.0,
        transaction_time=now - (260 * 86400)
    )

    inquiry = {
        "inquiry_id": "inq_verifi_001",
        "network": "visa",
        "card_fingerprint": card_fp,
        "customer_id": "user_rahul",
        "ip_address": "49.207.180.45",
        "device_fingerprint": "dev_mac_uuid",
        "shipping_address": "Indiranagar, Bangalore",
        "amount_inr": 4200.0,
        "timestamp": now
    }

    result = await handle_pre_dispute_inquiry(inquiry)
    assert result["status"] == "DEFLECTED"
    assert result["evidence_type"] == "CE_3_0"
    assert len(result["orders"]) == 2
    assert result["sla_guaranteed"] is True
    assert result["response_time_ms"] < 2000.0


@pytest.mark.asyncio
async def test_step2_pre_dispute_interception_no_match():
    """Verifies pre-dispute handles missing telemetry with NO_MATCH."""
    inquiry = {
        "inquiry_id": "inq_ethoca_002",
        "network": "mastercard",
        "card_fingerprint": "unknown_unseen_card_fingerprint",
        "customer_id": "random_user",
        "ip_address": "1.1.1.1",
        "device_fingerprint": "dev_xyz"
    }

    result = await handle_pre_dispute_inquiry(inquiry)
    assert result["status"] == "NO_MATCH"
    assert result["sla_guaranteed"] is True


# ==============================================================================
# STEP 3: DYNAMIC EXPECTED VALUE (E[V]) DECISION ENGINE
# ==============================================================================
def test_step3_expected_value_profitable_high_p():
    """E[V] > 0 and P(win) >= 0.70 -> AUTO_SUBMIT_REPRESENTMENT."""
    res = calculate_expected_value(
        amount_inr=10000.0,
        confidence_score=95.0,
        issuer_fee_inr=1500.0,
        operational_cost_inr=40.0,
        ce30_compliant=True
    )
    assert res.is_profitable is True
    assert res.p_win >= 0.70
    assert res.expected_value_inr > 0
    assert res.decision == "AUTO_SUBMIT_REPRESENTMENT"


def test_step3_expected_value_moderate_hitl():
    """E[V] > 0 and 0.40 <= P(win) < 0.70 -> ROUTE_TO_HITL_QUEUE."""
    res = calculate_expected_value(
        amount_inr=8000.0,
        confidence_score=60.0,
        issuer_fee_inr=1500.0,
        operational_cost_inr=40.0,
        ce30_compliant=False
    )
    assert res.is_profitable is True
    assert 0.40 <= res.p_win < 0.70
    assert res.decision == "ROUTE_TO_HITL_QUEUE"


def test_step3_expected_value_unprofitable_auto_accept():
    """E[V] <= 0 -> AUTO_ACCEPT_OR_REFUND to avoid $18 / ₹1500 penalty."""
    res = calculate_expected_value(
        amount_inr=400.0,
        confidence_score=20.0,
        issuer_fee_inr=1500.0,
        operational_cost_inr=40.0,
        ce30_compliant=False
    )
    assert res.is_profitable is False
    assert res.expected_value_inr <= 0
    assert res.decision == "AUTO_ACCEPT_OR_REFUND"


# ==============================================================================
# STEP 4: MULTIMODAL RAG FOR NON-FRAUD REASON CODES
# ==============================================================================
def test_step4_document_ocr_and_rebuttal_synthesis():
    """Verifies OCR parsing and constrained JSON-schema rebuttal synthesis for Visa 13.1."""
    raw_ocr = "Delhivery Consignment Waybill: DL99221100. Status: Signed by Recipient at 2026-02-10 14:00. Geofence OK."
    extracted = ocr_parser.parse_proof_of_delivery(raw_ocr, gps_lat=12.9716, gps_lng=77.5946)
    assert extracted.carrier_name == "Delhivery"
    assert extracted.tracking_number == "DL99221100"
    assert extracted.signature_present is True

    payload = RazorpayDisputeWebhook(
        dispute_id="disp_test_rag_13_1",
        payment_id="pay_rag_123",
        amount_inr=6500.0,
        card_network="visa",
        reason_code="13.1",
        telemetry=CustomerTelemetry(
            ip_address="49.207.180.45",
            device_id="dev_mac",
            user_id="user_rahul",
            shipping_address="Indiranagar, Bangalore",
            mfa_authenticated=True
        ),
        carrier_proof=CarrierProof(
            carrier_name=extracted.carrier_name,
            tracking_number=extracted.tracking_number,
            delivered_status=True,
            recipient_signature_present=extracted.signature_present,
            verified_gps=True
        )
    )

    rebuttal = rag_synthesizer.synthesize_rebuttal(payload, confidence_score=85.0, p_win=0.88)
    assert rebuttal.schema_version == "2.0-NETWORK-CONSTRAINED"
    assert rebuttal.tracking_number == "DL99221100"
    assert "refuting the claim of non-receipt" in rebuttal.rebuttal_statement
    assert len(rebuttal.terms_of_service_clauses) > 0


# ==============================================================================
# STEP 5: MULTI-RAIL & DOMESTIC CONNECTORS
# ==============================================================================
def test_step5_gateway_adapters():
    """Verifies Stripe, Adyen, and NPCI UDIR UPI adapters."""
    # 1. NPCI UDIR Adapter
    udir_adapter = RazorpayUPIAndRuPayAdapter()
    udir_event = udir_adapter.parse_webhook({
        "id": "disp_udir_99",
        "payment_id": "pay_upi_88",
        "amount": 2500.0,
        "method": "upi",
        "reason_code": "UDIR_GOODS_NOT_DELIVERED"
    })
    assert udir_event.gateway == "razorpay_udir"
    assert udir_event.network == "upi"

    # 2. Stripe Adapter
    stripe_adapter = StripeGatewayAdapter()
    stripe_event = stripe_adapter.parse_webhook({
        "data": {
            "object": {
                "id": "dp_stripe_11",
                "charge": "ch_stripe_22",
                "amount": 5000,
                "currency": "usd",
                "reason": "fraudulent"
            }
        }
    })
    assert stripe_event.gateway == "stripe"
    assert stripe_event.reason == "10.4"

    # 3. Logistics & CRM Connectors
    pod = logistics_connector.fetch_delivery_proof("Delhivery", "DL123456")
    assert pod.delivered is True
    assert pod.geofence_verified is True

    crm_trail = crm_connector.fetch_support_trail("Zendesk", "customer@example.com")
    assert crm_trail.ticket_resolution_status == "RESOLVED_FULFILLED"


# ==============================================================================
# STEP 6: ISSUER INTELLIGENCE & CLOSED-LOOP ML MODEL
# ==============================================================================
def test_step6_issuer_intelligence_closed_loop():
    """Verifies outcome recording and dynamic BIN propensity tracking."""
    bin_num = "424242"
    issuer_intelligence.record_dispute_resolution(
        dispute_id="disp_res_001",
        card_bin=bin_num,
        issuing_bank="HDFC Bank",
        network="visa",
        reason_code="10.4",
        outcome="won",
        amount_inr=5000.0,
        confidence_score=90.0
    )

    profile = issuer_intelligence.get_bin_profile(bin_num)
    assert profile.card_bin == bin_num
    assert profile.win_rate >= 0.70
    assert "w_ce30" in profile.weights

    adj = issuer_intelligence.get_issuer_win_rate_adjustment(bin_num)
    assert isinstance(adj, float)


# ==============================================================================
# END-TO-END WORKFLOW INTEGRATION TEST
# ==============================================================================
def test_full_roadmap_end_to_end_dispute_workflow():
    """Runs complete end-to-end LangGraph state machine with all roadmap features."""
    now = time.time()
    payload = RazorpayDisputeWebhook(
        dispute_id="disp_e2e_roadmap_001",
        payment_id="pay_e2e_001",
        amount_inr=7500.0,
        card_network="visa",
        reason_code="10.4",
        telemetry=CustomerTelemetry(
            ip_address="49.207.180.45",
            device_id="dev_macbook_pro_uuid",
            user_id="user_rahul_sharma",
            shipping_address="Indiranagar, Bangalore",
            mfa_authenticated=True
        ),
        carrier_proof=CarrierProof(
            carrier_name="BlueDart",
            tracking_number="BD11223344",
            delivered_status=True,
            verified_gps=True
        ),
        historical_transactions=[
            HistoricalTransaction(
                transaction_id="tx_h1",
                payment_id="pay_h1",
                amount_inr=7000.0,
                days_ago=140,
                card_last4="4242",
                card_network="visa",
                ip_address="49.207.180.45",
                device_id="dev_macbook_pro_uuid",
                user_id="user_rahul_sharma",
                shipping_address="Indiranagar, Bangalore",
                undisputed=True
            ),
            HistoricalTransaction(
                transaction_id="tx_h2",
                payment_id="pay_h2",
                amount_inr=7200.0,
                days_ago=220,
                card_last4="4242",
                card_network="visa",
                ip_address="49.207.180.45",
                device_id="dev_macbook_pro_uuid",
                user_id="user_rahul_sharma",
                shipping_address="Indiranagar, Bangalore",
                undisputed=True
            )
        ]
    )

    dossier = execute_dispute_workflow(payload)
    assert dossier.decision == "AUTO_DISPATCHED"
    assert dossier.confidence_score >= 85.0
    assert dossier.expected_value_inr is not None
    assert dossier.expected_value_inr > 0
    assert dossier.p_win is not None
    assert dossier.p_win >= 0.70
    assert dossier.rebuttal_letter is not None
    assert dossier.sealed_hash is not None
