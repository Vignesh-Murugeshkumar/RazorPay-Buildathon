"""
Unit tests for AIEvidenceVerifier.
Validates that the AI Verifier strictly rejects hallucinated evidence IDs,
ungrounded assertions, fabricated delivery claims, and contradicted evidence.
"""

import pytest
from app.ai.verifier import AIEvidenceVerifier, VerificationResult
from app.ai.prompts import DisputeInvestigationReport, AIClaimItem
from app.schemas.dispute import EvidenceItem, EvidenceStatus, EvidenceContradiction


def test_verifier_catches_hallucinated_evidence_id():
    """Verifier must reject report if AI references non-existent evidence ID."""
    verifier = AIEvidenceVerifier()

    evidence_items = [
        EvidenceItem(
            evidence_id="EV-001",
            evidence_type="ip_address",
            status=EvidenceStatus.VERIFIED,
            value="157.48.12.90",
            source="telemetry"
        )
    ]

    report = DisputeInvestigationReport(
        risk_assessment="High Risk: Attempting to assert satellite evidence.",
        confidence=0.92,
        claim_summary="Order confirmed via non-existent telemetry item.",
        claims=[
            AIClaimItem(
                claim_id="CL-001",
                claim_text="Order delivered and confirmed via satellite EV-999.",
                evidence_ids=["EV-999"],  # Hallucinated ID
                confidence=0.95,
                policy_document_id="DOC-CARRIER-POD"
            )
        ],
        supporting_evidence=["EV-999"],
        contradicting_evidence=[],
        missing_evidence=[],
        policy_citations=["DOC-CARRIER-POD"],
        recommended_strategy="CARRIER_POD_DEFENSE",
        recommended_action="AUTO_REPRESENT",
        reasoning_summary="Advisory claims delivery via EV-999."
    )

    result = verifier.verify_report(
        report=report,
        evidence_items=evidence_items,
        contradictions=[]
    )

    assert result.passed is False
    assert "EV-999" in result.hallucinated_evidence_ids
    assert result.grounded_claims_ratio == 0.0


def test_verifier_catches_ungrounded_unverified_claim():
    """Verifier must reject report if AI claims an unverified or missing evidence item is verified."""
    verifier = AIEvidenceVerifier()

    evidence_items = [
        EvidenceItem(
            evidence_id="EV-004",
            evidence_type="carrier_proof",
            status=EvidenceStatus.MISSING,  # Not verified!
            value=None,
            source="carrier_proof"
        )
    ]

    report = DisputeInvestigationReport(
        risk_assessment="Advisory assertion of delivery.",
        confidence=0.88,
        claim_summary="Carrier delivered goods.",
        claims=[
            AIClaimItem(
                claim_id="CL-001",
                claim_text="Carrier delivered the package to recipient address successfully.",
                evidence_ids=["EV-004"],
                confidence=0.90,
                policy_document_id="DOC-CARRIER-POD"
            )
        ],
        supporting_evidence=["EV-004"],
        contradicting_evidence=[],
        missing_evidence=[],
        policy_citations=["DOC-CARRIER-POD"],
        recommended_strategy="CARRIER_POD_DEFENSE",
        recommended_action="AUTO_REPRESENT",
        reasoning_summary="Claims delivery occurred."
    )

    result = verifier.verify_report(
        report=report,
        evidence_items=evidence_items,
        contradictions=[]
    )

    assert result.passed is False
    assert len(result.rejection_reasons) >= 1
    assert result.grounded_claims_ratio == 0.0


def test_verifier_rejects_claims_relying_on_contradicted_evidence():
    """Verifier must reject claims that cite evidence which was flagged as contradicted."""
    verifier = AIEvidenceVerifier()

    evidence_items = [
        EvidenceItem(
            evidence_id="EV-004",
            evidence_type="carrier_proof",
            status=EvidenceStatus.CONTRADICTED,
            value={"delivered": True, "tracking": None},
            source="carrier_proof"
        )
    ]

    contradictions = [
        EvidenceContradiction(
            conflict_id="CONF-001",
            evidence_ids=["EV-004"],
            fields=["delivered_status", "tracking_number"],
            description="Carrier proof marked delivered but tracking number is missing",
            severity="CRITICAL"
        )
    ]

    report = DisputeInvestigationReport(
        risk_assessment="Advisory claims delivery without tracking.",
        confidence=0.85,
        claim_summary="Carrier proof shows delivery.",
        claims=[
            AIClaimItem(
                claim_id="CL-001",
                claim_text="Carrier proof confirms delivery at customer address.",
                evidence_ids=["EV-004"],
                confidence=0.85,
                policy_document_id="DOC-CARRIER-POD"
            )
        ],
        supporting_evidence=["EV-004"],
        contradicting_evidence=[],
        missing_evidence=[],
        policy_citations=["DOC-CARRIER-POD"],
        recommended_strategy="CARRIER_POD_DEFENSE",
        recommended_action="AUTO_REPRESENT",
        reasoning_summary="Claims delivery."
    )

    result = verifier.verify_report(
        report=report,
        evidence_items=evidence_items,
        contradictions=contradictions
    )

    assert result.passed is False
    assert "EV-004" in result.contradicted_citations
    assert len(result.rejection_reasons) >= 1


def test_verifier_passes_valid_grounded_report():
    """Verifier must pass a cleanly grounded report where all claims match verified evidence."""
    verifier = AIEvidenceVerifier()

    evidence_items = [
        EvidenceItem(
            evidence_id="EV-004",
            evidence_type="carrier_proof",
            status=EvidenceStatus.VERIFIED,
            value={"carrier": "BlueDart", "tracking": "BD99281921IN", "delivered": True},
            source="carrier_proof"
        )
    ]

    report = DisputeInvestigationReport(
        risk_assessment="Low Risk: Valid proof of delivery with carrier tracking.",
        confidence=0.95,
        claim_summary="Physical carrier BlueDart confirmed delivery.",
        claims=[
            AIClaimItem(
                claim_id="CL-001",
                claim_text="Physical carrier BlueDart confirmed delivery with recipient signature.",
                evidence_ids=["EV-004"],
                confidence=0.95,
                policy_document_id="DOC-CARRIER-POD"
            )
        ],
        supporting_evidence=["EV-004"],
        contradicting_evidence=[],
        missing_evidence=[],
        policy_citations=["DOC-CARRIER-POD"],
        recommended_strategy="CARRIER_POD_DEFENSE",
        recommended_action="AUTO_REPRESENT",
        reasoning_summary="Valid carrier proof corroboration."
    )

    result = verifier.verify_report(
        report=report,
        evidence_items=evidence_items,
        contradictions=[]
    )

    assert result.passed is True
    assert len(result.rejection_reasons) == 0
    assert result.grounded_claims_ratio == 1.0
