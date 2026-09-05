"""
SentinelDispute - Evidence Investigation Agent.

Aggregates structured evidence, queries the local Policy Knowledge Base (RAG),
and prompts the AI Provider to produce a structured, schema-validated risk analysis.
"""

from typing import Dict, Any, List, Tuple, Optional
from app.schemas.dispute import DisputePayload, EvidenceItem, EvidenceContradiction
from app.ai.prompts import DisputeInvestigationReport
from app.ai.policy_kb import policy_knowledge_base, PolicyExcerpt
from app.ai.provider import get_ai_provider, AIProvider
from app.core.security import compute_sha256_hash
from app.core.logger import get_logger

logger = get_logger("investigation_agent")


class EvidenceInvestigationAgent:
    """
    Core AI Investigation Agent.
    Synthesizes messy, multi-source dispute evidence and produces grounded,
    structured reasoning. Output is purely advisory and feeds directly into the AI Verifier.
    """

    def __init__(self, provider: AIProvider = None):
        self.provider = provider or get_ai_provider()

    def investigate_dispute(
        self,
        payload: DisputePayload,
        evidence_items: List[EvidenceItem],
        contradictions: List[EvidenceContradiction],
        provider: Optional[AIProvider] = None
    ) -> Tuple[DisputeInvestigationReport, str, List[PolicyExcerpt]]:
        """
        Executes an end-to-end evidence investigation:
        1. Queries local policy knowledge base for relevant rules (Visa, MC, 3DS, Carrier, TOS).
        2. Packages structured evidence and contradictions.
        3. Calls AI Provider for structured reasoning.
        4. Calculates cryptographic SHA-256 seal of the advisory report.

        Returns: (DisputeInvestigationReport, report_sha256_hash, retrieved_policy_excerpts)
        """
        active_provider = provider or self.provider
        query = (
            f"{payload.card_network} chargeback dispute reason {payload.reason_code} "
            f"service {payload.service_type} amount {payload.amount_inr}"
        )
        policy_excerpts = policy_knowledge_base.retrieve(
            query=query,
            card_network=payload.card_network,
            reason_code=str(payload.reason_code),
            service_type=payload.service_type,
            top_k=4
        )

        dispute_summary = {
            "dispute_id": payload.dispute_id,
            "payment_id": payload.payment_id,
            "amount_inr": payload.amount_inr,
            "currency": payload.currency,
            "card_network": payload.card_network,
            "reason_code": payload.reason_code,
            "service_type": payload.service_type,
            "status": payload.status,
            "due_by": payload.due_by
        }

        serialized_evidence = [
            {
                "evidence_id": item.evidence_id,
                "evidence_type": item.evidence_type,
                "status": item.status.value,
                "value": item.value,
                "source": item.source,
                "rule_ids": item.rule_ids
            }
            for item in evidence_items
        ]

        serialized_contradictions = [
            {
                "conflict_id": c.conflict_id,
                "evidence_ids": c.evidence_ids,
                "fields": c.fields,
                "description": c.description,
                "severity": c.severity
            }
            for c in contradictions
        ]

        # Call provider with safe failover
        try:
            report = active_provider.investigate(
                dispute_summary=dispute_summary,
                evidence_items=serialized_evidence,
                contradictions=serialized_contradictions,
                policy_excerpts=policy_excerpts
            )
        except Exception as exc:
            logger.error(f"AI Provider error during investigation: {exc}. Falling back to safe HITL review.")
            from app.ai.prompts import MissingEvidenceItem, SelfChallengeReport
            report = DisputeInvestigationReport(
                case_assessment="INSUFFICIENT_EVIDENCE",
                win_probability=0.20,
                reasoning_confidence=0,
                strongest_evidence=[],
                weakest_evidence=[],
                claims=[],
                policy_analysis=[],
                contradictions=[],
                missing_evidence=[MissingEvidenceItem(
                    requirement="Automated AI Analysis",
                    reason=f"Provider error: {type(exc).__name__}. Safe failover to HITL."
                )],
                uncertainties=[f"Investigation interrupted by provider error: {str(exc)[:100]}"],
                recommended_action="HITL",
                reasoning=f"Fail-safe activated: AI provider error ({type(exc).__name__}). Dispute routed to HITL queue for manual review.",
                self_challenge=SelfChallengeReport(
                    vulnerabilities_found=[f"Provider error: {type(exc).__name__}"],
                    weakest_requirement="Live LLM Availability",
                    alternative_interpretation="Manual analyst adjudication required",
                    adjustment_made=True,
                    original_action="AUTO_REPRESENT",
                    revised_action="HITL",
                    rationale="Safe failover to human operator"
                ),
                provider_used="failover",
                model_version="failover-v2"
            )

        # Compute tamper-evident hash of the AI output
        report_json = report.model_dump_json()
        report_hash = compute_sha256_hash(report_json)

        logger.info(
            "Evidence investigation completed",
            dispute_id=payload.dispute_id,
            recommended_action=report.recommended_action,
            claims_count=len(report.claims),
            supporting_evidence=report.supporting_evidence,
            report_hash=report_hash[:12]
        )

        return report, report_hash, policy_excerpts


investigation_agent = EvidenceInvestigationAgent()
