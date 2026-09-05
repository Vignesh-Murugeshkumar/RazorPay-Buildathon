import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse

from app.core.config import settings
from app.core.logger import get_logger
from app.api import api_v1_router
from app.api.v1.endpoints.webhooks import get_dossiers_db, dossiers_db
from app.schemas.dispute import (
    RazorpayDisputeWebhook,
    DisputePayload,
    Dossier,
    DisputeSummary
)
from app.services.ledger import (
    LedgerBlock,
    LedgerIntegrityReport,
    ledger
)
from app.graphs.dispute_graph import execute_dispute_workflow

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI Lifespan Context Manager.
    Validates production readiness, initializes services, and gracefully cleans up pools.
    """
    # Enforce production security check on boot (log warning if default credentials)
    try:
        settings.validate_production_readiness()
    except Exception as e:
        logger.warning("Production readiness check notice", warning=str(e))

    logger.info(
        "Initializing SentinelDispute Engine",
        environment=settings.ENVIRONMENT,
        version=settings.PROJECT_VERSION,
        audit_blocks=len(ledger.chain)
    )
    yield
    logger.info("Shutting down SentinelDispute Engine")
    try:
        from app.core.db import db as _db
        _db.close()
    except Exception:
        pass



app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Autonomous Visa CE 3.0 & Mastercard FPT Dispute Defense Engine for Razorpay",
    version=settings.PROJECT_VERSION,
    docs_url="/docs",
    openapi_url="/openapi.json",
    lifespan=lifespan
)

# Production Security Headers & Correlation ID Middleware
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-Id") or str(uuid.uuid4())
    request.state.correlation_id = correlation_id
    response: Response = await call_next(request)
    response.headers["X-Correlation-Id"] = correlation_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# Global Sanitized Exception Handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    logger.error("Unhandled internal server exception", correlation_id=correlation_id, path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal Server Error",
            "message": "An unexpected error occurred while processing your request.",
            "correlation_id": correlation_id
        }
    )


# Hardened CORS Middleware
cors_origins = settings.get_cors_origins()
allow_creds = "*" not in cors_origins  # Wildcard with credentials violates CORS standards

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=allow_creds,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Modular API Routers
app.include_router(api_v1_router)

# Direct root-level webhook routing (supports Razorpay dashboard URLs configured as /webhooks/razorpay)
from app.api.v1.endpoints.webhooks import router as webhooks_root_router
app.include_router(webhooks_root_router)


@app.get("/api/v1/health", tags=["System"])
async def health_check(response: Response):
    """Deep production health check: verifies application, database ping, and ledger integrity."""
    from app.core.db import db as _db
    db_status = _db.ping()
    integrity = ledger.verify_integrity()

    is_healthy = db_status.get("healthy", False) and integrity.is_valid
    if not is_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "healthy" if is_healthy else "degraded",
        "service": settings.PROJECT_NAME,
        "version": settings.PROJECT_VERSION,
        "environment": settings.ENVIRONMENT,
        "database": db_status,
        "audit_ledger": {
            "total_blocks": ledger.get_total_count(),
            "integrity_verified": integrity.is_valid
        }
    }


@app.get("/api/v1/disputes", response_model=List[DisputeSummary], tags=["Disputes"])
async def list_disputes():
    """Returns list of processed disputes with summaries.
    
    Reads from persistent DB on every call to ensure consistency across
    serverless instances and after cold starts (fixes stale in-memory cache issue).
    """
    from app.core.db import db as _db
    all_dossiers = _db.get_all_dossiers()
    # Keep in-memory cache warm for other endpoints that still use it
    get_dossiers_db().update(all_dossiers)
    summaries = [
        DisputeSummary(
            dispute_id=d.dispute_id,
            payment_id=d.payment_id,
            amount_inr=d.amount_inr,
            card_network=d.card_network,
            reason_code=d.reason_code,
            confidence_score=d.confidence_score,
            decision=d.decision,
            timestamp=d.timestamp,
            sealed_hash=d.sealed_hash,
            expected_value_inr=d.expected_value_inr,
            p_win=d.p_win,
            win_probability=d.win_probability if d.win_probability is not None else d.p_win,
            expected_value=d.expected_value if d.expected_value is not None else d.expected_value_inr,
            assigned_to=d.assigned_to
        )
        for d in all_dossiers.values()
    ]
    return list(reversed(summaries))


from app.core.db import db
from app.schemas.dispute import (
    RazorpayDisputeWebhook,
    DisputePayload,
    Dossier,
    DisputeSummary,
    CarrierProof
)
from app.schemas.remediation import RemediationEvidencePayload


@app.get("/api/v1/disputes/{dispute_id}", response_model=Dossier, tags=["Disputes"])
async def get_dispute(dispute_id: str):
    """
    Returns full evidence dossier and evaluation trace.
    PostgreSQL/SQLite database is the authoritative source of truth.
    """
    dossier = db.get_dossier(dispute_id)
    if dossier:
        get_dossiers_db()[dispute_id] = dossier
        return dossier
    # Optional fallback if DB was bypassed in lightweight mock test
    cache = get_dossiers_db()
    if dispute_id in cache:
        return cache[dispute_id]
    raise HTTPException(status_code=404, detail="Dispute dossier not found")


@app.post("/api/v1/disputes/{dispute_id}/remediate", response_model=Dossier, tags=["Disputes"])
async def remediate_dispute_evidence(dispute_id: str, remediation: RemediationEvidencePayload):
    """
    Human-in-the-Loop (HITL) Evidence Remediation:
    Allows analysts to supply missing carrier proof, GPS telemetry, MFA verification, or SaaS logs.
    Re-runs the deterministic compliance engine and auto-dispatches if Sc >= 85.0.
    """
    raw_payload = db.get_raw_payload(dispute_id)
    if not raw_payload:
        cache = get_dossiers_db()
        if dispute_id in cache:
            d = cache[dispute_id]
            raw_payload = RazorpayDisputeWebhook(
                dispute_id=d.dispute_id,
                payment_id=d.payment_id,
                amount_inr=d.amount_inr,
                card_network=d.card_network,
                reason_code=d.reason_code,
                telemetry=d.telemetry,
                carrier_proof=d.carrier_proof,
                digital_proof=d.digital_proof
            )
        else:
            raise HTTPException(status_code=404, detail=f"Dispute {dispute_id} not found for remediation")

    # Update Carrier Proof
    if remediation.delivered_status is not None or remediation.tracking_number is not None:
        if raw_payload.carrier_proof is None:
            raw_payload.carrier_proof = CarrierProof(
                carrier_name=remediation.carrier_name,
                tracking_number=remediation.tracking_number,
                delivered_status=remediation.delivered_status if remediation.delivered_status is not None else False,
                recipient_signature_present=remediation.recipient_signature_present if remediation.recipient_signature_present is not None else False,
                gps_latitude=remediation.gps_latitude,
                gps_longitude=remediation.gps_longitude,
                verified_gps=remediation.verified_gps if remediation.verified_gps is not None else (remediation.gps_latitude is not None)
            )
        else:
            if remediation.carrier_name:
                raw_payload.carrier_proof.carrier_name = remediation.carrier_name
            if remediation.tracking_number:
                raw_payload.carrier_proof.tracking_number = remediation.tracking_number
            if remediation.delivered_status is not None:
                raw_payload.carrier_proof.delivered_status = remediation.delivered_status
            if remediation.recipient_signature_present is not None:
                raw_payload.carrier_proof.recipient_signature_present = remediation.recipient_signature_present
            if remediation.gps_latitude is not None:
                raw_payload.carrier_proof.gps_latitude = remediation.gps_latitude
            if remediation.gps_longitude is not None:
                raw_payload.carrier_proof.gps_longitude = remediation.gps_longitude
            if remediation.verified_gps is not None:
                raw_payload.carrier_proof.verified_gps = remediation.verified_gps

    # Update Telemetry
    if remediation.mfa_authenticated is not None:
        raw_payload.telemetry.mfa_authenticated = remediation.mfa_authenticated
    if remediation.user_id_confirmed:
        raw_payload.telemetry.user_id = remediation.user_id_confirmed
    if remediation.ip_address_confirmed:
        raw_payload.telemetry.ip_address = remediation.ip_address_confirmed

    # Update Digital Proof if provided
    if remediation.digital_access_logs_verified is not None:
        raw_payload.service_type = "digital_saas"
        from app.schemas.dispute import DigitalFulfillmentProof
        raw_payload.digital_proof = DigitalFulfillmentProof(
            access_logs_verified=remediation.digital_access_logs_verified,
            ip_subnet_matched=remediation.digital_ip_subnet_matched if remediation.digital_ip_subnet_matched is not None else True,
            user_account_active=True
        )

    # Append HITL Audit Block
    ledger.append_block(
        agent_id=f"HITL_{remediation.analyst_id}",
        state_transition="EVIDENCE_REMEDIATED",
        payload={
            "dispute_id": dispute_id,
            "analyst_id": remediation.analyst_id,
            "notes": remediation.analyst_notes,
            "carrier_verified": bool(raw_payload.carrier_proof and raw_payload.carrier_proof.delivered_status),
            "mfa_verified": raw_payload.telemetry.mfa_authenticated,
            "gps_verified": bool(raw_payload.carrier_proof and raw_payload.carrier_proof.verified_gps)
        }
    )

    # Re-evaluate through deterministic workflow
    dossier = execute_dispute_workflow(raw_payload)
    get_dossiers_db()[dossier.dispute_id] = dossier
    db.save_dossier(dossier, raw_payload)
    
    logger.info(
        "Remediation processed for dispute",
        dispute_id=dispute_id,
        new_score=dossier.confidence_score,
        new_decision=dossier.decision
    )
    return dossier


@app.get("/api/v1/audit/integrity", response_model=LedgerIntegrityReport, tags=["Audit Ledger"])
async def verify_ledger_integrity():
    """Verifies complete SHA-256 hash chain continuity from genesis to head."""
    return ledger.verify_integrity()


@app.get("/api/v1/audit/blocks", response_model=List[LedgerBlock], tags=["Audit Ledger"])
async def get_ledger_blocks(limit: int = 50, offset: int = 0):
    """Returns recent blocks from the cryptographic ledger."""
    return ledger.get_blocks(limit=limit, offset=offset)


@app.get("/api/v1/stats", tags=["Analytics"])
async def get_stats():
    """Returns aggregate dashboard metrics, yield rates, and protected GMV.
    
    Reads from persistent DB on every call to ensure accuracy across
    serverless instances (fixes stale in-memory cache divergence).
    """
    from app.core.db import db as _db
    all_dossiers = _db.get_all_dossiers()
    # Keep in-memory cache warm
    dossiers_db.update(all_dossiers)

    total = len(all_dossiers)
    auto_dispatched = sum(1 for d in all_dossiers.values() if d.decision == "AUTO_DISPATCHED")
    hitl_queued = total - auto_dispatched

    total_gmv = sum(d.amount_inr for d in all_dossiers.values())
    recovered_gmv = sum(d.amount_inr for d in all_dossiers.values() if d.decision == "AUTO_DISPATCHED")

    avg_score = (sum(d.confidence_score for d in all_dossiers.values()) / total) if total > 0 else 0.0
    yield_rate = (auto_dispatched / total * 100.0) if total > 0 else 0.0

    integrity = ledger.verify_integrity()

    return {
        "total_disputes": total,
        "auto_dispatched_count": auto_dispatched,
        "hitl_count": hitl_queued,
        "autonomous_yield_percentage": round(yield_rate, 2),
        "total_disputed_gmv_inr": round(total_gmv, 2),
        "recovered_gmv_inr": round(recovered_gmv, 2),
        "average_confidence_score": round(avg_score, 2),
        "total_ledger_blocks": ledger.get_total_count(),
        "ledger_integrity_verified": integrity.is_valid
    }


@app.post("/api/v1/simulate", tags=["Simulation"])
async def simulate_dispute(payload: RazorpayDisputeWebhook):
    """Direct scenario simulation runner."""
    ledger.append_block(
        agent_id="SIMULATION_RUNNER",
        state_transition="SIMULATION_INGEST",
        payload={"dispute_id": payload.dispute_id, "amount_inr": payload.amount_inr}
    )
    dossier = execute_dispute_workflow(payload)
    dossiers_db[dossier.dispute_id] = dossier
    db.save_dossier(dossier, payload)
    return dossier


@app.post("/api/v1/benchmark/run", tags=["Simulation"])
async def trigger_benchmark_run():
    """Runs rigorous 115-scenario held-out benchmark evaluation dataset across categories A-P."""
    from tests.run_benchmark import run_benchmark
    
    benchmark_report = run_benchmark()
    
    return {
        "status": "completed",
        "total_scenarios": benchmark_report["total_scenarios"],
        "confusion_matrix": benchmark_report["confusion_matrix"],
        "precision_percentage": round(benchmark_report["precision"], 2),
        "recall_percentage": round(benchmark_report["recall"], 2),
        "f1_score": round(benchmark_report["f1"], 2),
        "accuracy_percentage": round(benchmark_report["accuracy"], 2),
        "false_positive_rate": round(benchmark_report["fpr"], 2),
        "total_disputed_gmv_inr": benchmark_report["total_disputed_gmv"],
        "correctly_recovered_gmv_inr": benchmark_report["correctly_recovered_gmv"],
        "false_positive_financial_cost_inr": benchmark_report["false_positive_financial_cost"],
        "autonomous_yield_percentage": round((benchmark_report["confusion_matrix"]["tp"] + benchmark_report["confusion_matrix"]["fp"]) / benchmark_report["total_scenarios"] * 100.0, 2),
        "hitl_rate_percentage": round(benchmark_report["hitl_rate"], 2),
        "ai_grounding_rate": round(benchmark_report["ai_grounding_rate"], 2),
        "p50_latency_ms": round(benchmark_report["p50_latency_ms"], 2),
        "p95_latency_ms": round(benchmark_report["p95_latency_ms"], 2),
        "ledger_integrity": benchmark_report["ledger_integrity"]
    }


# Mount Static Files & Dashboard UI
_base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
static_dir = os.path.join(_base_dir, "static")
if not os.path.exists(static_dir):
    static_dir = os.path.abspath("static")

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/favicon.ico", include_in_schema=False)
@app.get("/favicon.png", include_in_schema=False)
async def favicon():
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_index():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(
        content="""
        <html>
            <head><title>SentinelDispute API</title></head>
            <body style="background:#0f172a;color:#f8fafc;font-family:sans-serif;padding:40px;">
                <h1>🛡️ SentinelDispute Engine</h1>
                <p>Autonomous Visa CE 3.0 & Mastercard FPT Dispute Defense for Razorpay.</p>
                <p><a href="/docs" style="color:#38bdf8;">View Swagger API Documentation &rarr;</a></p>
            </body>
        </html>
        """
    )

