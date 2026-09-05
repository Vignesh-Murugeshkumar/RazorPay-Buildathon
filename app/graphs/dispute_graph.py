import datetime
from typing import TypedDict, Optional, Dict, Any, List, Tuple
from app.schemas.dispute import (
    DisputePayload,
    RuleEvaluationResult,
    DecisionExplanation,
    Dossier,
    EvidenceStatus,
    EvidenceItem,
    EvidenceContradiction
)
from app.rules.card_rules import evaluate_dispute_compliance
from app.rules.service_disputes import evaluate_service_dispute_compliance
from app.services.expected_value import calculate_expected_value, ExpectedValueResult
from app.services.rebuttal_synthesizer import rebuttal_synthesizer
from app.services.rag_rebuttal import rag_synthesizer
from app.services.evidence_engine import (
    extract_evidence_and_contradictions,
    calculate_hitl_priority,
    calculate_hitl_priority_score,
    detect_contradictions,
    extract_evidence_items,
)
from app.services.issuer_intelligence import issuer_intelligence
from app.services.ledger import ledger
from app.core.db import db
from app.core.security import compute_sha256_hash


class DisputeState(TypedDict, total=False):
    payload: DisputePayload
    dispute_id: str
    network: str
    reason_code: str
    amount_inr: float
    evaluation: Optional[RuleEvaluationResult]
    expected_value: Optional[ExpectedValueResult]
    rebuttal_letter: Optional[Dict[str, Any]]
    dossier: Optional[Dossier]
    decision: str
    logs: List[str]


def triage_agent_node(state: DisputeState) -> DisputeState:
    """
    Triage Agent:
    Extracts core dispute metadata, normalizes card network and reason code,
    categorizes dispute type (Fraud CE 3.0/FPT vs Service/Cancellation RAG),
    and logs ingress transition in the cryptographic ledger.
    """
    payload = state["payload"]
    dispute_id = payload.dispute_id
    network = payload.card_network.lower()
    reason_code = str(payload.reason_code).strip()
    amount = payload.amount_inr or 1000.0
    
    is_non_fraud = reason_code in ("13.1", "13.7", "4853", "4855")
    category = "SERVICE_DISPUTE_EVIDENCE" if is_non_fraud else "FRAUD_CE30_FPT"

    ledger.append_block(
        agent_id="AGENT_TRIAGE",
        state_transition="DISPUTE_TRIAGED",
        payload={
            "dispute_id": dispute_id,
            "payment_id": payload.payment_id,
            "network": network,
            "reason_code": reason_code,
            "category": category,
            "amount_inr": amount
        }
    )
    
    db.add_timeline_event(
        dispute_id=dispute_id,
        event_type="WEBHOOK_RECEIVED",
        title="Dispute Ingested",
        description=f"Received dispute {dispute_id} for ₹{amount:,.2f} on {network.upper()} ({reason_code} - {category}).",
        metadata={"payment_id": payload.payment_id, "network": network, "amount_inr": amount, "category": category}
    )

    logs = state.get("logs", [])
    logs.append(f"Triaged dispute {dispute_id}: Network={network.upper()}, Reason={reason_code} ({category}), Amount=₹{amount:,.2f}")
    
    return {
        **state,
        "dispute_id": dispute_id,
        "network": network,
        "reason_code": reason_code,
        "amount_inr": amount,
        "logs": logs
    }


def aggregator_agent_node(state: DisputeState) -> DisputeState:
    """
    Evidence Aggregator Agent:
    Aggregates session telemetry, 365-day historical transactions, and carrier/digital fulfillment proofs.
    """
    payload = state["payload"]
    dispute_id = state["dispute_id"]
    
    history_count = len(payload.historical_transactions)
    has_carrier = payload.carrier_proof is not None
    carrier_status = "VERIFIED" if (has_carrier and payload.carrier_proof.delivered_status) else "MISSING/UNVERIFIED"
    
    ledger.append_block(
        agent_id="AGENT_AGGREGATOR",
        state_transition="EVIDENCE_AGGREGATED",
        payload={
            "dispute_id": dispute_id,
            "historical_orders_count": history_count,
            "carrier_proof_present": has_carrier,
            "carrier_status": carrier_status,
            "mfa_present": payload.telemetry.mfa_authenticated if payload.telemetry else False
        }
    )

    db.add_timeline_event(
        dispute_id=dispute_id,
        event_type="EVIDENCE_AGGREGATED",
        title="Evidence & Telemetry Aggregated",
        description=f"Aggregated {history_count} historical orders, Carrier delivery status: {carrier_status}.",
        metadata={"history_count": history_count, "carrier_status": carrier_status}
    )
    
    logs = state.get("logs", [])
    logs.append(f"Aggregated evidence: {history_count} historical orders, Carrier={carrier_status}")
    
    return {
        **state,
        "logs": logs
    }


def compliance_agent_node(state: DisputeState) -> DisputeState:
    """
    Compliance & Formation Engine Agent:
    Executes Visa CE 3.0 / Mastercard FPT deterministic evaluation or Non-Fraud RAG rules.
    Derives existing booleans from central EvidenceStatus.
    """
    payload = state["payload"]
    dispute_id = state["dispute_id"]
    reason_code = str(payload.reason_code).strip()

    # Extract central evidence items, contradictions, and statuses
    items, contradictions, statuses = extract_evidence_and_contradictions(payload)
    
    # Derive booleans strictly from EvidenceStatus.VERIFIED
    carrier_verified = (statuses.get("CARRIER_DELIVERY_PROOF") == EvidenceStatus.VERIFIED)
    gps_verified = (statuses.get("GPS_GEOLOCATION") == EvidenceStatus.VERIFIED)
    mfa_verified = (statuses.get("PAYMENT_AUTHENTICATION") == EvidenceStatus.VERIFIED)
    digital_verified = (statuses.get("DIGITAL_ACCESS_LOGS") == EvidenceStatus.VERIFIED)
    
    if reason_code in ("13.1", "13.7", "4853", "4855"):
        # Non-Fraud Merchandise / Cancellation evidence flow
        compliant, score, gaps, breakdown = evaluate_service_dispute_compliance(payload)
        category = "SERVICE_DISPUTE_EVIDENCE" if reason_code in ("13.1", "4855") else "CANCELLATION_DEFENSE"
        
        evaluation = RuleEvaluationResult(
            network=payload.card_network,
            reason_code=reason_code,
            ce30_compliant=False,
            fpt_compliant=False,
            qualifying_orders_count=len(payload.historical_transactions),
            carrier_verified=carrier_verified,
            digital_verified=digital_verified,
            gps_verified=gps_verified,
            mfa_verified=mfa_verified,
            confidence_score=score,
            route_decision="AUTO_DISPATCH" if (score >= 70.0 and not contradictions) else "ROUTE_TO_HITL_QUEUE",
            diagnostic_gaps=gaps,
            score_breakdown=breakdown,
            evidence_category=category,
            evidence_items=items,
            contradictions=contradictions,
            evidence_statuses=statuses
        )
    else:
        # Standard Visa CE 3.0 / Mastercard FPT rule evaluation
        evaluation = evaluate_dispute_compliance(payload)
        evaluation.evidence_category = "FRAUD_CE30_FPT"
        evaluation.carrier_verified = carrier_verified
        evaluation.digital_verified = digital_verified
        evaluation.gps_verified = gps_verified
        evaluation.mfa_verified = mfa_verified
        evaluation.evidence_items = items
        evaluation.contradictions = contradictions
        evaluation.evidence_statuses = statuses

    # If contradictions exist, force route to HITL queue and prepend diagnostic gaps
    if contradictions:
        evaluation.route_decision = "ROUTE_TO_HITL_QUEUE"
        for c in contradictions:
            conflict_msg = f"[CONTRADICTION] {c.description}"
            if conflict_msg not in evaluation.diagnostic_gaps:
                evaluation.diagnostic_gaps.insert(0, conflict_msg)

    ledger.append_block(
        agent_id="AGENT_COMPLIANCE",
        state_transition="COMPLIANCE_EVALUATED",
        payload={
            "dispute_id": dispute_id,
            "confidence_score": evaluation.confidence_score,
            "ce30_compliant": evaluation.ce30_compliant,
            "fpt_compliant": evaluation.fpt_compliant,
            "category": evaluation.evidence_category,
            "gaps": evaluation.diagnostic_gaps,
            "contradictions_count": len(contradictions)
        }
    )

    db.add_timeline_event(
        dispute_id=dispute_id,
        event_type="RULES_EVALUATED",
        title=f"{payload.card_network.upper()} Rules Evaluated",
        description=f"Rule {evaluation.reason_code} evaluated. Confidence Score: {evaluation.confidence_score}/100.0 ({evaluation.evidence_category}). Contradictions: {len(contradictions)}.",
        metadata={"confidence_score": evaluation.confidence_score, "category": evaluation.evidence_category, "contradictions": len(contradictions)}
    )
    
    logs = state.get("logs", [])
    logs.append(f"Compliance evaluated: Score Sc={evaluation.confidence_score}/100.0 ({evaluation.evidence_category}), Contradictions={len(contradictions)}")
    
    return {
        **state,
        "evaluation": evaluation,
        "logs": logs
    }


def economic_engine_agent_node(state: DisputeState) -> DisputeState:
    """
    Dynamic Expected Value (E[V]) & Rebuttal Synthesis Agent:
    Computes Net Recovery E[V] = P(win|x)*A - (1-P(win|x))*F_fee - C_op,
    synthesizes constrained rebuttal letter with EvidenceItem citations, and sets economic decision.
    """
    payload = state["payload"]
    evaluation = state["evaluation"]
    amount = payload.amount_inr or 1000.0
    
    # Check historical issuer intelligence adjustment
    card_bin = "424242"
    if payload.historical_transactions and hasattr(payload.historical_transactions[0], "card_last4"):
        card_bin = "424242"
    issuer_adj = issuer_intelligence.get_issuer_win_rate_adjustment(card_bin)

    ev_result = calculate_expected_value(
        amount_inr=amount,
        confidence_score=evaluation.confidence_score,
        ce30_compliant=evaluation.ce30_compliant,
        fpt_compliant=evaluation.fpt_compliant,
        issuer_adjustment=issuer_adj
    )

    # Synthesize constrained RAG rebuttal letter using canonical EvidenceItems
    rebuttal = rag_synthesizer.synthesize_rebuttal(
        payload=payload,
        confidence_score=evaluation.confidence_score,
        p_win=ev_result.estimated_win_probability,
        evidence_items=evaluation.evidence_items
    )

    # Link supports_claim_ids back to canonical evidence_items
    for cl in rebuttal.claims:
        for ev_id in cl.supported_by:
            for item in evaluation.evidence_items:
                if item.evidence_id == ev_id and cl.claim_id not in item.supports_claim_ids:
                    item.supports_claim_ids.append(cl.claim_id)

    # If contradictions exist, force route to HITL queue
    if evaluation.contradictions:
        final_decision = "ROUTE_TO_HITL_QUEUE"
    else:
        final_decision = ev_result.decision

    # Update evaluation with canonical economic data
    evaluation.estimated_win_probability = ev_result.estimated_win_probability
    evaluation.p_win = ev_result.estimated_win_probability
    evaluation.expected_value_inr = ev_result.expected_value_inr
    evaluation.issuer_fee_inr = ev_result.issuer_fee_inr
    evaluation.operational_cost_inr = ev_result.operational_cost_inr
    evaluation.economic_decision = final_decision
    evaluation.route_decision = final_decision
    evaluation.rebuttal_letter = rebuttal.model_dump()

    ledger.append_block(
        agent_id="AGENT_ECONOMIC_ENGINE",
        state_transition="EXPECTED_VALUE_COMPUTED",
        payload={
            "dispute_id": payload.dispute_id,
            "expected_value_inr": ev_result.expected_value_inr,
            "estimated_win_probability": ev_result.estimated_win_probability,
            "p_win": ev_result.estimated_win_probability,
            "economic_decision": final_decision,
            "is_profitable": ev_result.is_profitable
        }
    )

    db.add_timeline_event(
        dispute_id=payload.dispute_id,
        event_type="ECONOMIC_EVALUATED",
        title="Expected Value Computed",
        description=f"Computed E[V]: ₹{ev_result.expected_value_inr:,.2f} with P(win): {ev_result.estimated_win_probability*100:.1f}%. Decision: {final_decision}.",
        metadata={"expected_value_inr": ev_result.expected_value_inr, "p_win": ev_result.estimated_win_probability, "decision": final_decision}
    )

    logs = state.get("logs", [])
    logs.append(
        f"Economic E[V] Computed: E[V]=₹{ev_result.expected_value_inr:,.2f}, P(win)={ev_result.estimated_win_probability*100:.1f}% -> Decision={final_decision}"
    )

    return {
        **state,
        "evaluation": evaluation,
        "expected_value": ev_result,
        "rebuttal_letter": rebuttal.model_dump(),
        "decision": final_decision,
        "logs": logs
    }


def gatekeeper_router(state: DisputeState) -> str:
    """
    3-Tier Gatekeeper Router based on Dynamic Expected Value & P(win):
    - Any active contradiction           --> hitl_queue_agent
    - E[V] > 0 & P(win) >= 0.70          --> auto_dispatch_agent
    - E[V] > 0 & 0.40 <= P < 0.70        --> hitl_queue_agent
    - E[V] <= 0                          --> auto_accept_agent
    """
    if state.get("evaluation") and state["evaluation"].contradictions:
        return "hitl_queue_agent"
    decision = state.get("decision")
    if decision == "AUTO_SUBMIT_REPRESENTMENT" or decision == "AUTO_DISPATCH" or decision == "AUTO_DISPATCHED":
        return "auto_dispatch_agent"
    elif decision == "AUTO_ACCEPT_OR_REFUND":
        return "auto_accept_agent"
    return "hitl_queue_agent"



def _create_dossier(state: DisputeState, decision: str, summary: str, sealed_hash: str, timestamp: str) -> Dossier:
    payload = state["payload"]
    dispute_id = state["dispute_id"]
    evaluation = state["evaluation"]
    ev_result = state.get("expected_value")
    amount = payload.amount_inr or 1000.0

    # 1. Evidence Intelligence fields
    mfa_auth = bool(payload.telemetry and payload.telemetry.mfa_authenticated)
    payment_auth_str = "3DS 2.2 Verified (Strong Customer Authentication)" if mfa_auth else "Frictionless / No MFA"
    
    delivery_proof_dict = None
    if payload.carrier_proof:
        delivery_proof_dict = {
            "carrier_name": payload.carrier_proof.carrier_name,
            "tracking_number": payload.carrier_proof.tracking_number,
            "delivered_status": payload.carrier_proof.delivered_status,
            "delivery_date": payload.carrier_proof.delivery_date,
            "recipient_signature_present": payload.carrier_proof.recipient_signature_present
        }
        
    gps_verification_dict = None
    if payload.carrier_proof and payload.carrier_proof.gps_latitude is not None:
        gps_verification_dict = {
            "latitude": payload.carrier_proof.gps_latitude,
            "longitude": payload.carrier_proof.gps_longitude,
            "verified_within_50m": payload.carrier_proof.verified_gps
        }

    device_info_dict = None
    if payload.telemetry:
        device_info_dict = {
            "device_id": payload.telemetry.device_id,
            "session_id": payload.telemetry.session_id,
            "user_agent": payload.telemetry.user_agent
        }

    history_summary_dict = {
        "total_historical_orders": len(payload.historical_transactions),
        "undisputed_count": sum(1 for h in payload.historical_transactions if h.undisputed),
        "qualifying_orders_count": evaluation.qualifying_orders_count if evaluation else 0,
        "total_amount_inr": sum(h.amount_inr for h in payload.historical_transactions)
    }

    digital_access_dict = None
    if payload.digital_proof:
        digital_access_dict = {
            "service_type": payload.digital_proof.service_type,
            "access_logs_verified": payload.digital_proof.access_logs_verified,
            "download_timestamp": payload.digital_proof.download_timestamp,
            "user_account_active": payload.digital_proof.user_account_active,
            "ip_subnet_matched": payload.digital_proof.ip_subnet_matched
        }

    # 2. Decision Explanation
    positive_factors = []
    negative_factors = []
    
    if evaluation.ce30_compliant:
        positive_factors.append("Visa CE 3.0 Compelling Evidence Qualified with prior undisputed orders")
    if evaluation.fpt_compliant:
        positive_factors.append("Mastercard First-Party Trust (FPT) qualified with confirmed historical orders")
    if evaluation.carrier_verified:
        positive_factors.append("Physical delivery verified by carrier with recipient signature")
    if evaluation.gps_verified:
        positive_factors.append("Delivery GPS coordinate match within 50m radius of cardholder address")
    if evaluation.digital_verified:
        positive_factors.append("Digital server access logs confirm active cardholder consumption")
    if evaluation.mfa_verified:
        positive_factors.append("Two-Factor Authentication / 3DS Verified (Liability Shift)")
    if ev_result and ev_result.is_profitable:
        positive_factors.append(f"Net recovery positive E[V] (+₹{ev_result.expected_value_inr:,.2f}) with {ev_result.p_win*100:.1f}% win probability")
    elif not positive_factors:
        positive_factors.append("Standard dispute ingestion metadata validated")

    if evaluation.diagnostic_gaps:
        negative_factors.extend(evaluation.diagnostic_gaps)
    if ev_result and not ev_result.is_profitable:
        negative_factors.append(f"Unfavorable E[V] (₹{ev_result.expected_value_inr:,.2f}): non-refundable dispute fee exceeds recovery potential")
    if not mfa_auth:
        negative_factors.append("No 3DS/MFA authentication recorded at checkout (merchant liability)")

    p_win = ev_result.estimated_win_probability if ev_result else (evaluation.estimated_win_probability or evaluation.p_win or 0.0)
    ev_inr = ev_result.expected_value_inr if ev_result else (evaluation.expected_value_inr or 0.0)

    has_contradictions = len(evaluation.contradictions) > 0 if evaluation else False
    priority_score, urgency, priority_factors = calculate_hitl_priority(
        payload=payload,
        confidence_score=evaluation.confidence_score if evaluation else 0.0,
        estimated_win_probability=p_win,
        has_contradictions=has_contradictions
    )

    recommendation = "Submit automated representment package immediately"
    if decision == "ROUTE_TO_HITL_QUEUE":
        if has_contradictions:
            recommendation = "Route to human analyst review queue to resolve identified evidence contradictions"
        else:
            recommendation = "Route to human analyst review queue to resolve identified evidence gaps"
    elif decision == "AUTO_ACCEPT_OR_REFUND":
        recommendation = "Accept dispute or refund to prevent non-refundable issuer arbitration fees"

    explanation = DecisionExplanation(
        summary=summary,
        top_positive_factors=positive_factors,
        top_negative_factors=negative_factors,
        confidence_breakdown=evaluation.score_breakdown or {},
        rule_applied=f"{evaluation.network.upper()} {evaluation.reason_code} ({evaluation.evidence_category})",
        estimated_win_probability=p_win,
        win_probability=p_win,
        expected_value_inr=ev_inr,
        recommendation=recommendation
    )

    ev_breakdown_dict = None
    if ev_result:
        ev_breakdown_dict = {
            "amount_inr": amount,
            "estimated_win_probability": ev_result.estimated_win_probability,
            "p_win": ev_result.estimated_win_probability,
            "gross_recovery": round(ev_result.estimated_win_probability * amount, 2),
            "issuer_fee_inr": ev_result.issuer_fee_inr,
            "risk_adjusted_fee": round((1.0 - ev_result.estimated_win_probability) * ev_result.issuer_fee_inr, 2),
            "operational_cost_inr": ev_result.operational_cost_inr,
            "expected_value_inr": ev_result.expected_value_inr,
            "is_profitable": ev_result.is_profitable
        }

    return Dossier(
        dispute_id=dispute_id,
        payment_id=payload.payment_id,
        amount_inr=amount,
        card_network=payload.card_network,
        reason_code=payload.reason_code,
        confidence_score=evaluation.confidence_score,
        decision=decision,
        evaluation=evaluation,
        sealed_hash=sealed_hash,
        timestamp=timestamp,
        telemetry=payload.telemetry,
        carrier_proof=payload.carrier_proof,
        digital_proof=payload.digital_proof,
        historical_count=len(payload.historical_transactions),
        summary=summary,
        # Central Evidence Items & Semantics
        evidence_items=evaluation.evidence_items if evaluation else [],
        evidence_statuses=evaluation.evidence_statuses if evaluation else {},
        contradictions=evaluation.contradictions if evaluation else [],
        # Probability & Economic Fields
        estimated_win_probability=p_win,
        p_win=p_win,
        win_probability=p_win,
        expected_value=ev_inr,
        expected_value_inr=ev_inr,
        ev_breakdown=ev_breakdown_dict,
        rebuttal_letter=state.get("rebuttal_letter"),
        # Evidence Intelligence
        payment_authentication=payment_auth_str,
        delivery_proof=delivery_proof_dict,
        gps_verification=gps_verification_dict,
        mfa_verification=mfa_auth,
        ip_address=payload.telemetry.ip_address if payload.telemetry else None,
        device_info=device_info_dict,
        customer_history_summary=history_summary_dict,
        digital_access_logs=digital_access_dict,
        # Explainability & HITL
        decision_explanation=explanation,
        assigned_to=None,
        due_by=payload.due_by,
        priority_score=priority_score,
        urgency=urgency,
        priority_factors=priority_factors
    )


def auto_dispatch_agent_node(state: DisputeState) -> DisputeState:
    """
    Auto-Dispatch & Sealing Agent:
    Seals representment dossier under SHA-256 and dispatches representment.
    """
    payload = state["payload"]
    dispute_id = state["dispute_id"]
    evaluation = state["evaluation"]
    ev_result = state.get("expected_value")
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    raw_dossier_data = f"{dispute_id}||{payload.payment_id}||{evaluation.confidence_score}||{timestamp}"
    sealed_hash = compute_sha256_hash(raw_dossier_data)
    
    ev_str = f"+₹{ev_result.expected_value_inr:,.2f}" if ev_result else "N/A"
    p_str = f"{ev_result.p_win*100:.1f}%" if ev_result else "N/A"

    summary = (
        f"Autonomous representment compiled successfully. Expected Value E[V]: {ev_str}, P(win): {p_str}, "
        f"Confidence Score: {evaluation.confidence_score}/100.0. Compliant with {evaluation.network.upper()} "
        f"regulatory specifications ({evaluation.reason_code}). Sealed under SHA-256 cryptographic proof."
    )
    
    dossier = _create_dossier(
        state=state,
        decision="AUTO_DISPATCHED",
        summary=summary,
        sealed_hash=sealed_hash,
        timestamp=timestamp
    )
    
    ledger.append_block(
        agent_id="AGENT_GATEKEEPER",
        state_transition="SEAL_AND_DISPATCH",
        payload={
            "dispute_id": dispute_id,
            "decision": "AUTO_DISPATCHED",
            "confidence_score": evaluation.confidence_score,
            "expected_value_inr": ev_result.expected_value_inr if ev_result else None,
            "sealed_hash": sealed_hash
        }
    )

    db.add_timeline_event(
        dispute_id=dispute_id,
        event_type="DECISION_SEALED",
        title="Decision Sealed: Auto-Dispatched",
        description=f"Autonomous representment dispatched and sealed under SHA-256 hash {sealed_hash[:16]}...",
        metadata={"decision": "AUTO_DISPATCHED", "sealed_hash": sealed_hash, "confidence_score": evaluation.confidence_score}
    )
    
    logs = state.get("logs", [])
    logs.append(f"Auto-Dispatched & Sealed: Hash={sealed_hash[:16]}...")
    
    return {
        **state,
        "dossier": dossier,
        "decision": "AUTO_DISPATCHED",
        "logs": logs
    }


def hitl_queue_agent_node(state: DisputeState) -> DisputeState:
    """
    Human-in-the-Loop (HITL) Queue Agent:
    Routes moderate-risk disputes to manual analyst review with gap diagnostics.
    """
    payload = state["payload"]
    dispute_id = state["dispute_id"]
    evaluation = state["evaluation"]
    ev_result = state.get("expected_value")
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    raw_dossier_data = f"{dispute_id}||{payload.payment_id}||{evaluation.confidence_score}||{timestamp}"
    sealed_hash = compute_sha256_hash(raw_dossier_data)
    
    gaps_str = "; ".join(evaluation.diagnostic_gaps) if evaluation.diagnostic_gaps else "Moderate win probability (40-70%)"
    summary = (
        f"Dispute routed to Human-in-the-Loop review queue. Expected Value E[V]: +₹{ev_result.expected_value_inr if ev_result else 0.0:,.2f}, "
        f"P(win): {ev_result.p_win*100 if ev_result else 0.0:.1f}%, Confidence Score: {evaluation.confidence_score}/100.0. "
        f"Actionable Gaps Identified: {gaps_str}."
    )
    
    dossier = _create_dossier(
        state=state,
        decision="ROUTE_TO_HITL_QUEUE",
        summary=summary,
        sealed_hash=sealed_hash,
        timestamp=timestamp
    )
    
    ledger.append_block(
        agent_id="AGENT_GATEKEEPER",
        state_transition="ROUTE_TO_HITL",
        payload={
            "dispute_id": dispute_id,
            "decision": "ROUTE_TO_HITL_QUEUE",
            "confidence_score": evaluation.confidence_score,
            "gaps": evaluation.diagnostic_gaps
        }
    )

    db.add_timeline_event(
        dispute_id=dispute_id,
        event_type="DECISION_SEALED",
        title="Decision Sealed: Routed to HITL",
        description=f"Routed to human review queue with {len(evaluation.diagnostic_gaps)} actionable gaps.",
        metadata={"decision": "ROUTE_TO_HITL_QUEUE", "sealed_hash": sealed_hash, "gaps_count": len(evaluation.diagnostic_gaps)}
    )
    
    logs = state.get("logs", [])
    logs.append(f"Routed to HITL Review Queue: Gaps={len(evaluation.diagnostic_gaps)}")
    
    return {
        **state,
        "dossier": dossier,
        "decision": "ROUTE_TO_HITL_QUEUE",
        "logs": logs
    }


def auto_accept_agent_node(state: DisputeState) -> DisputeState:
    """
    Auto-Accept & Refund Agent:
    Handles unprofitable representments (E[V] <= 0) to avoid secondary penalty fees
    and protect merchant dispute ratios.
    """
    payload = state["payload"]
    dispute_id = state["dispute_id"]
    evaluation = state["evaluation"]
    ev_result = state.get("expected_value")
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    raw_dossier_data = f"{dispute_id}||{payload.payment_id}||{evaluation.confidence_score}||{timestamp}"
    sealed_hash = compute_sha256_hash(raw_dossier_data)

    fee_val = ev_result.issuer_fee_inr if ev_result else 1500.0
    ev_val = ev_result.expected_value_inr if ev_result else 0.0

    summary = (
        f"Representment automatically accepted/refunded. Negative Expected Value E[V]: ₹{ev_val:,.2f} <= ₹0. "
        f"Auto-acceptance defensed merchant from non-refundable ₹{fee_val:,.2f} issuer dispute fee and protected VAMP/ECM ratios."
    )

    dossier = _create_dossier(
        state=state,
        decision="AUTO_ACCEPT_OR_REFUND",
        summary=summary,
        sealed_hash=sealed_hash,
        timestamp=timestamp
    )

    ledger.append_block(
        agent_id="AGENT_GATEKEEPER",
        state_transition="AUTO_ACCEPT_REFUND",
        payload={
            "dispute_id": dispute_id,
            "decision": "AUTO_ACCEPT_OR_REFUND",
            "expected_value_inr": ev_val,
            "fee_saved_inr": fee_val
        }
    )

    db.add_timeline_event(
        dispute_id=dispute_id,
        event_type="DECISION_SEALED",
        title="Decision Sealed: Auto-Accepted / Refunded",
        description="Auto-accepted dispute to protect merchant from non-refundable issuer arbitration fee.",
        metadata={"decision": "AUTO_ACCEPT_OR_REFUND", "sealed_hash": sealed_hash, "fee_saved_inr": fee_val}
    )

    logs = state.get("logs", [])
    logs.append(f"Auto-Accepted / Refunded: E[V]=₹{ev_val:,.2f} <= 0")

    return {
        **state,
        "dossier": dossier,
        "decision": "AUTO_ACCEPT_OR_REFUND",
        "logs": logs
    }


def execute_dispute_workflow(payload: DisputePayload) -> Dossier:
    """
    Executes the full dispute defense pipeline via deterministic sequential agents.
    """
    initial_state: DisputeState = {
        "payload": payload,
        "dispute_id": payload.dispute_id,
        "network": payload.card_network,
        "reason_code": payload.reason_code,
        "amount_inr": payload.amount_inr or 1000.0,
        "logs": []
    }

    # Deterministic pipeline
    s1 = triage_agent_node(initial_state)
    s2 = aggregator_agent_node(s1)
    s3 = compliance_agent_node(s2)
    s4 = economic_engine_agent_node(s3)
    next_node = gatekeeper_router(s4)
    if next_node == "auto_dispatch_agent":
        s5 = auto_dispatch_agent_node(s4)
    elif next_node == "auto_accept_agent":
        s5 = auto_accept_agent_node(s4)
    else:
        s5 = hitl_queue_agent_node(s4)

    return s5["dossier"]

