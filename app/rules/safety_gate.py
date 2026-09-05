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
    network_policy_qualified: bool = Field(default=False, description="True if Visa CE 3.0 or MC FPT rules are satisfied")
    fulfillment_evidence_sufficient: bool = Field(default=False, description="True if carrier POD or digital logs are verified")
    blocking_factors: List[str] = Field(default_factory=list, description="Specific safety factors blocking automation")
    missing_requirements: List[str] = Field(default_factory=list, description="Evidence gaps preventing representment")
    recommended_human_action: str = Field(default="", description="Prescriptive instructions for human reviewer")


class DeterministicSafetyGate:
    """
    Authoritative Financial Action Gatekeeper.
    Combines AI advice, verification audits, card brand rules, and economic calculus.
    Guarantees AI recommendation is purely advisory.
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
        blocking_factors: List[str] = []
        missing_requirements: List[str] = []

        # Decouple Network Qualification from Fulfillment
        network_policy_qualified = bool(rule_result.ce30_compliant or rule_result.fpt_compliant)
        fulfillment_evidence_sufficient = bool(rule_result.carrier_verified or rule_result.digital_verified)

        reason_str = str(rule_result.reason_code).strip()
        if reason_str in ("10.4", "4837"):
            is_compliant = network_policy_qualified and fulfillment_evidence_sufficient
        else:
            is_compliant = fulfillment_evidence_sufficient or network_policy_qualified

        p_win = ev_result.estimated_win_probability
        ev_inr = ev_result.expected_value_inr
        ai_action = getattr(ai_report, "recommended_action", "HITL")
        ai_conf = getattr(ai_report, "reasoning_confidence", 100)

        # Audit Gaps
        if not network_policy_qualified and reason_str in ("10.4", "4837"):
            missing_requirements.append(f"{rule_result.network.upper()} historical lookback requirement (2+ matching orders)")
        if not fulfillment_evidence_sufficient:
            missing_requirements.append("Verified carrier POD tracking or digital server access logs")

        # HARD RULE 1: AI Verification Failure -> Strict Block to HITL
        if not verification.passed:
            reasons = [
                f"AI Verification Failure: {len(verification.rejection_reasons)} safety violation(s) detected. "
                f"Autonomous representment blocked."
            ] + verification.rejection_reasons
            blocking_factors.extend(verification.rejection_reasons)
            rec_action = f"Human action required: Resolve AI verification violations: {'; '.join(verification.rejection_reasons[:2])}."
            return SafetyGateDecision(
                final_decision="HITL_REVIEW",
                allowed_auto_dispatch=False,
                gate_reasons=reasons,
                primary_policy_rule="SAFETY-GATE-VERIFIER-REJECTION",
                ai_alignment="ESCALATED_TO_HITL",
                decision_explanation=(
                    f"Routed to Human-in-the-Loop review because AI evidence verification failed "
                    f"({len(verification.rejection_reasons)} violation(s)). AI advice overridden for safety."
                ),
                network_policy_qualified=network_policy_qualified,
                fulfillment_evidence_sufficient=fulfillment_evidence_sufficient,
                blocking_factors=blocking_factors,
                missing_requirements=missing_requirements,
                recommended_human_action=rec_action
            )

        # HARD RULE 2: Objective Factual Contradictions -> Strict Block to HITL
        if len(contradictions) > 0:
            c_reasons = [
                f"Objective Contradictions Detected: {len(contradictions)} conflicting evidence fact(s). "
                f"Cannot auto-dispatch contradictory evidence to card network."
            ]
            for c in contradictions:
                blocking_factors.append(f"Contradiction: {c.description}")
            rec_action = f"Human action required: Reconcile evidence contradiction before filing: {contradictions[0].description}."
            return SafetyGateDecision(
                final_decision="HITL_REVIEW",
                allowed_auto_dispatch=False,
                gate_reasons=c_reasons,
                primary_policy_rule="SAFETY-GATE-UNRESOLVED-CONTRADICTION",
                ai_alignment="ESCALATED_TO_HITL",
                decision_explanation=(
                    f"Routed to Human-in-the-Loop review due to {len(contradictions)} objective evidence contradiction(s). "
                    f"Contradictory representments risk immediate issuer rejection and arbitration penalties."
                ),
                network_policy_qualified=network_policy_qualified,
                fulfillment_evidence_sufficient=fulfillment_evidence_sufficient,
                blocking_factors=blocking_factors,
                missing_requirements=missing_requirements,
                recommended_human_action=rec_action
            )

        # HARD RULE 3: Negative Expected Value -> Auto-Accept Loss to Prevent Arbitration Penalty
        if ev_inr <= 0.0 and p_win < 0.40:
            ev_reasons = [
                f"Economic Unviability: Expected value is negative (E[V] = ₹{ev_inr:,.2f}) with low win probability "
                f"({p_win*100:.1f}%). Defending risks ₹{ev_result.issuer_fee_inr:,.2f} non-refundable fee."
            ]
            alignment = "AGREED" if ai_action in ("ACCEPT", "ACCEPT_LOSS") else "OVERRIDDEN_FOR_SAFETY"
            blocking_factors.append(f"Negative Expected Value (E[V] = INR {ev_inr:,.2f})")
            return SafetyGateDecision(
                final_decision="ACCEPT_LOSS",
                allowed_auto_dispatch=False,
                gate_reasons=ev_reasons,
                primary_policy_rule="SAFETY-GATE-NEGATIVE-EXPECTED-VALUE",
                ai_alignment=alignment,
                decision_explanation=(
                    f"Auto-accepted dispute loss. Recoverable amount (₹{ev_result.disputed_amount_inr:,.2f}) does not "
                    f"justify the ₹{ev_result.issuer_fee_inr:,.2f} dispute fee at an estimated {p_win*100:.1f}% win probability."
                ),
                network_policy_qualified=network_policy_qualified,
                fulfillment_evidence_sufficient=fulfillment_evidence_sufficient,
                blocking_factors=blocking_factors,
                missing_requirements=missing_requirements,
                recommended_human_action="No representment required. Chargeback liability accepted to prevent fees."
            )

        # HARD RULE 4: Autonomous Representment Qualification
        # Must have:
        # 1. is_compliant (Network qualified + Fulfillment sufficient for fraud, or Fulfillment for non-fraud)
        # 2. Positive Expected Value (E[V] > 0)
        # 3. Win probability >= 70%
        # 4. Confidence Score >= 85.0
        # 5. AI reasoning confidence >= 70
        auto_qualified = (
            is_compliant and
            ev_inr > 0.0 and
            p_win >= 0.70 and
            confidence_score >= 85.0 and
            ai_conf >= 70
        )

        if auto_qualified:
            dispatch_reasons = [
                f"Autonomous Defense Qualified: 100% verified evidence, compliant with {rule_result.network.upper()} "
                f"rules, positive expected value (+₹{ev_inr:,.2f}), win probability {p_win*100:.1f}% >= 70%, "
                f"confidence score {confidence_score:.1f} >= 85.0, and AI reasoning confidence {ai_conf}% >= 70%."
            ]
            return SafetyGateDecision(
                final_decision="AUTO_REPRESENT",
                allowed_auto_dispatch=True,
                gate_reasons=dispatch_reasons,
                primary_policy_rule=f"RULE-{rule_result.network.upper()}-AUTONOMOUS-DISPATCH",
                ai_alignment="AGREED" if ai_action in ("AUTO_REPRESENT", "AUTO_DISPATCH") else "OVERRIDDEN_FOR_SAFETY",
                decision_explanation=(
                    f"Approved for autonomous representment dispatch. Evidence package completely satisfies "
                    f"{rule_result.network.upper()} standards with +₹{ev_inr:,.2f} expected net recovery."
                ),
                network_policy_qualified=network_policy_qualified,
                fulfillment_evidence_sufficient=fulfillment_evidence_sufficient,
                blocking_factors=[],
                missing_requirements=[],
                recommended_human_action="Automated package generated and submitted to payment network gateway."
            )

        # Default fallback: Moderate risk / partial evidence -> HITL Review
        hitl_reasons = []
        if not is_compliant:
            if not network_policy_qualified:
                hitl_reasons.append(f"Unfulfilled {rule_result.network.upper()} network lookback policy")
            if not fulfillment_evidence_sufficient:
                hitl_reasons.append("Incomplete delivery or digital access proof")
        if ai_conf < 70:
            hitl_reasons.append(f"AI reasoning confidence ({ai_conf}%) is below automation threshold (70%)")
        if p_win < 0.70:
            hitl_reasons.append(f"Estimated win probability ({p_win*100:.1f}%) is below 70%")

        blocking_factors.extend(hitl_reasons)
        rec_guidance = (
            f"Human action required: Attach {', '.join(missing_requirements)} before submitting representment."
            if missing_requirements else
            f"Human action required: Review case evidentiary support ({'; '.join(hitl_reasons[:2])})."
        )

        return SafetyGateDecision(
            final_decision="HITL_REVIEW",
            allowed_auto_dispatch=False,
            gate_reasons=hitl_reasons or ["Moderate evidentiary support requires human review"],
            primary_policy_rule="SAFETY-GATE-HITL-REMEDIATION",
            ai_alignment="AGREED" if ai_action in ("HITL", "HITL_REVIEW") else "ESCALATED_TO_HITL",
            decision_explanation=(
                f"Routed to Human-in-the-Loop review. Case demonstrates positive expected value (+₹{ev_inr:,.2f}), "
                f"but does not satisfy strict autonomous criteria ({'; '.join(hitl_reasons[:2])})."
            ),
            network_policy_qualified=network_policy_qualified,
            fulfillment_evidence_sufficient=fulfillment_evidence_sufficient,
            blocking_factors=blocking_factors,
            missing_requirements=missing_requirements,
            recommended_human_action=rec_guidance
        )

    evaluate = evaluate_gate


safety_gate = DeterministicSafetyGate()
