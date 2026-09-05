import uuid
import time
from typing import Optional, Dict, Any
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status

from app.core.config import settings
from app.core.security import verify_razorpay_webhook, validate_webhook_timestamp
from app.core.logger import get_logger
from app.core.db import db
from app.schemas.dispute import RazorpayDisputeWebhook, Dossier
from app.graphs.dispute_graph import execute_dispute_workflow
from app.services.ledger import ledger
from app.services.queue import DisputeQueueTask, get_dispute_queue

router = APIRouter(prefix="", tags=["Webhooks"])
logger = get_logger("webhook_ingress")

# In-memory fast cache populated lazily or on demand (avoids blocking DB call at import)
_dossiers_cache: Dict[str, Dossier] = {}


def get_dossiers_db() -> Dict[str, Dossier]:
    """
    Lazy getter for the in-memory dossiers cache.
    Prevents cold-start database connection hangs during module import.
    """
    return _dossiers_cache


# Backward compatibility reference
dossiers_db = _dossiers_cache


@router.post("/webhooks/razorpay", status_code=status.HTTP_200_OK)
@router.post("/webhook/dispute", status_code=status.HTTP_200_OK)
@router.post("/webhook", status_code=status.HTTP_200_OK)
async def handle_razorpay_dispute_webhook(
    request: Request,
    x_razorpay_signature: Optional[str] = Header(None, alias="X-Razorpay-Signature"),
    x_razorpay_event_id: Optional[str] = Header(None, alias="X-Razorpay-Event-Id"),
    x_razorpay_event_time: Optional[str] = Header(None, alias="X-Razorpay-Event-Time"),
    x_process_async: Optional[str] = Header(None, alias="X-Process-Async"),
    async_mode: Optional[bool] = Query(None, alias="async")
):
    """
    Production Ingress Point for Razorpay payment.dispute.created webhooks.
    Validates HMAC-SHA256 signature, timestamp tolerance, and replay nonces before invoking deterministic state graph.

    Supports asynchronous Fast-ACK mode:
    - Set header ``X-Process-Async: true`` or query param ``?async=true``
    - Returns HTTP 202 Accepted with ``task_id`` immediately
    - Dispute is processed in a background thread pool
    - Poll ``GET /api/v1/queue/tasks/{task_id}`` for completion status
    """
    correlation_id = str(uuid.uuid4())
    raw_body = await request.body()
    request_async = (x_process_async and x_process_async.lower() == "true") or (async_mode is True)

    # 0. Enforce Payload Size Limit (DDoS / Memory Exhaustion Guard)
    if len(raw_body) > settings.MAX_REQUEST_BODY_BYTES:
        logger.warning(
            "Rejected webhook exceeding maximum body size",
            correlation_id=correlation_id,
            size_bytes=len(raw_body),
            max_bytes=settings.MAX_REQUEST_BODY_BYTES
        )
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Webhook payload exceeds maximum size limit of {settings.MAX_REQUEST_BODY_BYTES // 1024} KB"
        )

    # 1. Verify Razorpay Signature (Authentication first)
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
        if settings.is_production:
            logger.warning("Rejected production webhook: Missing X-Razorpay-Signature header", correlation_id=correlation_id)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing required X-Razorpay-Signature header in production environment"
            )
        logger.info("Webhook received without signature header (dev/testing mode)", correlation_id=correlation_id)

    # 2. Timestamp Freshness / Replay Guard
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
    elif settings.is_production:
        logger.warning("Rejected production webhook: Missing X-Razorpay-Event-Time", correlation_id=correlation_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required X-Razorpay-Event-Time header in production"
        )

    # 3. Event ID Nonce / Replay Guard / State Machine Lifecycle
    if x_razorpay_event_id is not None:
        action, cached_result = db.register_webhook_event(
            event_id=x_razorpay_event_id,
            signature=x_razorpay_signature or "no_signature"
        )
        if action == "COMPLETED":
            logger.info(
                "Duplicate webhook event ID already completed; returning idempotent result",
                correlation_id=correlation_id,
                event_id=x_razorpay_event_id
            )
            return cached_result
        elif action == "PROCESSING":
            logger.warning(
                "Duplicate webhook event currently processing",
                correlation_id=correlation_id,
                event_id=x_razorpay_event_id
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Webhook event ID {x_razorpay_event_id} is currently being processed"
            )

    # 4. Validate Schema
    try:
        payload_dict = await request.json()
        dispute_payload = RazorpayDisputeWebhook.model_validate(payload_dict)
    except Exception as e:
        if x_razorpay_event_id is not None:
            db.fail_webhook_event(x_razorpay_event_id, error_message=f"Schema validation failure: {str(e)}")
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
        },
        event_id=x_razorpay_event_id,
        dispute_id=dispute_payload.dispute_id,
        correlation_id=correlation_id,
        actor="RAZORPAY_WEBHOOK"
    )

    logger.info(
        "Dispute webhook ingested and verified",
        correlation_id=correlation_id,
        dispute_id=dispute_payload.dispute_id,
        payment_id=dispute_payload.payment_id,
        network=dispute_payload.card_network,
        amount=dispute_payload.amount_inr
    )

    # 6a. Async Fast-ACK Path: enqueue and return HTTP 202 immediately
    if request_async:
        task = DisputeQueueTask(
            dispute_id=dispute_payload.dispute_id,
            event_id=x_razorpay_event_id,
            correlation_id=correlation_id
        )
        queue = get_dispute_queue()
        task_id = queue.enqueue(task, payload_dict)

        logger.info(
            "Dispute enqueued for async processing (Fast-ACK)",
            task_id=task_id,
            dispute_id=dispute_payload.dispute_id,
            correlation_id=correlation_id
        )

        return Response(
            content=__import__("json").dumps({
                "status": "accepted",
                "correlation_id": correlation_id,
                "task_id": task_id,
                "dispute_id": dispute_payload.dispute_id,
                "message": "Dispute accepted for background processing. Poll GET /api/v1/queue/tasks/{task_id} for status."
            }),
            status_code=status.HTTP_202_ACCEPTED,
            media_type="application/json"
        )

    # 6b. Synchronous Execution Path (default)
    try:
        dossier = execute_dispute_workflow(dispute_payload)
        get_dossiers_db()[dossier.dispute_id] = dossier
        db.save_dossier(dossier, dispute_payload)

        result_payload = {
            "status": "success",
            "correlation_id": correlation_id,
            "dispute_id": dossier.dispute_id,
            "payment_id": dossier.payment_id,
            "decision": dossier.decision,
            "confidence_score": dossier.confidence_score,
            "sealed_hash": dossier.sealed_hash,
            "summary": dossier.summary
        }

        if x_razorpay_event_id is not None:
            db.complete_webhook_event(x_razorpay_event_id, result_payload)

        return result_payload
    except Exception as e:
        if x_razorpay_event_id is not None:
            db.fail_webhook_event(x_razorpay_event_id, error_message=str(e))
        raise


@router.get("/queue/tasks/{task_id}")
async def get_queue_task_status(task_id: str):
    """Poll endpoint for async dispute processing task status."""
    queue = get_dispute_queue()
    task = queue.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task.model_dump()


