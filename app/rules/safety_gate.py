"""
SentinelDispute - Deterministic Financial Safety Gate.

Authoritative Gatekeeper that executes after AI Investigation, AI Verification,
Network Rules, and Expected Value modeling.
Enforces that the LLM is strictly advisory and NEVER authorized to move money or dispatch representments alone.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from app.schemas.dispute import RuleEvaluationResult, EvidenceContradiction
from app.ai.prompts import DisputeInvestigationReport
from app.ai.verifier import VerificationResult
from app.services.expected_value import ExpectedValueResult
from app.core.logger import get_logger

logger = get_logger("safety_gate")


class SafetyGateDecision(BaseModel):
    final_decision: str = Field(..., description="AUTO_REPRESENT | HITL_REVIEW | ACCEPT_LOSS")
    allowed_auto_dispatch: bool = Field(..., description="True ONLY if every deterministic safety check passes")
    gate_reasons: List[str] = Field(default_factory=list, description="List of rule evaluations justifying the decision")
    primary_policy_rule: str = Field(..., description="Authoritative network or financial rule applied")
    ai_alignment: str = Field(..., description="AGREED | OVERRIDDEN_FOR_SAFETY | ESCALATED_TO_HITL")
    decision_explanation: str = Field(..., description="Human-readable decision explanation for UI and merchant audit")


class DeterministicSafetyGate:
    """
    Authoritative Financial Action Gatekeeper.
    Combines AI advice, verification audits, card brand rules, and economic calculus.
    """

    def evaluate_gate(
        self,
        ai_report: DisputeInvestigationReport,
        verification: VerificationResult,
        rule_result: RuleEvaluationResult,
        ev_result: ExpectedValueResult,
        contradictions: List[EvidenceContradiction],
        confidence_score: float
    ) -> SafetyGateDecision:
        gate_reasons: List[str] = []
        is_compliant = (
            rule_result.ce30_compliant or
            rule_result.fpt_compliant or
            rule_result.carrier_verified or
            rule_result.digital_verified
        )

        p_win = ev_result.estimated_win_probability
        ev_inr = ev_result.expected_value_inr
        ai_action = ai_report.recommended_action

        # HARD RULE 1: AI Verification Failure -> Strict Block to HITL
        if not verification.passed:
            gate_reasons.append(
                f"AI Verification Failure: {len(verification.rejection_reasons)} safety violation(s) detected. "
                f"Autonomous representment blocked."
            )
            return SafetyGateDecision(
                final_decision="HITL_REVIEW",
                allowed_auto_dispatch=False,
                gate_reasons=gate_reasons + verification.rejection_reasons,
                primary_policy_rule="SAFETY-GATE-VERIFIER-REJECTION",
                ai_alignment="ESCALATED_TO_HITL",
                decision_explanation=(
                    f"Routed to Human-in-the-Loop review because AI evidence verification failed "
                    f"({len(verification.rejection_reasons)} violation(s)). AI advice overridden for safety."
                )
            )

        # HARD RULE 2: Objective Factual Contradictions -> Strict Block to HITL
        if len(contradictions) > 0:
            gate_reasons.append(
                f"Objective Contradictions Detected: {len(contradictions)} conflicting evidence fact(s). "
                f"Cannot auto-dispatch contradictory evidence to card network."
            )
            return SafetyGateDecision(
                final_decision="HITL_REVIEW",
                allowed_auto_dispatch=False,
                gate_reasons=gate_reasons,
                primary_policy_rule="SAFETY-GATE-UNRESOLVED-CONTRADICTION",
                ai_alignment="ESCALATED_TO_HITL",
                decision_explanation=(
                    f"Routed to Human-in-the-Loop review due to {len(contradictions)} objective evidence contradiction(s). "
                    f"Contradictory representments risk immediate issuer rejection and arbitration penalties."
                )
            )

        # HARD RULE 3: Negative Expected Value -> Auto-Accept Loss to Prevent Arbitration Penalty
        if ev_inr <= 0.0 and p_win < 0.40:
            gate_reasons.append(
                f"Economic Unviability: Expected value is negative (E[V] = ₹{ev_inr:,.2f}) with low win probability "
                f"({p_win*100:.1f}%). Defending risks ₹{ev_result.issuer_fee_inr:,.2f} non-refundable fee."
            )
            alignment = "AGREED" if ai_action == "ACCEPT_LOSS" else "OVERRIDDEN_FOR_SAFETY"
            return SafetyGateDecision(
                final_decision="ACCEPT_LOSS",
                allowed_auto_dispatch=False,
                gate_reasons=gate_reasons,
                primary_policy_rule="SAFETY-GATE-NEGATIVE-EXPECTED-VALUE",
                ai_alignment=alignment,
                decision_explanation=(
                    f"Auto-accepted dispute loss. Recoverable amount (₹{ev_result.disputed_amount_inr:,.2f}) does not "
                    f"justify the ₹{ev_result.issuer_fee_inr:,.2f} dispute fee at an estimated {p_win*100:.1f}% win probability."
                )
            )

        # HARD RULE 4: Autonomous Representment Qualification
        # Must have: Verified AI report + Network Compliance + E[V] > 0 + P(win) >= 70% + Score >= 85.0
        if is_compliant and ev_inr > 0.0 and p_win >= 0.70 and confidence_score >= 85.0:
            gate_reasons.append(
                f"Autonomous Defense Qualified: 100% verified evidence, compliant with {rule_result.network.upper()} "
                f"rules, positive expected value (+₹{ev_inr:,.2f}), win probability {p_win*100:.1f}% >= 70%, "
                f"and confidence score {confidence_score:.1f} >= 85.0."
            )
            return SafetyGateDecision(
                final_decision="AUTO_REPRESENT",
                allowed_auto_dispatch=True,
                gate_reasons=gate_reasons,
                primary_policy_rule=f"RULE-{rule_result.network.upper()}-AUTONOMOUS-DISPATCH",
                ai_alignment="AGREED" if ai_action == "AUTO_REPRESENT" else "OVERRIDDEN_FOR_SAFETY",
                decision_explanation=(
                    f"Approved for autonomous representment dispatch. Evidence package completely satisfies "
                    f"{rule_result.network.upper()} standards with +₹{ev_inr:,.2f} expected net recovery."
                )
            )

        # Default fallback: Moderate risk / partial evidence -> HITL Review
        gate_reasons.append(
            f"Moderate Win Probability: Estimated win rate is {p_win*100:.1f}% with confidence {confidence_score:.1f}%. "
            f"Exceeds accept-loss threshold but requires human evidence enrichment before dispatch."
        )
        return SafetyGateDecision(
            final_decision="HITL_REVIEW",
            allowed_auto_dispatch=False,
            gate_reasons=gate_reasons,
            primary_policy_rule="SAFETY-GATE-HITL-REMEDIATION",
            ai_alignment="AGREED" if ai_action == "HITL_REVIEW" else "ESCALATED_TO_HITL",
            decision_explanation=(
                f"Routed to Human-in-the-Loop review. Case demonstrates positive expected value (+₹{ev_inr:,.2f}), "
                f"but win probability ({p_win*100:.1f}%) is below the autonomous dispatch threshold (70%)."
            )
        )

    evaluate = evaluate_gate


safety_gate = DeterministicSafetyGate()
