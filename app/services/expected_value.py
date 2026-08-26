from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from app.core.logger import get_logger

logger = get_logger("expected_value_engine")


class ExpectedValueResult(BaseModel):
    disputed_amount_inr: float
    p_win: float = Field(..., description="Calibrated win probability P(win|x)")
    issuer_fee_inr: float = Field(..., description="Non-refundable issuer dispute fee F_fee")
    operational_cost_inr: float = Field(..., description="Operational & API infrastructure cost C_op")
    expected_value_inr: float = Field(..., description="Calculated Expected Value E[V]")
    decision: str = Field(..., description="AUTO_SUBMIT_REPRESENTMENT | ROUTE_TO_HITL_QUEUE | AUTO_ACCEPT_OR_REFUND")
    is_profitable: bool
    formula_breakdown: Dict[str, Any]
    rationale: str


def calibrate_win_probability(
    confidence_score: float,
    ce30_compliant: bool = False,
    fpt_compliant: bool = False,
    issuer_win_rate_adjustment: float = 0.0
) -> float:
    """
    Calibrates probability P(win | x) from the telemetry confidence score (0-100)
    and network compliance factors, adjusted by historical issuer propensity.
    """
    score = max(0.0, min(100.0, float(confidence_score)))
    
    if ce30_compliant or (score >= 85.0):
        # CE 3.0 liability shift yields 88% - 98% empirical win rates
        base_p = 0.70 + (0.28 * ((score - 85.0) / 15.0 if score > 85.0 else 0.0))
    elif score >= 50.0:
        base_p = 0.40 + (0.30 * ((score - 50.0) / 35.0))
    else:
        base_p = max(0.05, 0.10 + (0.30 * (score / 50.0)))

    # Apply issuer intelligence delta (clamped to [0.01, 0.99])
    adjusted_p = max(0.01, min(0.99, base_p + issuer_win_rate_adjustment))
    return round(adjusted_p, 4)


def calculate_expected_value(
    amount_inr: float,
    confidence_score: float,
    issuer_fee_inr: float = 1500.0,  # ~ $18.00 dispute fee
    operational_cost_inr: float = 40.0,  # ~ $0.50 infrastructure cost
    ce30_compliant: bool = False,
    fpt_compliant: bool = False,
    issuer_adjustment: float = 0.0
) -> ExpectedValueResult:
    """
    Dynamic Expected Value (E[V]) Optimization Engine.
    Formula:
        E[V] = P(win | x) * A - (1 - P(win | x)) * F_fee - C_op

    Decision Matrix:
    - E[V] > 0 and P(win) >= 0.70: AUTO_SUBMIT_REPRESENTMENT
    - E[V] > 0 and 0.40 <= P(win) < 0.70: ROUTE_TO_HITL_QUEUE
    - E[V] <= 0: AUTO_ACCEPT_OR_REFUND (Prevents negative net recovery and secondary penalties)
    """
    principal = float(amount_inr)
    fee = float(issuer_fee_inr)
    cost = float(operational_cost_inr)

    p_win = calibrate_win_probability(
        confidence_score=confidence_score,
        ce30_compliant=ce30_compliant,
        fpt_compliant=fpt_compliant,
        issuer_win_rate_adjustment=issuer_adjustment
    )
    p_loss = 1.0 - p_win

    # E[V] = P(win)*A - (1-P(win))*F_fee - C_op
    ev = (p_win * principal) - (p_loss * fee) - cost
    ev_rounded = round(ev, 2)
    is_profitable = ev_rounded > 0

    if is_profitable and p_win >= 0.70:
        decision = "AUTO_SUBMIT_REPRESENTMENT"
        rationale = (
            f"Representment is economically profitable (E[V] = +₹{ev_rounded:,.2f}) with high win probability "
            f"P(win) = {p_win*100:.1f}%. Safe for autonomous network representment."
        )
    elif is_profitable and (0.40 <= p_win < 0.70):
        decision = "ROUTE_TO_HITL_QUEUE"
        rationale = (
            f"Representment is mathematically positive (E[V] = +₹{ev_rounded:,.2f}) but carries moderate risk "
            f"P(win) = {p_win*100:.1f}%. Routed to Human-in-the-Loop review queue for supplementary evidence."
        )
    else:
        decision = "AUTO_ACCEPT_OR_REFUND"
        rationale = (
            f"Representment is unprofitable (E[V] = ₹{ev_rounded:,.2f} <= ₹0) with win probability "
            f"P(win) = {p_win*100:.1f}%. Auto-accept dispute or issue refund to prevent issuer fee (₹{fee:,.2f}) "
            f"and protect VAMP/ECM merchant thresholds."
        )

    breakdown = {
        "formula": "E[V] = P(win) * A - (1 - P(win)) * F_fee - C_op",
        "principal_A": principal,
        "p_win": p_win,
        "p_loss": round(p_loss, 4),
        "expected_gross_recovery": round(p_win * principal, 2),
        "expected_fee_loss": round(p_loss * fee, 2),
        "operational_cost": cost,
        "net_expected_value": ev_rounded
    }

    return ExpectedValueResult(
        disputed_amount_inr=principal,
        p_win=p_win,
        issuer_fee_inr=fee,
        operational_cost_inr=cost,
        expected_value_inr=ev_rounded,
        decision=decision,
        is_profitable=is_profitable,
        formula_breakdown=breakdown,
        rationale=rationale
    )
