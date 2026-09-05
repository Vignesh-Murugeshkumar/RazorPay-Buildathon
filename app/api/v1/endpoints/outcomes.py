from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.services.issuer_intelligence import issuer_intelligence, BINProfile
from app.core.db import db
from app.core.logger import get_logger

router = APIRouter(prefix="/disputes", tags=["Dispute Outcomes & Issuer Intelligence"])
logger = get_logger("outcomes_endpoints")


class DisputeOutcomeWebhook(BaseModel):
    event: str = Field(default="payment.dispute.won", description="payment.dispute.won | payment.dispute.lost")
    dispute_id: str = Field(..., description="Dispute ID")
    card_bin: Optional[str] = Field(default="424242", description="First 6 digits of card")
    issuing_bank: Optional[str] = Field(default="Synthetic Issuer A", description="Name of issuing bank")
    network: str = Field(default="visa", description="visa | mastercard | rupay")
    reason_code: str = Field(default="10.4", description="Dispute reason code")
    outcome: Optional[str] = Field(None, description="won | lost")
    amount_inr: float = Field(default=1000.0, description="Dispute amount")
    confidence_score: float = Field(default=85.0, description="Dossier confidence score at submission")
    evidence_types_used: List[str] = Field(default_factory=lambda: ["ce30", "carrier_proof"])


@router.post("/outcome", status_code=status.HTTP_200_OK)
async def record_dispute_resolution_outcome(payload: DisputeOutcomeWebhook):
    """
    Ingests payment gateway resolution outcomes (payment.dispute.won / payment.dispute.lost).
    Feeds closed-loop ML model and updates BIN-level propensity scores and adaptive weights.
    """
    outcome_val = payload.outcome
    if not outcome_val:
        outcome_val = "won" if "won" in payload.event.lower() else "lost"

    result = issuer_intelligence.record_dispute_resolution(
        dispute_id=payload.dispute_id,
        card_bin=payload.card_bin or "424242",
        issuing_bank=payload.issuing_bank or "Global Issuing Bank",
        network=payload.network,
        reason_code=payload.reason_code,
        outcome=outcome_val,
        amount_inr=payload.amount_inr,
        confidence_score=payload.confidence_score,
        evidence_types_used=payload.evidence_types_used
    )

    db.add_timeline_event(
        dispute_id=payload.dispute_id,
        event_type="OUTCOME_RECORDED",
        title=f"Dispute Resolution: {outcome_val.upper()}",
        description=f"Dispute officially marked {outcome_val.upper()} by gateway. Closed-loop ML prior updated for BIN {payload.card_bin}.",
        metadata={"outcome": outcome_val, "card_bin": payload.card_bin, "issuing_bank": payload.issuing_bank}
    )

    return {
        "status": "success",
        "message": "Dispute outcome ingested into closed-loop ML engine",
        "details": result
    }


@router.get("/issuer-intelligence/profile/{card_bin}", response_model=BINProfile)
async def get_bin_intelligence_profile(card_bin: str):
    """
    Retrieves BIN-level empirical win-rate profile, preferred evidence, and dynamic feature weights.
    """
    return issuer_intelligence.get_bin_profile(card_bin)


@router.get("/issuer-intelligence/all")
async def get_all_issuer_profiles():
    """
    Returns summary of all known BIN intelligence profiles.
    """
    bins = ["424242", "512345", "400000", "543210"]
    profiles = [issuer_intelligence.get_bin_profile(b) for b in bins]
    return {
        "tracked_bins": len(profiles),
        "profiles": profiles
    }
