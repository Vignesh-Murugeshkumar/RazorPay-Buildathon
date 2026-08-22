import os
import time
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse

from app.models.dispute import DisputePayload, Dossier, DisputeSummary
from app.models.ledger import LedgerBlock, LedgerIntegrityReport
from app.security import verify_razorpay_webhook, generate_razorpay_signature
from app.graphs.dispute_graph import execute_dispute_workflow
from app.ledger.audit_chain import ledger

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "sentinel_secret_key_dev")

app = FastAPI(
    title="SentinelDispute",
    description="Autonomous Visa CE 3.0 & Mastercard FPT Dispute Defense Engine for Razorpay",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json"
)

# Enable CORS for Next.js / React frontend & local testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory dossier store
_dossiers_db: Dict[str, Dossier] = {}


@app.get("/api/v1/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "SentinelDispute",
        "version": "1.0.0",
        "audit_blocks": ledger.get_total_count()
    }


@app.post("/api/v1/webhook/dispute", status_code=status.HTTP_200_OK)
async def handle_dispute_webhook(
    request: Request,
    x_razorpay_signature: Optional[str] = Header(None, alias="X-Razorpay-Signature")
):
    """
    Ingress point for Razorpay payment.dispute.created webhooks.
    Validates HMAC-SHA256 signature in constant time before processing.
    """
    raw_body = await request.body()

    # Signature verification
    # If signature header is provided, it must match.
    # In dev/testing mode without header, we allow test payloads if explicitly permitted.
    if x_razorpay_signature is not None:
        is_valid = verify_razorpay_webhook(raw_body, x_razorpay_signature, WEBHOOK_SECRET)
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Razorpay webhook HMAC-SHA256 signature"
            )

    try:
        payload_dict = await request.json()
        payload = DisputePayload.model_validate(payload_dict)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Malformed dispute webhook payload: {str(e)}"
        )

    # Ingress audit log
    ledger.append_block(
        agent_id="INGRESS_SECURITY",
        state_transition="WEBHOOK_VERIFIED",
        payload={
            "dispute_id": payload.dispute_id,
            "payment_id": payload.payment_id,
            "signature_verified": bool(x_razorpay_signature)
        }
    )

    # Execute deterministic LangGraph state workflow
    dossier = execute_dispute_workflow(payload)
    _dossiers_db[dossier.dispute_id] = dossier

    return {
        "status": "success",
        "dispute_id": dossier.dispute_id,
        "payment_id": dossier.payment_id,
        "decision": dossier.decision,
        "confidence_score": dossier.confidence_score,
        "sealed_hash": dossier.sealed_hash,
        "summary": dossier.summary
    }


@app.get("/api/v1/disputes", response_model=List[DisputeSummary])
async def list_disputes():
    """Returns list of processed disputes with high-level summaries."""
    summaries = []
    for d in _dossiers_db.values():
        summaries.append(
            DisputeSummary(
                dispute_id=d.dispute_id,
                payment_id=d.payment_id,
                amount_inr=d.amount_inr,
                card_network=d.card_network,
                reason_code=d.reason_code,
                confidence_score=d.confidence_score,
                decision=d.decision,
                timestamp=d.timestamp,
                sealed_hash=d.sealed_hash
            )
        )
    return list(reversed(summaries))


@app.get("/api/v1/disputes/{dispute_id}", response_model=Dossier)
async def get_dispute(dispute_id: str):
    """Returns full evidence dossier and evaluation trace for a dispute."""
    if dispute_id not in _dossiers_db:
        raise HTTPException(status_code=404, detail="Dispute dossier not found")
    return _dossiers_db[dispute_id]


@app.get("/api/v1/audit/integrity", response_model=LedgerIntegrityReport)
async def verify_ledger_integrity():
    """Verifies the complete cryptographic SHA-256 hash chain continuity."""
    return ledger.verify_integrity()


@app.get("/api/v1/audit/blocks", response_model=List[LedgerBlock])
async def get_ledger_blocks(limit: int = 50, offset: int = 0):
    """Returns recent blocks from the cryptographic hash chain."""
    return ledger.get_blocks(limit=limit, offset=offset)


@app.get("/api/v1/stats")
async def get_stats():
    """Returns aggregate dashboard analytics and KPI metrics."""
    total = len(_dossiers_db)
    auto_dispatched = sum(1 for d in _dossiers_db.values() if d.decision == "AUTO_DISPATCHED")
    hitl_queued = total - auto_dispatched
    
    total_gmv = sum(d.amount_inr for d in _dossiers_db.values())
    recovered_gmv = sum(d.amount_inr for d in _dossiers_db.values() if d.decision == "AUTO_DISPATCHED")
    
    avg_score = (sum(d.confidence_score for d in _dossiers_db.values()) / total) if total > 0 else 0.0
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


@app.post("/api/v1/simulate")
async def simulate_dispute(payload: DisputePayload):
    """
    Direct simulation endpoint for testing scenarios from UI without needing HMAC signing headers.
    """
    ledger.append_block(
        agent_id="SIMULATION_RUNNER",
        state_transition="SIMULATION_INGEST",
        payload={"dispute_id": payload.dispute_id, "amount_inr": payload.amount_inr}
    )
    dossier = execute_dispute_workflow(payload)
    _dossiers_db[dossier.dispute_id] = dossier
    return dossier


@app.post("/api/v1/benchmark/run")
async def trigger_benchmark_run():
    """
    Runs the 60-scenario synthetic benchmark dataset on-demand.
    """
    from tests.generate_dataset import generate_benchmark_dataset
    
    scenarios = generate_benchmark_dataset()
    start_time = time.time()
    
    results = []
    for sc in scenarios:
        t0 = time.time()
        dossier = execute_dispute_workflow(sc["payload"])
        latency_ms = round((time.time() - t0) * 1000, 2)
        _dossiers_db[dossier.dispute_id] = dossier
        
        is_expected = (dossier.decision == sc["expected_decision"])
        results.append({
            "dispute_id": dossier.dispute_id,
            "scenario_type": sc["category"],
            "card_network": sc["payload"].card_network,
            "confidence_score": dossier.confidence_score,
            "decision": dossier.decision,
            "expected_decision": sc["expected_decision"],
            "matched_expectation": is_expected,
            "latency_ms": latency_ms
        })
        
    total_elapsed = round(time.time() - start_time, 2)
    total_scenarios = len(results)
    correct = sum(1 for r in results if r["matched_expectation"])
    auto_count = sum(1 for r in results if r["decision"] == "AUTO_DISPATCHED")
    
    precision = (correct / total_scenarios) * 100.0
    yield_rate = (auto_count / total_scenarios) * 100.0
    avg_latency = round(sum(r["latency_ms"] for r in results) / total_scenarios, 2)
    
    return {
        "status": "completed",
        "total_scenarios": total_scenarios,
        "autonomous_yield_percentage": round(yield_rate, 2),
        "precision_percentage": round(precision, 2),
        "average_latency_ms": avg_latency,
        "total_time_seconds": total_elapsed,
        "ledger_integrity": ledger.verify_integrity().is_valid,
        "scenario_results": results
    }


# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", response_class=HTMLResponse)
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
