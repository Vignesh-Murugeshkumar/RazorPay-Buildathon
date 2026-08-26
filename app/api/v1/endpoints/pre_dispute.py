import time
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.core.redis_telemetry import telemetry_hot_cache
from app.core.db import db
from app.core.logger import get_logger
from app.services.pre_dispute import handle_pre_dispute_inquiry, PreDisputeInquiry

router = APIRouter(prefix="/pre-dispute", tags=["Pre-Dispute Interception"])
logger = get_logger("pre_dispute_endpoints")


class IngestTelemetryRequest(BaseModel):
    card_fingerprint: str = Field(..., description="Card token or SHA-256 fingerprint")
    customer_id: str = Field(..., description="Customer ID")
    ip_address: str = Field(..., description="Session IP Address")
    device_fingerprint: str = Field(..., description="Device ID or Fingerprint")
    shipping_address: str = Field(..., description="Shipping Address")
    amount_inr: float = Field(default=1000.0, description="Transaction Amount in INR")
    days_ago: Optional[int] = Field(None, description="Simulate historical transaction days ago (e.g. 180)")
    transaction_time: Optional[float] = Field(None, description="Unix timestamp of transaction")
    transaction_id: Optional[str] = Field(None, description="Optional Transaction ID")
    undisputed: bool = Field(default=True, description="Whether transaction was undisputed")


@router.post("/inquiry", status_code=status.HTTP_200_OK)
async def process_unified_pre_dispute_inquiry(inquiry: PreDisputeInquiry):
    """
    Unified Network Pre-Dispute Interception Handler.
    Evaluates historical credentials in hot cache and responds within <= 2s SLA.
    """
    result = await handle_pre_dispute_inquiry(inquiry.model_dump())
    return result


@router.post("/verifi", status_code=status.HTTP_200_OK)
async def handle_verifi_order_insight_webhook(request: Request):
    """
    Verifi Order Insight (Visa) Webhook Ingress.
    Responds deterministically within <= 2s SLA with CE 3.0 fulfillment data.
    """
    payload = await request.json()
    payload["network"] = "visa"
    if "inquiry_id" not in payload:
        payload["inquiry_id"] = payload.get("order_insight_id", f"verifi_{int(time.time()*1000)}")
    result = await handle_pre_dispute_inquiry(payload)
    return result


@router.post("/ethoca", status_code=status.HTTP_200_OK)
async def handle_ethoca_alerts_webhook(request: Request):
    """
    Ethoca Alerts / Consumer Clarity (Mastercard) Webhook Ingress.
    """
    payload = await request.json()
    payload["network"] = "mastercard"
    if "inquiry_id" not in payload:
        payload["inquiry_id"] = payload.get("alert_id", f"ethoca_{int(time.time()*1000)}")
    result = await handle_pre_dispute_inquiry(payload)
    return result


@router.post("/telemetry/ingest", status_code=status.HTTP_201_CREATED)
async def ingest_customer_telemetry(payload: IngestTelemetryRequest):
    """
    Ingests customer order telemetry into Dual-Tier Hot (Redis) and Cold (Postgres/SQLite) stores.
    Supports 365-day sliding TTL for fast lookups.
    """
    now = time.time()
    tx_time = payload.transaction_time
    if tx_time is None:
        if payload.days_ago is not None:
            tx_time = now - (payload.days_ago * 86400)
        else:
            tx_time = now

    record = telemetry_hot_cache.record_transaction(
        card_fingerprint=payload.card_fingerprint,
        customer_id=payload.customer_id,
        ip_address=payload.ip_address,
        device_fingerprint=payload.device_fingerprint,
        shipping_address=payload.shipping_address,
        amount_inr=payload.amount_inr,
        transaction_time=tx_time,
        transaction_id=payload.transaction_id,
        undisputed=payload.undisputed
    )

    # Ingest into cold storage
    import uuid
    from datetime import datetime, timezone
    rec_id = str(uuid.uuid4())
    tx_iso = datetime.fromtimestamp(tx_time, tz=timezone.utc).isoformat()
    addr_hash = telemetry_hot_cache.hash_identifier(payload.shipping_address)

    db.insert_customer_telemetry(
        record_id=rec_id,
        card_fingerprint=payload.card_fingerprint,
        customer_id=payload.customer_id,
        ip_address=payload.ip_address,
        device_fingerprint=payload.device_fingerprint,
        shipping_address_hash=addr_hash,
        transaction_time_iso=tx_iso,
        dispute_status="undisputed" if payload.undisputed else "disputed",
        amount_inr=payload.amount_inr,
        payload=record
    )

    return {
        "status": "success",
        "record_id": rec_id,
        "transaction_id": record["transaction_id"],
        "transaction_time": tx_time,
        "days_ago": payload.days_ago or 0,
        "message": "Telemetry record stored in hot and cold tiers with 365-day lookback index."
    }
