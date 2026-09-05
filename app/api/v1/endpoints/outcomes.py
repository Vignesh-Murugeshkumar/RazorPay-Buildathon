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


@router.post("/outcomes/batch", status_code=status.HTTP_200_OK)
async def batch_record_dispute_outcomes(payload: Dict[str, List[DisputeOutcomeWebhook]]):
    """
    Ingests batch historical dispute resolution outcomes (e.g. from gateway settlement reports or archives).
    """
    items = payload.get("outcomes", [])
    if not items:
        raise HTTPException(status_code=400, detail="Empty outcomes list provided.")

    ingested = 0
    for item in items:
        outcome_val = item.outcome
        if not outcome_val:
            outcome_val = "won" if "won" in item.event.lower() else "lost"

        issuer_intelligence.record_dispute_resolution(
            dispute_id=item.dispute_id,
            card_bin=item.card_bin or "424242",
            issuing_bank=item.issuing_bank or "Global Issuing Bank",
            network=item.network,
            reason_code=item.reason_code,
            outcome=outcome_val,
            amount_inr=item.amount_inr,
            confidence_score=item.confidence_score,
            evidence_types_used=item.evidence_types_used
        )
        ingested += 1

    return {
        "status": "success",
        "ingested_count": ingested,
        "message": f"Successfully ingested {ingested} dispute resolution outcomes."
    }


# Active calibrated model storage
_CALIBRATED_ESTIMATOR = None


@router.get("/calibration/status")
async def get_calibration_status():
    """
    Returns empirical calibration metrics against historical dispute outcomes in the database.
    Honest provenance: clearly indicates if sample count is sufficient for true calibration.
    """
    outcomes = db.get_bin_outcomes()
    total = len(outcomes)
    won = sum(1 for o in outcomes if str(o.get("outcome", "")).lower() in ("won", "dispute.won"))
    lost = total - won

    from app.services.probability.calibration import calculate_brier_score, calculate_expected_calibration_error

    metrics = {
        "total_outcomes_recorded": total,
        "outcomes_won": won,
        "outcomes_lost": lost,
        "empirical_win_rate": round(won / total, 4) if total > 0 else None,
        "min_samples_threshold": 50,
        "active_estimator": "platt_calibrated" if _CALIBRATED_ESTIMATOR is not None else "heuristic_baseline",
        "is_calibrated": _CALIBRATED_ESTIMATOR is not None,
    }

    if total >= 5:
        y_true = [1 if str(o.get("outcome", "")).lower() in ("won", "dispute.won") else 0 for o in outcomes]
        y_prob = [float(o.get("confidence_score", 50.0)) / 100.0 for o in outcomes]
        metrics["brier_score"] = calculate_brier_score(y_true, y_prob)
        metrics["expected_calibration_error"] = calculate_expected_calibration_error(y_true, y_prob)
    else:
        metrics["brier_score"] = None
        metrics["expected_calibration_error"] = None
        metrics["note"] = "Insufficient empirical outcomes (< 5) to compute statistically sound calibration error."

    return metrics


@router.post("/calibration/train", status_code=status.HTTP_200_OK)
async def train_empirical_calibration(
    min_samples: int = 50,
    learning_rate: float = 0.05,
    max_epochs: int = 250
):
    """
    Trains Platt Scaling logistic regression on empirical dispute outcomes in the database.
    Safely rejects fitting if fewer than `min_samples` (default: 50) records are present.
    """
    global _CALIBRATED_ESTIMATOR
    outcomes = db.get_bin_outcomes()

    from app.services.probability.calibration import fit_platt_scaling_model
    estimator, diagnostics = fit_platt_scaling_model(
        outcomes=outcomes,
        min_samples=min_samples,
        learning_rate=learning_rate,
        max_epochs=max_epochs
    )

    if estimator is not None:
        _CALIBRATED_ESTIMATOR = estimator

    return diagnostics


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
