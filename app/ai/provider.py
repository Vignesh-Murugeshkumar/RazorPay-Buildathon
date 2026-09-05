"""
SentinelDispute - Model Provider Abstraction.

Provides seamless switching between OpenAI (live LLM) and MockAIProvider (reproducible,
offline, deterministic reasoning for tests and local benchmarks).
Never fails startup if OPENAI_API_KEY is missing.
"""

import os
import json
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from app.ai.prompts import (
    DisputeInvestigationReport,
    AIClaimItem,
    build_investigation_system_prompt,
    build_investigation_user_prompt
)
from app.ai.policy_kb import PolicyExcerpt
from app.core.logger import get_logger

logger = get_logger("ai_provider")


class AIProvider(ABC):
    @abstractmethod
    def investigate(
        self,
        dispute_summary: Dict[str, Any],
        evidence_items: List[Dict[str, Any]],
        contradictions: List[Dict[str, Any]],
        policy_excerpts: List[PolicyExcerpt]
    ) -> DisputeInvestigationReport:
        pass


class MockAIProvider(AIProvider):
    """
    Deterministic, offline AI Provider for development, continuous integration,
    and reproducible benchmark evaluation. Emulates deep reasoning over structured evidence.
    """

    def __init__(self, simulate_hallucination: bool = False, simulate_unsupported_claim: bool = False):
        self.simulate_hallucination = simulate_hallucination
        self.simulate_unsupported_claim = simulate_unsupported_claim

    def investigate(
        self,
        dispute_summary: Dict[str, Any],
        evidence_items: List[Dict[str, Any]],
        contradictions: List[Dict[str, Any]],
        policy_excerpts: List[PolicyExcerpt]
    ) -> DisputeInvestigationReport:
        item_map = {item.get("evidence_id"): item for item in evidence_items}
        conflicted_ids = [c.get("evidence_ids", []) for c in contradictions]
        flat_conflicted = [item for sublist in conflicted_ids for item in sublist]

        dispute_id = dispute_summary.get("dispute_id", "disp_unknown")
        network = str(dispute_summary.get("card_network", "visa")).upper()
        reason = str(dispute_summary.get("reason_code", "10.4"))
        amount = float(dispute_summary.get("amount_inr", 1000.0))

        claims: List[AIClaimItem] = []
        supporting_ev: List[str] = []
        missing_ev: List[str] = []
        risk_flags: List[str] = []

        # 1. Evaluate Identity / Telemetry [EV-001, EV-002]
        ev_ip = item_map.get("EV-001")
        ev_dev = item_map.get("EV-002")
        if ev_ip and ev_ip.get("status") == "VERIFIED":
            supporting_ev.append("EV-001")
        else:
            missing_ev.append("EV-001")

        if ev_dev and ev_dev.get("status") == "VERIFIED":
            supporting_ev.append("EV-002")
        else:
            missing_ev.append("EV-002")

        # 2. Evaluate Authentication [EV-003]
        ev_mfa = item_map.get("EV-003")
        if ev_mfa and ev_mfa.get("status") == "VERIFIED":
            supporting_ev.append("EV-003")
            claims.append(AIClaimItem(
                claim_id="CL-001",
                claim_text="Cardholder presence established via Two-Factor 3DS authentication protocol.",
                evidence_ids=["EV-003"],
                policy_document_id="DOC-3DS-SHIFT",
                confidence=0.95
            ))
        else:
            missing_ev.append("EV-003")

        # 3. Evaluate Carrier / Digital Delivery [EV-004, EV-005, EV-007]
        ev_carrier = item_map.get("EV-004")
        ev_gps = item_map.get("EV-005")
        ev_digital = item_map.get("EV-007")

        if ev_carrier and ev_carrier.get("status") in ("VERIFIED", "PARTIALLY_VERIFIED"):
            if "EV-004" not in flat_conflicted:
                supporting_ev.append("EV-004")
                carrier_evs = ["EV-004"]
                if ev_gps and ev_gps.get("status") == "VERIFIED" and "EV-005" not in flat_conflicted:
                    supporting_ev.append("EV-005")
                    carrier_evs.append("EV-005")
                claims.append(AIClaimItem(
                    claim_id="CL-002",
                    claim_text="Physical delivery completed by logistics carrier with verified tracking proof.",
                    evidence_ids=carrier_evs,
                    policy_document_id="DOC-CARRIER-POD",
                    confidence=0.92
                ))
            else:
                risk_flags.append("CARRIER_DELIVERY_CONTRADICTED")
        elif ev_digital and ev_digital.get("status") in ("VERIFIED", "PARTIALLY_VERIFIED"):
            if "EV-007" not in flat_conflicted:
                supporting_ev.append("EV-007")
                claims.append(AIClaimItem(
                    claim_id="CL-002",
                    claim_text="Digital SaaS consumption substantiated by verified application server access logs.",
                    evidence_ids=["EV-007"],
                    policy_document_id="DOC-DIGITAL-GOODS",
                    confidence=0.88
                ))
            else:
                risk_flags.append("DIGITAL_ACCESS_LOGS_CONTRADICTED")
        else:
            missing_ev.extend(["EV-004", "EV-007"])

        # 4. Evaluate Historical Orders [EV-006]
        ev_hist = item_map.get("EV-006")
        if ev_hist and ev_hist.get("status") in ("VERIFIED", "PARTIALLY_VERIFIED"):
            supporting_ev.append("EV-006")
            claims.append(AIClaimItem(
                claim_id="CL-003",
                claim_text="Prior undisputed transaction history establishes ongoing cardholder relationship under network rules.",
                evidence_ids=["EV-006"],
                policy_document_id="DOC-VISA-CE30" if network == "VISA" else "DOC-MC-FPT",
                confidence=0.90
            ))
        else:
            missing_ev.append("EV-006")

        # Injected test modes for adversarial verifier testing
        if self.simulate_hallucination:
            claims.append(AIClaimItem(
                claim_id="CL-HAL-999",
                claim_text="Cardholder explicitly confirmed order delivery via telephone call with store manager.",
                evidence_ids=["EV-FAKE-PHONE-CALL"],
                policy_document_id="DOC-NONEXISTENT-POLICY",
                confidence=0.99
            ))
        elif self.simulate_unsupported_claim:
            claims.append(AIClaimItem(
                claim_id="CL-UNS-888",
                claim_text="Customer has zero history of disputes across merchant platforms.",
                evidence_ids=[],
                policy_document_id="DOC-INTERNAL-RISK",
                confidence=0.85
            ))

        # Check contradictions
        if contradictions:
            risk_flags.append(f"{len(contradictions)}_EVIDENCE_CONTRADICTIONS_DETECTED")

        # Determine advisory strategy & action
        citations = [p.citation_text for p in policy_excerpts]

        if contradictions:
            recommended_action = "HITL_REVIEW"
            recommended_strategy = "CONTRADICTION_MANUAL_RECONCILIATION"
            confidence = 0.40
            risk_assessment = f"High Risk: {len(contradictions)} objective contradiction(s) found in carrier/telemetry data."
        elif len(supporting_ev) >= 3 and not contradictions:
            recommended_action = "AUTO_REPRESENT"
            recommended_strategy = f"{network}_COMPLIANCE_DEFENSE"
            confidence = min(0.95, 0.60 + 0.08 * len(supporting_ev))
            risk_assessment = "Low Risk: Strong multi-factor corroboration across identity, fulfillment, and network rules."
        elif len(supporting_ev) >= 1:
            recommended_action = "HITL_REVIEW"
            recommended_strategy = "PARTIAL_EVIDENCE_ENRICHMENT"
            confidence = 0.55
            risk_assessment = "Moderate Risk: Incomplete evidence packet requires human operational enrichment."
        else:
            recommended_action = "ACCEPT_LOSS"
            recommended_strategy = "LIABILITY_ACCEPTANCE_PREVENT_ARBITRATION"
            confidence = 0.20
            risk_assessment = "Unviable Defense: Insufficient supporting evidence; defending risks ₹1,500 penalty."

        claim_summary = (
            f"Advisory investigation for {network} dispute {dispute_id} (Reason {reason}, ₹{amount:,.2f}). "
            f"Identified {len(claims)} grounded claim(s) backed by {len(supporting_ev)} evidence item(s)."
        )

        return DisputeInvestigationReport(
            risk_assessment=risk_assessment,
            confidence=round(confidence, 2),
            claim_summary=claim_summary,
            claims=claims,
            supporting_evidence=supporting_ev,
            contradicting_evidence=flat_conflicted,
            missing_evidence=missing_ev,
            policy_citations=citations,
            recommended_strategy=recommended_strategy,
            recommended_action=recommended_action,
            reasoning_summary=(
                f"Evaluated telemetry and network policies for {network} {reason}. "
                f"Contradictions: {len(contradictions)}. Supporting evidence items: {supporting_ev}."
            ),
            risk_flags=risk_flags,
            provider_used="mock",
            model_version="sentinel-agent-v1-mock"
        )


class OpenAIProvider(AIProvider):
    """
    Live OpenAI Provider utilizing JSON Mode / Structured Output.
    Falls back gracefully to MockAIProvider if an API key is missing or network fails.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("OPENAI_MODEL", model)
        self._fallback = MockAIProvider()

    def investigate(
        self,
        dispute_summary: Dict[str, Any],
        evidence_items: List[Dict[str, Any]],
        contradictions: List[Dict[str, Any]],
        policy_excerpts: List[PolicyExcerpt]
    ) -> DisputeInvestigationReport:
        if not self.api_key or self.api_key.startswith("mock") or len(self.api_key) < 10:
            logger.info("No valid OPENAI_API_KEY detected; using deterministic MockAIProvider")
            return self._fallback.investigate(dispute_summary, evidence_items, contradictions, policy_excerpts)

        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key, timeout=10.0)

            sys_prompt = build_investigation_system_prompt()
            user_prompt = build_investigation_user_prompt(
                dispute_summary=dispute_summary,
                evidence_items=evidence_items,
                contradictions=contradictions,
                policy_excerpts=[p.model_dump() for p in policy_excerpts]
            )

            completion = client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format=DisputeInvestigationReport,
                temperature=0.1
            )
            report = completion.choices[0].message.parsed
            if report is not None:
                report.provider_used = f"openai/{self.model}"
                return report
        except Exception as e:
            logger.warning("OpenAI API call failed or unavailable; using MockAIProvider fallback", error=str(e))

        fallback_report = self._fallback.investigate(dispute_summary, evidence_items, contradictions, policy_excerpts)
        fallback_report.provider_used = "mock (openai fallback)"
        return fallback_report


def get_ai_provider() -> AIProvider:
    """Factory returning configured AIProvider instance."""
    provider_name = os.getenv("AI_PROVIDER", "").lower().strip()
    has_key = bool(os.getenv("OPENAI_API_KEY") and len(os.getenv("OPENAI_API_KEY", "").strip()) > 10)
    if provider_name in ("openai", "gpt") or (has_key and provider_name != "mock"):
        return OpenAIProvider()
    return MockAIProvider()

