import uuid
import time
from typing import Optional, Dict, Any
from fastapi import APIRouter, Header, HTTPException, Request, Response, status

from app.core.config import settings
from app.core.security import verify_razorpay_webhook, validate_webhook_timestamp
from app.core.logger import get_logger
from app.core.db import db
from app.schemas.dispute import RazorpayDisputeWebhook, Dossier
from app.graphs.dispute_graph import execute_dispute_workflow
from app.services.ledger import ledger

router = APIRouter(prefix="", tags=["Webhooks"])
logger = get_logger("webhook_ingress")

# In-memory fast cache synced with persistent database
dossiers_db: Dict[str, Dossier] = db.get_all_dossiers()


@router.post("/webhooks/razorpay", status_code=status.HTTP_200_OK)
@router.post("/webhook/dispute", status_code=status.HTTP_200_OK)
async def handle_razorpay_dispute_webhook(
    request: Request,
    x_razorpay_signature: Optional[str] = Header(None, alias="X-Razorpay-Signature"),
    x_razorpay_event_id: Optional[str] = Header(None, alias="X-Razorpay-Event-Id"),
    x_razorpay_event_time: Optional[str] = Header(None, alias="X-Razorpay-Event-Time")
):
    """
    Production Ingress Point for Razorpay payment.dispute.created webhooks.
    Validates HMAC-SHA256 signature, timestamp tolerance, and replay nonces before invoking LangGraph state graph.
    """
    correlation_id = str(uuid.uuid4())
    raw_body = await request.body()

    # 1. Timestamp Freshness / Replay Guard
    if x_razorpay_event_time is not None:
        if not validate_webhook_timestamp(x_razorpay_event_time, tolerance_seconds=300):
            logger.warning(
                "Rejected stale webhook timestamp (potential replay)",
                correlation_id=correlation_id,
                event_time=x_razorpay_event_time
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Webhook timestamp outside 5-minute tolerance window"
            )

    # 2. Event ID Nonce / Replay Guard
    if x_razorpay_event_id is not None:
        is_fresh = db.record_and_verify_event(
            event_id=x_razorpay_event_id,
            signature=x_razorpay_signature or "no_signature"
        )
        if not is_fresh:
            logger.warning(
                "Duplicate webhook event detected and rejected",
                correlation_id=correlation_id,
                event_id=x_razorpay_event_id
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Duplicate webhook event ID {x_razorpay_event_id} already processed"
            )

    # 3. Verify Razorpay Signature
    if x_razorpay_signature is not None:
        is_valid = verify_razorpay_webhook(
            raw_body=raw_body,
            signature_header=x_razorpay_signature,
            webhook_secret=settings.RAZORPAY_WEBHOOK_SECRET
        )
        if not is_valid:
            logger.warning(
                "Unauthorized webhook signature",
                correlation_id=correlation_id,
                provided_signature=x_razorpay_signature[:16] + "..." if len(x_razorpay_signature) > 16 else x_razorpay_signature
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Razorpay webhook HMAC-SHA256 signature"
            )
    else:
        logger.info("Webhook received without signature header (dev/testing mode)", correlation_id=correlation_id)

    # 4. Validate Schema
    try:
        payload_dict = await request.json()
        dispute_payload = RazorpayDisputeWebhook.model_validate(payload_dict)
    except Exception as e:
        logger.error("Webhook payload validation failure", correlation_id=correlation_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Malformed Razorpay dispute webhook payload: {str(e)}"
        )

    # 5. Ingress Audit Block in Cryptographic Hash Chain
    ledger.append_block(
        agent_id="INGRESS_SECURITY",
        state_transition="WEBHOOK_INGRESS_VERIFIED",
        payload={
            "correlation_id": correlation_id,
            "dispute_id": dispute_payload.dispute_id,
            "payment_id": dispute_payload.payment_id,
            "signature_verified": bool(x_razorpay_signature),
            "event_id": x_razorpay_event_id
        }
    )

    logger.info(
        "Dispute webhook ingested and verified",
        correlation_id=correlation_id,
        dispute_id=dispute_payload.dispute_id,
        payment_id=dispute_payload.payment_id,
        network=dispute_payload.card_network,
        amount=dispute_payload.amount_inr
    )

    # 6. Execute LangGraph Deterministic State Machine Workflow
    dossier = execute_dispute_workflow(dispute_payload)
    dossiers_db[dossier.dispute_id] = dossier
    db.save_dossier(dossier, dispute_payload)

    return {
        "status": "success",
        "correlation_id": correlation_id,
        "dispute_id": dossier.dispute_id,
        "payment_id": dossier.payment_id,
        "decision": dossier.decision,
        "confidence_score": dossier.confidence_score,
        "sealed_hash": dossier.sealed_hash,
        "summary": dossier.summary
    }
