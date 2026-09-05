from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from app.core.logger import get_logger
from app.services.probability.estimator import (
    get_win_probability_estimator,
    BaseWinProbabilityEstimator,
    ProbabilityEstimate,
)

logger = get_logger("expected_value_engine")


class ExpectedValueResult(BaseModel):
    disputed_amount_inr: float
    estimated_win_probability: float = Field(..., description="Estimated win probability P(win|x)")
    p_win: float = Field(..., description="Estimated win probability alias for backward compatibility")
    calibration_method: str = Field(default="heuristic_baseline", description="Method used: 'heuristic_baseline' | 'platt_calibrated'")
    is_calibrated: bool = Field(default=False, description="True ONLY if derived from empirical historical outcome training")
    issuer_fee_inr: float = Field(..., description="Non-refundable issuer dispute fee F_fee")
    operational_cost_inr: float = Field(..., description="Operational & API infrastructure cost C_op")
    expected_value_inr: float = Field(..., description="Calculated Expected Value E[V]")
    decision: str = Field(..., description="AUTO_SUBMIT_REPRESENTMENT | ROUTE_TO_HITL_QUEUE | AUTO_ACCEPT_OR_REFUND")
    is_profitable: bool
    formula_breakdown: Dict[str, Any]
    rationale: str


def estimate_win_probability(
    confidence_score: float,
    ce30_compliant: bool = False,
    fpt_compliant: bool = False,
    issuer_win_rate_adjustment: float = 0.0,
    estimator: Optional[BaseWinProbabilityEstimator] = None
) -> float:
    """
    Estimates probability P(win | x) from the telemetry confidence score (0-100)
    and network compliance factors, adjusted by historical issuer propensity.
    Uses the active WinProbabilityEstimator (defaults to HeuristicBaselineEstimator).
    """
    active_estimator = estimator or get_win_probability_estimator()
    res = active_estimator.estimate(
        confidence_score=confidence_score,
        ce30_compliant=ce30_compliant,
        fpt_compliant=fpt_compliant,
        issuer_adjustment=issuer_win_rate_adjustment
    )
    return res.p_win


# Backward compatibility alias
calibrate_win_probability = estimate_win_probability


def calculate_expected_value(
    amount_inr: float,
    confidence_score: float,
    issuer_fee_inr: float = 1500.0,  # ~ $18.00 dispute fee
    operational_cost_inr: float = 40.0,  # ~ $0.50 infrastructure cost
    ce30_compliant: bool = False,
    fpt_compliant: bool = False,
    issuer_adjustment: float = 0.0,
    estimator: Optional[BaseWinProbabilityEstimator] = None
) -> ExpectedValueResult:
    """
    Dynamic Expected Value (E[V]) Optimization Engine.
    Formula:
        E[V] = P(win | x) * A - (1 - P(win | x)) * F_fee - C_op

    Decision Boundary:
    - E[V] > 0 and P(win) >= 0.70  --> AUTO_SUBMIT_REPRESENTMENT (Autonomous Defense)
    - E[V] > 0 and 0.40 <= P < 0.70 --> ROUTE_TO_HITL_QUEUE (Human Evidence Remediation)
    - E[V] <= 0                    --> AUTO_ACCEPT_OR_REFUND (Prevent Arbitration Penalty)
    """
    active_estimator = estimator or get_win_probability_estimator()
    prob_est = active_estimator.estimate(
        confidence_score=confidence_score,
        ce30_compliant=ce30_compliant,
        fpt_compliant=fpt_compliant,
        issuer_adjustment=issuer_adjustment
    )
    p_win = prob_est.p_win

    amount = float(amount_inr)
    fee = float(issuer_fee_inr)
    cost = float(operational_cost_inr)

    # Core mathematical expectation
    expected_value = (p_win * amount) - ((1.0 - p_win) * fee) - cost
    ev_rounded = round(expected_value, 2)
    is_profitable = ev_rounded > 0.0

    # Policy Router
    if ev_rounded > 0.0 and p_win >= 0.70:
        decision = "AUTO_SUBMIT_REPRESENTMENT"
        rationale = (
            f"Profitable representment (E[V] = +₹{ev_rounded:,.2f}) with strong estimated win probability "
            f"({p_win*100:.1f}%). Exceeds autonomous threshold (>=70%). Method: {prob_est.method}."
        )
    elif ev_rounded > 0.0 and p_win >= 0.40:
        decision = "ROUTE_TO_HITL_QUEUE"
        rationale = (
            f"Positive expected value (E[V] = +₹{ev_rounded:,.2f}), but moderate win probability "
            f"({p_win*100:.1f}%). Routed to Human-in-the-Loop review for evidence enrichment. Method: {prob_est.method}."
        )
    else:
        decision = "AUTO_ACCEPT_OR_REFUND"
        rationale = (
            f"Unprofitable representment (E[V] = ₹{ev_rounded:,.2f}, P(win) = {p_win*100:.1f}%). "
            f"Potential recovery does not justify the non-refundable ₹{fee:,.2f} dispute fee and ₹{cost:,.2f} cost. "
            f"Auto-accept recommended to avoid financial loss. Method: {prob_est.method}."
        )

    formula_breakdown = {
        "amount_inr": amount,
        "estimated_win_probability": p_win,
        "p_win": p_win,
        "calibration_method": prob_est.method,
        "is_calibrated": prob_est.is_calibrated,
        "issuer_fee_inr": fee,
        "operational_cost_inr": cost,
        "expected_recovery": round(p_win * amount, 2),
        "expected_loss_risk": round((1.0 - p_win) * fee, 2),
        "net_expected_value": ev_rounded
    }

    logger.info(
        "Evaluated dispute expected value",
        amount=amount,
        score=confidence_score,
        p_win=p_win,
        ev=ev_rounded,
        decision=decision
    )

    return ExpectedValueResult(
        disputed_amount_inr=amount,
        estimated_win_probability=p_win,
        p_win=p_win,
        calibration_method=prob_est.method,
        is_calibrated=prob_est.is_calibrated,
        issuer_fee_inr=fee,
        operational_cost_inr=cost,
        expected_value_inr=ev_rounded,
        decision=decision,
        is_profitable=is_profitable,
        formula_breakdown=formula_breakdown,
        rationale=rationale
    )
