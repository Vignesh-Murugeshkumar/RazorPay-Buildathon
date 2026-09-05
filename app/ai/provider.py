"""
SentinelDispute - Model Provider Abstraction.

Provides structured, verifiable AI investigation across two providers:
1. MockAIProvider: Deterministic, offline, reproducible reasoning for tests, CI, and local benchmarks.
2. OpenAIProvider: Live LLM provider utilizing Pydantic Structured Outputs with adversarial self-challenge.

Strict Safety Rule:
When AI_PROVIDER=openai, failures NEVER silently fall back to MockAIProvider.
Failures immediately route to HITL with explicit error provenance.
"""

import os
import json
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from app.ai.prompts import (
    DisputeInvestigationReport,
    AIClaimItem,
    EvidenceAssertion,
    PolicyAnalysisItem,
    ContradictionItem,
    MissingEvidenceItem,
    SelfChallengeReport,
    build_investigation_system_prompt,
    build_investigation_user_prompt,
    build_self_challenge_system_prompt,
    build_self_challenge_user_prompt
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
    and reproducible benchmark evaluation. Implements genuine evidence-to-policy
    deduction, separate win probability vs reasoning confidence, and self-challenge.
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
        flat_conflicted = set([item for sublist in conflicted_ids for item in sublist])

        dispute_id = dispute_summary.get("dispute_id", "disp_unknown")
        network = str(dispute_summary.get("card_network", "visa")).upper()
        reason = str(dispute_summary.get("reason_code", "10.4"))
        service_type = str(dispute_summary.get("service_type", "physical")).lower()

        claims: List[AIClaimItem] = []
        strongest_ev: List[EvidenceAssertion] = []
        weakest_ev: List[EvidenceAssertion] = []
        policy_analysis: List[PolicyAnalysisItem] = []
        contradiction_items: List[ContradictionItem] = []
        missing_ev: List[MissingEvidenceItem] = []
        uncertainties: List[str] = []

        retrieval_map = {p.document_id: p for p in policy_excerpts}
        top_ret_id = policy_excerpts[0].retrieval_id if policy_excerpts else "RET-001"

        # 1. Telemetry / Identity Analysis [EV-001, EV-002]
        ev_ip = item_map.get("EV-001")
        ev_dev = item_map.get("EV-002")
        ip_verified = ev_ip and ev_ip.get("status") == "VERIFIED"
        dev_verified = ev_dev and ev_dev.get("status") == "VERIFIED"

        if ip_verified:
            strongest_ev.append(EvidenceAssertion(evidence_id="EV-001", claim="Customer IP address matched historical profile", importance="HIGH"))
        else:
            weakest_ev.append(EvidenceAssertion(evidence_id="EV-001", claim="Customer IP address unverified or absent", importance="MEDIUM"))

        if dev_verified:
            strongest_ev.append(EvidenceAssertion(evidence_id="EV-002", claim="Persistent device fingerprint recognized", importance="HIGH"))
        else:
            weakest_ev.append(EvidenceAssertion(evidence_id="EV-002", claim="Device fingerprint absent from transaction telemetry", importance="MEDIUM"))

        # 2. Authentication Analysis [EV-003]
        ev_mfa = item_map.get("EV-003")
        if ev_mfa and ev_mfa.get("status") == "VERIFIED":
            strongest_ev.append(EvidenceAssertion(evidence_id="EV-003", claim="EMV 3DS / MFA Challenge verified with liability shift", importance="HIGH"))
            claims.append(AIClaimItem(
                claim_id="CL-001",
                claim="Cardholder authentication established via verified EMV 3DS OTP protocol [EV-003].",
                evidence_ids=["EV-003"],
                support="DIRECT",
                confidence=95,
                policy_document_id="DOC-3DS-SHIFT"
            ))
            ret = retrieval_map.get("DOC-3DS-SHIFT")
            policy_analysis.append(PolicyAnalysisItem(
                policy_document_id="DOC-3DS-SHIFT",
                section=ret.section_id if ret else "SEC-3DS-LIABILITY",
                retrieval_id=ret.retrieval_id if ret else top_ret_id,
                requirement="3-D Secure EMV authentication liability shift",
                status="SATISFIED",
                evidence_ids=["EV-003"]
            ))
        else:
            missing_ev.append(MissingEvidenceItem(
                requirement="3DS / Multi-Factor Authentication",
                reason="No verified OTP or biometric challenge token recorded for cardholder validation"
            ))

        # 3. Fulfillment Evidence Analysis [EV-004, EV-005, EV-007]
        ev_carrier = item_map.get("EV-004")
        ev_gps = item_map.get("EV-005")
        ev_digital = item_map.get("EV-007")

        carrier_verified = ev_carrier and ev_carrier.get("status") in ("VERIFIED", "PARTIALLY_VERIFIED") and "EV-004" not in flat_conflicted
        digital_verified = ev_digital and ev_digital.get("status") in ("VERIFIED", "PARTIALLY_VERIFIED") and "EV-007" not in flat_conflicted

        if carrier_verified:
            carrier_ids = ["EV-004"]
            if ev_gps and ev_gps.get("status") == "VERIFIED" and "EV-005" not in flat_conflicted:
                carrier_ids.append("EV-005")
                strongest_ev.append(EvidenceAssertion(evidence_id="EV-005", claim="GPS coordinates matched customer destination address within 50m", importance="HIGH"))

            strongest_ev.append(EvidenceAssertion(evidence_id="EV-004", claim="Carrier consignment tracking confirms physical delivery to cardholder", importance="HIGH"))
            claims.append(AIClaimItem(
                claim_id="CL-002",
                claim="Logistics carrier verified successful physical delivery to recipient address [EV-004].",
                evidence_ids=carrier_ids,
                support="DIRECT",
                confidence=92,
                policy_document_id="DOC-CARRIER-POD"
            ))
            ret = retrieval_map.get("DOC-CARRIER-POD")
            policy_analysis.append(PolicyAnalysisItem(
                policy_document_id="DOC-CARRIER-POD",
                section=ret.section_id if ret else "SEC-CARRIER-VERIFICATION",
                retrieval_id=ret.retrieval_id if ret else top_ret_id,
                requirement="Carrier physical proof of delivery with tracking confirmation",
                status="SATISFIED",
                evidence_ids=carrier_ids
            ))
        elif digital_verified:
            strongest_ev.append(EvidenceAssertion(evidence_id="EV-007", claim="Application server access logs confirm active digital service consumption", importance="HIGH"))
            claims.append(AIClaimItem(
                claim_id="CL-002",
                claim="Cardholder digital service access substantiated by timestamped server logs [EV-007].",
                evidence_ids=["EV-007"],
                support="DIRECT",
                confidence=88,
                policy_document_id="DOC-DIGITAL-GOODS"
            ))
            ret = retrieval_map.get("DOC-DIGITAL-GOODS")
            policy_analysis.append(PolicyAnalysisItem(
                policy_document_id="DOC-DIGITAL-GOODS",
                section=ret.section_id if ret else "SEC-DIGITAL-FULFILLMENT",
                retrieval_id=ret.retrieval_id if ret else top_ret_id,
                requirement="Digital SaaS consumption substantiated by server access logs",
                status="SATISFIED",
                evidence_ids=["EV-007"]
            ))
        else:
            if service_type == "digital_saas":
                missing_ev.append(MissingEvidenceItem(
                    requirement="Digital Service Access Logs",
                    reason="Server access logs proving cardholder account login and consumption are absent"
                ))
            else:
                missing_ev.append(MissingEvidenceItem(
                    requirement="Carrier Proof of Delivery (POD)",
                    reason="No verified carrier tracking or delivery receipt proving merchandise receipt"
                ))

        # 4. Historical Transaction Network Rules [EV-006]
        ev_hist = item_map.get("EV-006")
        target_doc = "DOC-VISA-CE30" if network == "VISA" else "DOC-MC-FPT"
        ret_net = retrieval_map.get(target_doc)

        if ev_hist and ev_hist.get("status") in ("VERIFIED", "PARTIALLY_VERIFIED"):
            strongest_ev.append(EvidenceAssertion(evidence_id="EV-006", claim=f"Prior undisputed orders qualify under {network} chargeback rules", importance="HIGH"))
            claims.append(AIClaimItem(
                claim_id="CL-003",
                claim=f"Historical undisputed transaction history establishes qualified cardholder relationship under {network} rules [EV-006].",
                evidence_ids=["EV-006"],
                support="DIRECT",
                confidence=90,
                policy_document_id=target_doc
            ))
            policy_analysis.append(PolicyAnalysisItem(
                policy_document_id=target_doc,
                section=ret_net.section_id if ret_net else "SEC-CORE",
                retrieval_id=ret_net.retrieval_id if ret_net else top_ret_id,
                requirement=f"{network} pre-dispute transaction lookback qualification",
                status="SATISFIED",
                evidence_ids=["EV-006"]
            ))
        else:
            missing_ev.append(MissingEvidenceItem(
                requirement=f"{network} Historical Transactions",
                reason="Insufficient historical undisputed orders within required lookback window"
            ))
            policy_analysis.append(PolicyAnalysisItem(
                policy_document_id=target_doc,
                section=ret_net.section_id if ret_net else "SEC-CORE",
                retrieval_id=ret_net.retrieval_id if ret_net else top_ret_id,
                requirement=f"{network} pre-dispute transaction lookback qualification",
                status="UNSATISFIED",
                evidence_ids=[]
            ))

        # 5. Process Contradictions
        for c in contradictions:
            c_ids = c.get("evidence_ids", [])
            sev = c.get("severity", "HIGH").upper()
            desc = c.get("description", "Objective evidentiary conflict")
            contradiction_items.append(ContradictionItem(evidence_ids=c_ids, severity=sev, description=desc))
            for cid in c_ids:
                weakest_ev.append(EvidenceAssertion(evidence_id=cid, claim=f"Contradicted evidence: {desc}", importance="HIGH"))

        # Injected test modes for testing verifier
        if self.simulate_hallucination:
            claims.append(AIClaimItem(
                claim_id="CL-HAL-999",
                claim="Cardholder explicitly confirmed order delivery via telephone call with store manager [EV-FAKE-PHONE-CALL].",
                evidence_ids=["EV-FAKE-PHONE-CALL"],
                support="DIRECT",
                confidence=99,
                policy_document_id="DOC-NONEXISTENT-POLICY"
            ))
        elif self.simulate_unsupported_claim:
            claims.append(AIClaimItem(
                claim_id="CL-UNS-888",
                claim="Customer has zero history of disputes across merchant platforms.",
                evidence_ids=[],
                support="INFERRED",
                confidence=85,
                policy_document_id="DOC-INTERNAL-RISK"
            ))

        # 6. Calculate Initial Assessment, Win Probability, and Reasoning Confidence
        has_high_contradiction = any(c.severity == "HIGH" for c in contradiction_items)
        has_fulfillment = carrier_verified or digital_verified
        has_history = ev_hist and ev_hist.get("status") in ("VERIFIED", "PARTIALLY_VERIFIED")
        has_auth = ev_mfa and ev_mfa.get("status") == "VERIFIED"

        if has_high_contradiction:
            case_assessment = "CONTRADICTORY"
            win_probability = 0.25
            reasoning_confidence = 88  # highly confident that evidence is contradictory
            recommended_action = "HITL_REVIEW"
            uncertainties.append("Objective conflict between delivery proof and telemetry records")
        elif has_fulfillment and (has_history or has_auth):
            case_assessment = "DEFENSIBLE"
            win_probability = 0.88
            reasoning_confidence = 92
            recommended_action = "AUTO_REPRESENT"
        elif has_fulfillment or has_history or has_auth:
            case_assessment = "INSUFFICIENT_EVIDENCE"
            win_probability = 0.50
            reasoning_confidence = 72
            recommended_action = "HITL_REVIEW"
            uncertainties.append("Partial evidence package; missing corroborating identity or delivery proofs")
        else:
            case_assessment = "NOT_DEFENSIBLE"
            win_probability = 0.15
            reasoning_confidence = 90
            recommended_action = "ACCEPT_LOSS"
            uncertainties.append("No material defense evidence available to refute chargeback claim")

        # 7. Self-Challenge Pass (Devil's Advocate Analysis)
        vulnerabilities = []
        counter_args = []
        revised_action = recommended_action
        adjustment_made = False

        if case_assessment == "DEFENSIBLE":
            if not ip_verified or not dev_verified:
                vulnerabilities.append("Identity matching relies on partial telemetry (IP or Device missing).")
                counter_args.append("Cardholder could claim friendly fraud by family member on shared network.")
            if missing_ev:
                weak_req = missing_ev[0].requirement
            else:
                weak_req = "Continuous cardholder identity lock"

            # Check if self-challenge uncovers any subtle flaw
            if flat_conflicted:
                adjustment_made = True
                revised_action = "HITL_REVIEW"
                rationale = "Self-challenge caught unaddressed evidence conflict. Demoting from AUTO_REPRESENT to HITL."
                reasoning_confidence = min(reasoning_confidence, 65)
                win_probability = min(win_probability, 0.45)
            else:
                rationale = "Self-challenge examined alternative customer theories; corroborated fulfillment and network lookback withstand critique."
        else:
            weak_req = missing_ev[0].requirement if missing_ev else "Delivery verification"
            vulnerabilities.append(f"Defense fails primary requirement: {weak_req}")
            counter_args.append("Issuing bank will reject representment without primary fulfillment proof.")
            rationale = f"Self-challenge affirms non-defensible or ambiguous status due to {weak_req}."

        self_challenge = SelfChallengeReport(
            vulnerabilities_found=vulnerabilities,
            weakest_requirement=weak_req,
            alternative_interpretation=counter_args[0] if counter_args else "Standard consumer denial",
            adjustment_made=adjustment_made,
            original_action=recommended_action,
            revised_action=revised_action,
            rationale=rationale
        )

        final_action = revised_action
        reasoning = (
            f"Advisory investigation for {network} dispute {dispute_id} (Reason {reason}). "
            f"Assessment: {case_assessment}. Win probability: {win_probability*100:.1f}%, Reasoning confidence: {reasoning_confidence}%. "
            f"Strongest evidence: {[e.evidence_id for e in strongest_ev]}. Contradictions: {len(contradiction_items)}. "
            f"Self-challenge: {self_challenge.rationale}"
        )

        return DisputeInvestigationReport(
            case_assessment=case_assessment,
            win_probability=win_probability,
            reasoning_confidence=reasoning_confidence,
            strongest_evidence=strongest_ev,
            weakest_evidence=weakest_ev,
            claims=claims,
            policy_analysis=policy_analysis,
            contradictions=contradiction_items,
            missing_evidence=missing_ev,
            uncertainties=uncertainties,
            recommended_action=final_action,
            reasoning=reasoning,
            self_challenge=self_challenge,
            provider_used="mock",
            model_version="sentinel-agent-v2-mock"
        )


class OpenAIProvider(AIProvider):
    """
    Live OpenAI Provider utilizing Pydantic Structured Outputs.
    Executes a 2-pass investigation:
      Pass 1: Structured investigation over evidence and retrieved policies.
      Pass 2: Structured adversarial self-challenge.

    Strict Safety Invariant:
    If OpenAI fails, times out, or has an invalid key, NEVER fall back to MockAIProvider.
    Immediately raise or return an explicit failover report routed to HITL.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("OPENAI_MODEL", model)

    def investigate(
        self,
        dispute_summary: Dict[str, Any],
        evidence_items: List[Dict[str, Any]],
        contradictions: List[Dict[str, Any]],
        policy_excerpts: List[PolicyExcerpt]
    ) -> DisputeInvestigationReport:
        if not self.api_key or self.api_key.startswith("mock") or len(self.api_key.strip()) < 10:
            logger.error("AI_PROVIDER=openai was specified, but OPENAI_API_KEY is missing or invalid. Failing to HITL.")
            return self._create_provider_failure_report(
                error_type="MISSING_OR_INVALID_API_KEY",
                error_msg="OPENAI_API_KEY is not configured. Autonomous representment blocked; routed to HITL review.",
                policy_excerpts=policy_excerpts
            )

        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key, timeout=12.0)

            # Pass 1: Initial Structured Investigation
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
            if report is None:
                raise ValueError("OpenAI returned an empty parsed response structure.")

            report.provider_used = f"openai/{self.model}"
            report.model_version = f"sentinel-agent-v2-openai-{self.model}"

            # Pass 2: Adversarial Self-Challenge (Second Pass)
            try:
                sc_sys_prompt = build_self_challenge_system_prompt()
                sc_user_prompt = build_self_challenge_user_prompt(
                    initial_report=report.model_dump(),
                    evidence_items=evidence_items,
                    contradictions=contradictions
                )
                sc_completion = client.beta.chat.completions.parse(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": sc_sys_prompt},
                        {"role": "user", "content": sc_user_prompt}
                    ],
                    response_format=SelfChallengeReport,
                    temperature=0.2
                )
                sc_report = sc_completion.choices[0].message.parsed
                if sc_report:
                    report.self_challenge = sc_report
                    if sc_report.adjustment_made and sc_report.revised_action in ("AUTO_REPRESENT", "HITL", "ACCEPT"):
                        logger.info(
                            "OpenAI self-challenge adjusted recommendation",
                            original=report.recommended_action,
                            revised=sc_report.revised_action
                        )
                        report.recommended_action = sc_report.revised_action
                        if sc_report.revised_action in ("HITL", "ACCEPT") and report.reasoning_confidence > 70:
                            report.reasoning_confidence = 65
            except Exception as sc_err:
                logger.warning("Self-challenge pass encountered an error; keeping initial report", error=str(sc_err))

            return report

        except Exception as e:
            logger.error("OpenAI API call failed. Refusing silent fallback to MockAIProvider. Routing to HITL.", error=str(e))
            return self._create_provider_failure_report(
                error_type=type(e).__name__,
                error_msg=f"OpenAI API invocation failed: {str(e)[:160]}",
                policy_excerpts=policy_excerpts
            )

    def _create_provider_failure_report(
        self,
        error_type: str,
        error_msg: str,
        policy_excerpts: List[PolicyExcerpt]
    ) -> DisputeInvestigationReport:
        """Constructs a deterministic fail-safe report routing to HITL when OpenAI fails."""
        citations = [p.citation_text for p in policy_excerpts]
        return DisputeInvestigationReport(
            case_assessment="INSUFFICIENT_EVIDENCE",
            win_probability=0.20,
            reasoning_confidence=0,
            strongest_evidence=[],
            weakest_evidence=[],
            claims=[],
            policy_analysis=[],
            contradictions=[],
            missing_evidence=[MissingEvidenceItem(
                requirement="Live AI Investigation",
                reason=f"Provider failure: {error_type}. Automated reasoning unavailable."
            )],
            uncertainties=[f"Live AI Provider error: {error_msg}"],
            recommended_action="HITL_REVIEW",
            reasoning=f"AI Provider failure ({error_type}): {error_msg}. Autonomous action strictly blocked; routed to HITL queue.",
            self_challenge=SelfChallengeReport(
                vulnerabilities_found=[f"Provider error: {error_type}"],
                weakest_requirement="Live LLM Availability",
                alternative_interpretation="Unverified case requires manual review",
                adjustment_made=True,
                original_action="AUTO_REPRESENT",
                revised_action="HITL_REVIEW",
                rationale=f"Failed safe to HITL due to {error_type}"
            ),
            provider_used=f"openai-failed/{error_type}",
            model_version="failover-hitl-v2"
        )


def get_ai_provider(provider_override: Optional[str] = None) -> AIProvider:
    """Factory returning configured AIProvider instance."""
    provider_name = (provider_override or os.getenv("AI_PROVIDER", "mock")).lower().strip()
    if provider_name in ("openai", "gpt"):
        return OpenAIProvider()
    return MockAIProvider()
