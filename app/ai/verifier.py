"""
SentinelDispute - Deterministic Evidence & Provenance Verifier.

Acts as an independent, deterministic Python verification stage between the probabilistic
LLM reasoning layer and the deterministic safety gate.
Strictly validates:
  1. Evidence IDs (EV-001..EV-007) exist in the normalized evidence package.
  2. Evidence statuses (VERIFIED / PARTIALLY_VERIFIED).
  3. No ungrounded assertions or hallucinated evidence tokens.
  4. Absence of unresolved contradictory evidence citations.
  5. Policy document IDs and versioned retrieval IDs match session-retrieved excerpts.
  6. Material physical delivery and 3DS authentication assertions are backed by verified evidence.

Architectural Trust Hierarchy:
  - LLM = Probabilistic reasoning / structured advisory layer
  - Verifier = Deterministic evidence & provenance safety boundary
  - Rules & E[V] = Deterministic card network compliance & financial optimization
  - Safety Gate = Final financial decision authority
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from app.schemas.dispute import (
    EvidenceItem,
    EvidenceStatus,
    EvidenceContradiction,
    ClaimVerificationResult,
    ClaimChallenge
)
from app.ai.prompts import DisputeInvestigationReport, AIClaimItem
from app.ai.policy_kb import PolicyExcerpt
from app.core.logger import get_logger

logger = get_logger("deterministic_verifier")


class VerificationResult(BaseModel):
    passed: bool = Field(..., description="True if all claims are grounded and consistent with evidence and policy")
    grounded_claims_ratio: float = Field(..., ge=0.0, le=1.0, description="Ratio of verified grounded claims: grounded/total")
    total_claims: int = Field(default=0)
    grounded_claims: int = Field(default=0)
    unsupported_claims: List[str] = Field(default_factory=list, description="Claim texts lacking valid evidence citations")
    hallucinated_evidence_ids: List[str] = Field(default_factory=list, description="Referenced evidence IDs not present in system")
    contradicted_citations: List[str] = Field(default_factory=list, description="Evidence IDs cited as positive despite being contradicted")
    fabricated_policy_citations: List[str] = Field(default_factory=list, description="Policy citations not retrieved in session")
    rejection_reasons: List[str] = Field(default_factory=list, description="Specific safety violations blocking automation")
    audit_summary: str = Field(..., description="Explainable audit statement")
    
    # Granular Independent Claim Verifications
    claim_verifications: List[ClaimVerificationResult] = Field(default_factory=list, description="Independent verification results per claim")
    overturned_claims: List[str] = Field(default_factory=list, description="Claims overturned by adversarial challenge")


class DeterministicEvidenceVerifier:
    """
    Deterministic Verification Stage:
    Enforces that the LLM/AI never invents facts, fabricates policy retrieval records,
    or bypasses deterministic policy.
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
        policy_excerpts: Optional[List[PolicyExcerpt]] = None,
        challenges: Optional[List[ClaimChallenge]] = None
    ) -> VerificationResult:
        rejection_reasons: List[str] = []
        hallucinated_ids: List[str] = []
        contradicted_cites: List[str] = []
        unsupported: List[str] = []
        fabricated_policies: List[str] = []
        claim_verifications: List[ClaimVerificationResult] = []
        overturned_claims: List[str] = []

        item_map = {item.evidence_id: item for item in evidence_items}
        valid_ev_ids = set(item_map.keys())

        conflicted_ev_ids = set()
        for c in contradictions:
            conflicted_ev_ids.update(c.evidence_ids)

        challenge_by_cid: Dict[str, ClaimChallenge] = {
            c.claim_id: c for c in (challenges or [])
        }

        retrieved_ret_ids = set()
        retrieved_doc_ids = set()
        if policy_excerpts:
            retrieved_ret_ids = {p.retrieval_id for p in policy_excerpts if p.retrieval_id}
            retrieved_doc_ids = {p.document_id for p in policy_excerpts}

        # 1. Verify supporting_evidence IDs exist and are not contradicted
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

        # 2. Verify individual claims grounding & Challenger Outcomes
        grounded_count = 0
        total_count = len(report.claims)

        for claim in report.claims:
            is_claim_grounded = True
            initial_conf = float(claim.confidence) / 100.0 if claim.confidence > 1.0 else float(claim.confidence)
            supp_ev = [ev_id for ev_id in claim.evidence_ids if ev_id in valid_ev_ids and item_map[ev_id].status in (EvidenceStatus.VERIFIED, EvidenceStatus.PARTIALLY_VERIFIED)]
            contra_ev = [ev_id for ev_id in claim.evidence_ids if ev_id in conflicted_ev_ids]

            chal = challenge_by_cid.get(claim.claim_id)
            if chal:
                for ce in chal.contrary_evidence_ids:
                    if ce not in contra_ev:
                        contra_ev.append(ce)

            # Check if Challenger overturned claim
            if chal and chal.challenge_result == "overturned":
                v_status = "contradicted"
                v_conf = 0.0
                unsupported_reason = f"Challenger overturned claim: {chal.alternative_explanation}"
                is_claim_grounded = False
                overturned_claims.append(claim.claim_id)
                rejection_reasons.append(f"Claim {claim.claim_id} overturned by challenger: {chal.challenge}")
                if claim.claim_text not in unsupported:
                    unsupported.append(f"{claim.claim_id}: {claim.claim_text} (Overturned by challenger)")
            elif contra_ev:
                v_status = "contradicted"
                v_conf = 0.0
                unsupported_reason = f"Evidence {contra_ev} has unresolved contradictions"
                is_claim_grounded = False
                contradicted_cites.extend(contra_ev)
            elif not claim.evidence_ids:
                v_status = "unsupported"
                v_conf = 0.0
                unsupported_reason = "No evidence citations provided"
                unsupported.append(f"{claim.claim_id}: {claim.claim_text} (No evidence cited)")
                is_claim_grounded = False
            else:
                has_hallucination = False
                has_unverified = False
                for ev_id in claim.evidence_ids:
                    if ev_id not in valid_ev_ids:
                        hallucinated_ids.append(ev_id)
                        has_hallucination = True
                        is_claim_grounded = False
                    else:
                        item = item_map[ev_id]
                        if item.status not in (EvidenceStatus.VERIFIED, EvidenceStatus.PARTIALLY_VERIFIED):
                            has_unverified = True
                            is_claim_grounded = False

                if has_hallucination:
                    v_status = "unsupported"
                    v_conf = 0.0
                    unsupported_reason = "Claim references nonexistent evidence IDs"
                elif has_unverified:
                    v_status = "unsupported"
                    v_conf = 0.0
                    unsupported_reason = "Claim references missing or unverified evidence"
                elif (chal and chal.challenge_result == "weakened") or any(item_map[e].status == EvidenceStatus.PARTIALLY_VERIFIED for e in claim.evidence_ids):
                    v_status = "partially_supported"
                    v_conf = min(0.65, round(initial_conf * 0.7, 2))
                    unsupported_reason = chal.challenge if chal else "Evidence only partially verified"
                    grounded_count += 1
                else:
                    v_status = "supported"
                    v_conf = round(initial_conf, 2)
                    unsupported_reason = None
                    grounded_count += 1

            # Check policy document citation validity and retrieval provenance
            if claim.policy_document_id:
                if claim.policy_document_id not in self.VALID_DOC_IDS:
                    rejection_reasons.append(f"Claim {claim.claim_id} cites unrecognized policy document: {claim.policy_document_id}")
                    fabricated_policies.append(claim.policy_document_id)
                    is_claim_grounded = False
                elif policy_excerpts and claim.policy_document_id not in retrieved_doc_ids:
                    rejection_reasons.append(f"Claim {claim.claim_id} cites unretrieved policy document: {claim.policy_document_id}")
                    fabricated_policies.append(claim.policy_document_id)
                    is_claim_grounded = False

            if not is_claim_grounded and claim.claim_text not in [u.split(": ", 1)[-1].split(" (")[0] for u in unsupported]:
                unsupported.append(f"{claim.claim_id}: {claim.claim_text}")

            claim_verifications.append(ClaimVerificationResult(
                claim_id=claim.claim_id,
                verification_status=v_status,
                supporting_evidence=supp_ev,
                contradicting_evidence=contra_ev,
                unsupported_reason=unsupported_reason,
                verified_confidence=v_conf
            ))

        # 3. Verify Policy Analysis Provenance
        for pa in report.policy_analysis:
            if pa.policy_document_id not in self.VALID_DOC_IDS:
                rejection_reasons.append(f"Policy analysis references unrecognized document: {pa.policy_document_id}")
                fabricated_policies.append(pa.policy_document_id)
            elif policy_excerpts and pa.policy_document_id not in retrieved_doc_ids:
                rejection_reasons.append(f"Policy analysis references document not retrieved in session: {pa.policy_document_id}")
                fabricated_policies.append(pa.policy_document_id)

            if pa.retrieval_id and policy_excerpts and pa.retrieval_id not in retrieved_ret_ids:
                rejection_reasons.append(f"Policy analysis cited fabricated retrieval ID: {pa.retrieval_id}")
                fabricated_policies.append(pa.retrieval_id)

            # Check that SATISFIED status is supported by verified evidence
            if pa.status == "SATISFIED":
                if not pa.evidence_ids:
                    rejection_reasons.append(f"Policy requirement '{pa.requirement}' claimed SATISFIED without evidence IDs")
                else:
                    for ev_id in pa.evidence_ids:
                        if ev_id not in valid_ev_ids:
                            hallucinated_ids.append(ev_id)
                        elif item_map[ev_id].status not in (EvidenceStatus.VERIFIED, EvidenceStatus.PARTIALLY_VERIFIED):
                            rejection_reasons.append(f"Requirement '{pa.requirement}' cites unverified evidence {ev_id}")
                        elif ev_id in conflicted_ev_ids:
                            contradicted_cites.append(ev_id)
                            rejection_reasons.append(f"Requirement '{pa.requirement}' cites contradicted evidence {ev_id}")

        # 4. Contradiction Check: If contradictions exist, AI cannot recommend AUTO_REPRESENT
        if contradictions and report.recommended_action in ("AUTO_REPRESENT", "AUTO_DISPATCH"):
            rejection_reasons.append(
                f"AI recommended AUTO_REPRESENT while {len(contradictions)} objective factual contradiction(s) remain unresolved"
            )

        # 5. Check for ungrounded physical delivery claim if carrier proof is absent
        ev_carrier = item_map.get("EV-004")
        has_verified_carrier = ev_carrier and ev_carrier.status in (EvidenceStatus.VERIFIED, EvidenceStatus.PARTIALLY_VERIFIED) and "EV-004" not in conflicted_ev_ids
        for claim in report.claims:
            if ("physical delivery" in claim.claim_text.lower() or "carrier verified" in claim.claim_text.lower()) and not has_verified_carrier:
                rejection_reasons.append("AI asserted physical delivery without verified carrier proof [EV-004]")
                if claim.claim_text not in unsupported:
                    unsupported.append(claim.claim_text)

        # 6. Check for ungrounded 3DS claim if MFA is absent
        ev_mfa = item_map.get("EV-003")
        has_verified_mfa = ev_mfa and ev_mfa.status == EvidenceStatus.VERIFIED and "EV-003" not in conflicted_ev_ids
        for claim in report.claims:
            if ("3ds" in claim.claim_text.lower() or "liability shift" in claim.claim_text.lower()) and not has_verified_mfa:
                rejection_reasons.append("AI asserted 3D Secure / MFA authentication without verified telemetry [EV-003]")
                if claim.claim_text not in unsupported:
                    unsupported.append(claim.claim_text)

        # Compute grounding ratio
        grounding_ratio = (grounded_count / total_count) if total_count > 0 else (1.0 if not unsupported else 0.0)
        passed = (
            (len(rejection_reasons) == 0) and
            (len(unsupported) == 0) and
            (len(hallucinated_ids) == 0) and
            (len(fabricated_policies) == 0) and
            (len(overturned_claims) == 0)
        )

        # Audit summary statement
        if passed:
            audit_summary = (
                f"VERIFIER_PASSED: All {total_count} AI claims strictly grounded in verified evidence. "
                f"Zero hallucinations, 100% evidence-policy provenance verified."
            )
        else:
            audit_summary = (
                f"VERIFIER_FAILED: Rejected {len(rejection_reasons)} violation(s). "
                f"Unsupported claims: {len(unsupported)}, Hallucinated IDs: {len(hallucinated_ids)}, "
                f"Contradicted citations: {len(contradicted_cites)}, Fabricated policies: {len(fabricated_policies)}, "
                f"Overturned claims: {len(overturned_claims)}. Autonomous action strictly blocked."
            )

        logger.info(
            "Deterministic evidence verification evaluated",
            passed=passed,
            grounded_claims_ratio=round(grounding_ratio, 2),
            rejection_count=len(rejection_reasons),
            overturned_count=len(overturned_claims)
        )

        return VerificationResult(
            passed=passed,
            grounded_claims_ratio=round(grounding_ratio, 4),
            total_claims=total_count,
            grounded_claims=grounded_count,
            unsupported_claims=unsupported,
            hallucinated_evidence_ids=list(set(hallucinated_ids)),
            contradicted_citations=list(set(contradicted_cites)),
            fabricated_policy_citations=list(set(fabricated_policies)),
            rejection_reasons=rejection_reasons,
            audit_summary=audit_summary,
            claim_verifications=claim_verifications,
            overturned_claims=overturned_claims
        )


# Canonical naming for deterministic safety boundary
DeterministicEvidenceVerifier = DeterministicEvidenceVerifier

# Backward compatibility alias for existing test suites and imports
AIEvidenceVerifier = DeterministicEvidenceVerifier
deterministic_verifier = DeterministicEvidenceVerifier()
ai_verifier = deterministic_verifier
