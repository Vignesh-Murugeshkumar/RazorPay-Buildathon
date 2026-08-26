import datetime
from typing import TypedDict, Optional, Dict, Any, List
from app.models.dispute import (
    DisputePayload,
    RuleEvaluationResult,
    Dossier
)
from app.rules.card_rules import evaluate_dispute_compliance
from app.rules.service_disputes import evaluate_service_dispute_compliance
from app.services.expected_value import calculate_expected_value, ExpectedValueResult
from app.services.rag_rebuttal import rag_synthesizer
from app.services.issuer_intelligence import issuer_intelligence
from app.ledger.audit_chain import ledger
from app.security import compute_sha256_hash

try:
    from langgraph.graph import StateGraph, END
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    StateGraph = None
    END = None


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
    category = "SERVICE_DISPUTE_RAG" if is_non_fraud else "FRAUD_CE30_FPT"

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
    """
    payload = state["payload"]
    dispute_id = state["dispute_id"]
    reason_code = str(payload.reason_code).strip()
    
    if reason_code in ("13.1", "13.7", "4853", "4855"):
        # Non-Fraud Merchandise / Cancellation RAG flow
        compliant, score, gaps, breakdown = evaluate_service_dispute_compliance(payload)
        category = "SERVICE_DISPUTE_RAG" if reason_code in ("13.1", "4855") else "CANCELLATION_RAG"
        
        evaluation = RuleEvaluationResult(
            network=payload.card_network,
            reason_code=reason_code,
            ce30_compliant=False,
            fpt_compliant=False,
            qualifying_orders_count=len(payload.historical_transactions),
            carrier_verified=payload.carrier_proof is not None and payload.carrier_proof.delivered_status,
            digital_verified=payload.digital_proof is not None and payload.digital_proof.access_logs_verified,
            gps_verified=payload.carrier_proof is not None and payload.carrier_proof.verified_gps,
            mfa_verified=payload.telemetry.mfa_authenticated if payload.telemetry else False,
            confidence_score=score,
            route_decision="AUTO_DISPATCH" if score >= 70.0 else "ROUTE_TO_HITL_QUEUE",
            diagnostic_gaps=gaps,
            score_breakdown=breakdown,
            evidence_category=category
        )
    else:
        # Standard Visa CE 3.0 / Mastercard FPT rule evaluation
        evaluation = evaluate_dispute_compliance(payload)
        evaluation.evidence_category = "FRAUD_CE30_FPT"

    ledger.append_block(
        agent_id="AGENT_COMPLIANCE",
        state_transition="COMPLIANCE_EVALUATED",
        payload={
            "dispute_id": dispute_id,
            "confidence_score": evaluation.confidence_score,
            "ce30_compliant": evaluation.ce30_compliant,
            "fpt_compliant": evaluation.fpt_compliant,
            "category": evaluation.evidence_category,
            "gaps": evaluation.diagnostic_gaps
        }
    )
    
    logs = state.get("logs", [])
    logs.append(f"Compliance evaluated: Score Sc={evaluation.confidence_score}/100.0 ({evaluation.evidence_category})")
    
    return {
        **state,
        "evaluation": evaluation,
        "logs": logs
    }


def economic_engine_agent_node(state: DisputeState) -> DisputeState:
    """
    Dynamic Expected Value (E[V]) & Rebuttal Synthesis Agent:
    Computes Net Recovery E[V] = P(win|x)*A - (1-P(win|x))*F_fee - C_op,
    synthesizes constrained rebuttal letter, and sets economic decision.
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

    # Synthesize constrained RAG rebuttal letter
    rebuttal = rag_synthesizer.synthesize_rebuttal(
        payload=payload,
        confidence_score=evaluation.confidence_score,
        p_win=ev_result.p_win
    )

    # Update evaluation with economic data
    evaluation.p_win = ev_result.p_win
    evaluation.expected_value_inr = ev_result.expected_value_inr
    evaluation.issuer_fee_inr = ev_result.issuer_fee_inr
    evaluation.operational_cost_inr = ev_result.operational_cost_inr
    evaluation.economic_decision = ev_result.decision
    evaluation.route_decision = ev_result.decision
    evaluation.rebuttal_letter = rebuttal.model_dump()

    ledger.append_block(
        agent_id="AGENT_ECONOMIC_ENGINE",
        state_transition="EXPECTED_VALUE_COMPUTED",
        payload={
            "dispute_id": payload.dispute_id,
            "expected_value_inr": ev_result.expected_value_inr,
            "p_win": ev_result.p_win,
            "economic_decision": ev_result.decision,
            "is_profitable": ev_result.is_profitable
        }
    )

    logs = state.get("logs", [])
    logs.append(
        f"Economic E[V] Computed: E[V]=₹{ev_result.expected_value_inr:,.2f}, P(win)={ev_result.p_win*100:.1f}% -> Decision={ev_result.decision}"
    )

    return {
        **state,
        "evaluation": evaluation,
        "expected_value": ev_result,
        "rebuttal_letter": rebuttal.model_dump(),
        "decision": ev_result.decision,
        "logs": logs
    }


def gatekeeper_router(state: DisputeState) -> str:
    """
    3-Tier Gatekeeper Router based on Dynamic Expected Value & P(win):
    - E[V] > 0 & P(win) >= 0.70  --> auto_dispatch_agent
    - E[V] > 0 & 0.40 <= P < 0.70 --> hitl_queue_agent
    - E[V] <= 0                   --> auto_accept_agent
    """
    decision = state.get("decision")
    if decision == "AUTO_SUBMIT_REPRESENTMENT" or decision == "AUTO_DISPATCH":
        return "auto_dispatch_agent"
    elif decision == "AUTO_ACCEPT_OR_REFUND":
        return "auto_accept_agent"
    return "hitl_queue_agent"


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
    
    dossier = Dossier(
        dispute_id=dispute_id,
        payment_id=payload.payment_id,
        amount_inr=payload.amount_inr or 1000.0,
        card_network=payload.card_network,
        reason_code=payload.reason_code,
        confidence_score=evaluation.confidence_score,
        decision="AUTO_DISPATCHED",
        evaluation=evaluation,
        sealed_hash=sealed_hash,
        timestamp=timestamp,
        telemetry=payload.telemetry,
        carrier_proof=payload.carrier_proof,
        digital_proof=payload.digital_proof,
        historical_count=len(payload.historical_transactions),
        summary=summary,
        expected_value_inr=ev_result.expected_value_inr if ev_result else None,
        p_win=ev_result.p_win if ev_result else None,
        rebuttal_letter=state.get("rebuttal_letter")
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
    
    dossier = Dossier(
        dispute_id=dispute_id,
        payment_id=payload.payment_id,
        amount_inr=payload.amount_inr or 1000.0,
        card_network=payload.card_network,
        reason_code=payload.reason_code,
        confidence_score=evaluation.confidence_score,
        decision="ROUTE_TO_HITL_QUEUE",
        evaluation=evaluation,
        sealed_hash=sealed_hash,
        timestamp=timestamp,
        telemetry=payload.telemetry,
        carrier_proof=payload.carrier_proof,
        digital_proof=payload.digital_proof,
        historical_count=len(payload.historical_transactions),
        summary=summary,
        expected_value_inr=ev_result.expected_value_inr if ev_result else None,
        p_win=ev_result.p_win if ev_result else None,
        rebuttal_letter=state.get("rebuttal_letter")
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

    dossier = Dossier(
        dispute_id=dispute_id,
        payment_id=payload.payment_id,
        amount_inr=payload.amount_inr or 1000.0,
        card_network=payload.card_network,
        reason_code=payload.reason_code,
        confidence_score=evaluation.confidence_score,
        decision="AUTO_ACCEPT_OR_REFUND",
        evaluation=evaluation,
        sealed_hash=sealed_hash,
        timestamp=timestamp,
        telemetry=payload.telemetry,
        carrier_proof=payload.carrier_proof,
        digital_proof=payload.digital_proof,
        historical_count=len(payload.historical_transactions),
        summary=summary,
        expected_value_inr=ev_val,
        p_win=ev_result.p_win if ev_result else None,
        rebuttal_letter=state.get("rebuttal_letter")
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

    logs = state.get("logs", [])
    logs.append(f"Auto-Accepted / Refunded: E[V]=₹{ev_val:,.2f} <= 0")

    return {
        **state,
        "dossier": dossier,
        "decision": "AUTO_ACCEPT_OR_REFUND",
        "logs": logs
    }


def build_dispute_graph():
    """
    Builds and compiles the LangGraph state machine workflow with E[V] decisioning.
    """
    if not LANGGRAPH_AVAILABLE:
        return None
        
    workflow = StateGraph(DisputeState)
    
    workflow.add_node("triage_agent", triage_agent_node)
    workflow.add_node("aggregator_agent", aggregator_agent_node)
    workflow.add_node("compliance_agent", compliance_agent_node)
    workflow.add_node("economic_engine_agent", economic_engine_agent_node)
    workflow.add_node("auto_dispatch_agent", auto_dispatch_agent_node)
    workflow.add_node("hitl_queue_agent", hitl_queue_agent_node)
    workflow.add_node("auto_accept_agent", auto_accept_agent_node)
    
    workflow.set_entry_point("triage_agent")
    workflow.add_edge("triage_agent", "aggregator_agent")
    workflow.add_edge("aggregator_agent", "compliance_agent")
    workflow.add_edge("compliance_agent", "economic_engine_agent")
    
    workflow.add_conditional_edges(
        "economic_engine_agent",
        gatekeeper_router,
        {
            "auto_dispatch_agent": "auto_dispatch_agent",
            "hitl_queue_agent": "hitl_queue_agent",
            "auto_accept_agent": "auto_accept_agent"
        }
    )
    
    workflow.add_edge("auto_dispatch_agent", END)
    workflow.add_edge("hitl_queue_agent", END)
    workflow.add_edge("auto_accept_agent", END)
    
    return workflow.compile()


compiled_dispute_graph = build_dispute_graph()


def execute_dispute_workflow(payload: DisputePayload) -> Dossier:
    """
    Executes the full dispute defense pipeline. Uses LangGraph if compiled,
    otherwise deterministic sequential fallback.
    """
    initial_state: DisputeState = {
        "payload": payload,
        "dispute_id": payload.dispute_id,
        "network": payload.card_network,
        "reason_code": payload.reason_code,
        "amount_inr": payload.amount_inr or 1000.0,
        "logs": []
    }
    
    if compiled_dispute_graph is not None:
        try:
            final_state = compiled_dispute_graph.invoke(initial_state)
            return final_state["dossier"]
        except Exception:
            pass  # fallback to deterministic steps

    # Deterministic fallback pipeline
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
