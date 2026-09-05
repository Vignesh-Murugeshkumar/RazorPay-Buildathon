"""
SentinelDispute - AI Evidence Verifier.

Acts as an independent second-stage safety auditor over AI Investigation Reports.
Catches hallucinated facts, nonexistent evidence IDs, ungrounded claims, and contradictions.
If the verifier fails, automatic representment is strictly blocked and routed to HITL.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from app.schemas.dispute import EvidenceItem, EvidenceStatus, EvidenceContradiction
from app.ai.prompts import DisputeInvestigationReport
from app.ai.policy_kb import PolicyExcerpt
from app.core.logger import get_logger

logger = get_logger("ai_verifier")


class VerificationResult(BaseModel):
    passed: bool = Field(..., description="True if all claims are grounded and consistent with evidence")
    grounded_claims_ratio: float = Field(..., ge=0.0, le=1.0, description="Ratio of verified grounded claims: grounded/total")
    total_claims: int = Field(default=0)
    grounded_claims: int = Field(default=0)
    unsupported_claims: List[str] = Field(default_factory=list, description="Claim texts lacking valid evidence citations")
    hallucinated_evidence_ids: List[str] = Field(default_factory=list, description="Referenced evidence IDs not present in system")
    contradicted_citations: List[str] = Field(default_factory=list, description="Evidence IDs cited as positive despite being contradicted")
    rejection_reasons: List[str] = Field(default_factory=list, description="Specific safety violations blocking automation")
    audit_summary: str = Field(..., description="Explainable audit statement")


class AIEvidenceVerifier:
    """
    Independent Verification Stage:
    Enforces that the LLM/AI never invents facts or bypasses deterministic policy.
    """

    VALID_DOC_IDS = {
        "DOC-VISA-CE30",
        "DOC-MC-FPT",
        "DOC-3DS-SHIFT",
        "DOC-CARRIER-POD",
        "DOC-DIGITAL-GOODS",
        "DOC-MERCHANT-TOS",
        "DOC-INTERNAL-RISK"
    }

    def verify_report(
        self,
        report: DisputeInvestigationReport,
        evidence_items: List[EvidenceItem],
        contradictions: List[EvidenceContradiction],
        policy_excerpts: Optional[List[PolicyExcerpt]] = None
    ) -> VerificationResult:
        rejection_reasons: List[str] = []
        hallucinated_ids: List[str] = []
        contradicted_cites: List[str] = []
        unsupported: List[str] = []

        item_map = {item.evidence_id: item for item in evidence_items}
        valid_ev_ids = set(item_map.keys())

        conflicted_ev_ids = set()
        for c in contradictions:
            conflicted_ev_ids.update(c.evidence_ids)

        # 1. Verify that all supporting_evidence IDs exist and are not contradicted
        for ev_id in report.supporting_evidence:
            if ev_id not in valid_ev_ids:
                hallucinated_ids.append(ev_id)
                rejection_reasons.append(f"AI cited nonexistent evidence ID: {ev_id}")
            else:
                item = item_map[ev_id]
                if item.status in (EvidenceStatus.MISSING, EvidenceStatus.UNVERIFIED):
                    rejection_reasons.append(f"AI treated {ev_id} ({item.evidence_type}) as verified, but status is {item.status.value}")
                if ev_id in conflicted_ev_ids:
                    contradicted_cites.append(ev_id)
                    rejection_reasons.append(f"AI cited {ev_id} as supporting evidence despite unresolved contradiction")

        # 2. Verify individual claims grounding
        grounded_count = 0
        total_count = len(report.claims)

        for claim in report.claims:
            is_claim_grounded = True

            if not claim.evidence_ids:
                unsupported.append(f"{claim.claim_id}: {claim.claim_text} (No evidence cited)")
                is_claim_grounded = False
            else:
                for ev_id in claim.evidence_ids:
                    if ev_id not in valid_ev_ids:
                        hallucinated_ids.append(ev_id)
                        is_claim_grounded = False
                    else:
                        item = item_map[ev_id]
                        if item.status not in (EvidenceStatus.VERIFIED, EvidenceStatus.PARTIALLY_VERIFIED):
                            is_claim_grounded = False
                        if ev_id in conflicted_ev_ids:
                            contradicted_cites.append(ev_id)
                            is_claim_grounded = False

            # Check policy document citation validity
            if claim.policy_document_id and claim.policy_document_id not in self.VALID_DOC_IDS:
                rejection_reasons.append(f"Claim {claim.claim_id} cites unrecognized policy document: {claim.policy_document_id}")
                is_claim_grounded = False

            if is_claim_grounded:
                grounded_count += 1
            else:
                if claim.claim_text not in [u.split(": ", 1)[-1].split(" (")[0] for u in unsupported]:
                    unsupported.append(f"{claim.claim_id}: {claim.claim_text}")

        # 3. Contradiction Check: If contradictions exist, AI cannot recommend AUTO_REPRESENT
        if contradictions and report.recommended_action == "AUTO_REPRESENT":
            rejection_reasons.append(
                f"AI recommended AUTO_REPRESENT while {len(contradictions)} objective factual contradiction(s) remain unresolved"
            )

        # 4. Check for ungrounded physical delivery claim if carrier proof is absent
        ev_carrier = item_map.get("EV-004")
        has_verified_carrier = ev_carrier and ev_carrier.status in (EvidenceStatus.VERIFIED, EvidenceStatus.PARTIALLY_VERIFIED)
        for claim in report.claims:
            if "physical delivery" in claim.claim_text.lower() and not has_verified_carrier:
                rejection_reasons.append("AI asserted physical delivery without verified carrier proof [EV-004]")
                if claim.claim_text not in unsupported:
                    unsupported.append(claim.claim_text)

        # 5. Check for ungrounded 3DS claim if MFA is absent
        ev_mfa = item_map.get("EV-003")
        has_verified_mfa = ev_mfa and ev_mfa.status == EvidenceStatus.VERIFIED
        for claim in report.claims:
            if "3ds" in claim.claim_text.lower() and not has_verified_mfa:
                rejection_reasons.append("AI asserted 3D Secure / MFA authentication without verified telemetry [EV-003]")
                if claim.claim_text not in unsupported:
                    unsupported.append(claim.claim_text)

        # Compute grounding ratio
        grounding_ratio = (grounded_count / total_count) if total_count > 0 else (1.0 if not unsupported else 0.0)
        passed = (len(rejection_reasons) == 0) and (len(unsupported) == 0) and (len(hallucinated_ids) == 0)

        # Audit summary statement
        if passed:
            audit_summary = (
                f"VERIFIER_PASSED: All {total_count} AI claims strictly grounded in verified evidence. "
                f"Zero hallucinations, 100% evidence-rule consistency."
            )
        else:
            audit_summary = (
                f"VERIFIER_FAILED: Rejected {len(rejection_reasons)} violation(s). "
                f"Unsupported claims: {len(unsupported)}, Hallucinated IDs: {len(hallucinated_ids)}, "
                f"Contradicted citations: {len(contradicted_cites)}. Autonomous action strictly blocked."
            )

        logger.info(
            "AI evidence verification evaluated",
            passed=passed,
            grounded_claims_ratio=round(grounding_ratio, 2),
            rejection_count=len(rejection_reasons)
        )

        return VerificationResult(
            passed=passed,
            grounded_claims_ratio=round(grounding_ratio, 4),
            total_claims=total_count,
            grounded_claims=grounded_count,
            unsupported_claims=unsupported,
            hallucinated_evidence_ids=list(set(hallucinated_ids)),
            contradicted_citations=list(set(contradicted_cites)),
            rejection_reasons=rejection_reasons,
            audit_summary=audit_summary
        )


ai_verifier = AIEvidenceVerifier()
