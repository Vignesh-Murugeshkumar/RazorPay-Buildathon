from typing import TypedDict, Optional, Dict, Any, List
from app.schemas.dispute import (
    RazorpayDisputeWebhook,
    RuleEvaluationResult,
    Dossier
)


class DisputeState(TypedDict, total=False):
    """
    TypedDict state schema governing the deterministic LangGraph agent state machine.
    Passed across Triage, Aggregator, Compliance, and Gatekeeper nodes.
    """
    # Ingress & Core Identifiers
    payload: RazorpayDisputeWebhook
    dispute_id: str
    payment_id: str
    network: str
    reason_code: str
    amount_inr: float
    due_by: Optional[int]
    correlation_id: str

    # Aggregator Extraction Flags
    telemetry_extracted: bool
    carrier_verified: bool
    historical_lookback_count: int

    # Evaluation & Scoring
    evaluation: Optional[RuleEvaluationResult]
    confidence_score: float

    # Gatekeeper Decision & Dossier
    decision: str  # "AUTO_DISPATCHED" | "ROUTE_TO_HITL_QUEUE"
    dossier: Optional[Dossier]

    # Cryptographic Hash Chain Audit State
    genesis_hash: str
    latest_block_hash: str

    # Observability & Trace Logs
    logs: List[str]
    errors: List[str]
