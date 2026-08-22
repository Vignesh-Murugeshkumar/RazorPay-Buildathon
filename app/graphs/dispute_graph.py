import datetime
from typing import TypedDict, Optional, Dict, Any, List
from app.models.dispute import (
    DisputePayload,
    RuleEvaluationResult,
    Dossier
)
from app.rules.card_rules import evaluate_dispute_compliance
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
    dossier: Optional[Dossier]
    decision: str
    logs: List[str]


def triage_agent_node(state: DisputeState) -> DisputeState:
    """
    Triage Agent:
    Extracts core dispute metadata, normalizes card network and reason code,
    and logs ingress transition in the cryptographic ledger.
    """
    payload = state["payload"]
    dispute_id = payload.dispute_id
    network = payload.card_network.lower()
    reason_code = payload.reason_code
    amount = payload.amount_inr
    
    # Append state transition to ledger
    ledger.append_block(
        agent_id="AGENT_TRIAGE",
        state_transition="DISPUTE_TRIAGED",
        payload={
            "dispute_id": dispute_id,
            "payment_id": payload.payment_id,
            "network": network,
            "reason_code": reason_code,
            "amount_inr": amount
        }
    )
    
    logs = state.get("logs", [])
    logs.append(f"Triaged dispute {dispute_id}: Network={network.upper()}, Reason={reason_code}, Amount=₹{amount:,.2f}")
    
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
    Aggregates session telemetry, 365-day historical transactions, and carrier proofs.
    """
    payload = state["payload"]
    dispute_id = state["dispute_id"]
    
    history_count = len(payload.historical_transactions)
    has_carrier = payload.carrier_proof is not None
    carrier_status = "VERIFIED" if (has_carrier and payload.carrier_proof.delivered_status) else "MISSING/UNVERIFIED"
    
    # Ledger audit
    ledger.append_block(
        agent_id="AGENT_AGGREGATOR",
        state_transition="EVIDENCE_AGGREGATED",
        payload={
            "dispute_id": dispute_id,
            "historical_orders_count": history_count,
            "carrier_proof_present": has_carrier,
            "carrier_status": carrier_status,
            "mfa_present": payload.telemetry.mfa_authenticated,
            "ip": payload.telemetry.ip_address,
            "device_id": payload.telemetry.device_id
        }
    )
    
    logs = state.get("logs", [])
    logs.append(f"Aggregated evidence: {history_count} historical orders, Carrier={carrier_status}, MFA={payload.telemetry.mfa_authenticated}")
    
    return {
        **state,
        "logs": logs
    }


def compliance_agent_node(state: DisputeState) -> DisputeState:
    """
    Compliance & Formation Engine Agent:
    Executes Visa CE 3.0 / Mastercard FPT deterministic evaluation and calculates Sc.
    """
    payload = state["payload"]
    dispute_id = state["dispute_id"]
    
    evaluation = evaluate_dispute_compliance(payload)
    
    ledger.append_block(
        agent_id="AGENT_COMPLIANCE",
        state_transition="COMPLIANCE_EVALUATED",
        payload={
            "dispute_id": dispute_id,
            "confidence_score": evaluation.confidence_score,
            "ce30_compliant": evaluation.ce30_compliant,
            "fpt_compliant": evaluation.fpt_compliant,
            "decision": evaluation.route_decision,
            "score_breakdown": evaluation.score_breakdown,
            "gaps": evaluation.diagnostic_gaps
        }
    )
    
    logs = state.get("logs", [])
    logs.append(f"Compliance evaluated: Confidence Score Sc={evaluation.confidence_score}/100.0 -> {evaluation.route_decision}")
    
    return {
        **state,
        "evaluation": evaluation,
        "decision": evaluation.route_decision,
        "logs": logs
    }


def gatekeeper_router(state: DisputeState) -> str:
    """
    Deterministic Gatekeeper Router:
    If Sc >= 85.0 -> AUTO_DISPATCH
    If Sc < 85.0 -> ROUTE_TO_HITL_QUEUE
    """
    evaluation = state.get("evaluation")
    if evaluation and evaluation.confidence_score >= 85.0:
        return "auto_dispatch_agent"
    return "hitl_queue_agent"


def auto_dispatch_agent_node(state: DisputeState) -> DisputeState:
    """
    Auto-Dispatch & Sealing Agent:
    Constructs sealed evidence dossier with cryptographic SHA-256 seal.
    """
    payload = state["payload"]
    dispute_id = state["dispute_id"]
    evaluation = state["evaluation"]
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    raw_dossier_data = f"{dispute_id}||{payload.payment_id}||{evaluation.confidence_score}||{timestamp}"
    sealed_hash = compute_sha256_hash(raw_dossier_data)
    
    summary = (
        f"Autonomous representment compiled successfully with Confidence Score {evaluation.confidence_score}/100.0. "
        f"Compliant with {evaluation.network.upper()} regulatory specifications ({evaluation.reason_code}). "
        f"Sealed under SHA-256 cryptographic proof."
    )
    
    dossier = Dossier(
        dispute_id=dispute_id,
        payment_id=payload.payment_id,
        amount_inr=payload.amount_inr,
        card_network=payload.card_network,
        reason_code=payload.reason_code,
        confidence_score=evaluation.confidence_score,
        decision="AUTO_DISPATCHED",
        evaluation=evaluation,
        sealed_hash=sealed_hash,
        timestamp=timestamp,
        telemetry=payload.telemetry,
        carrier_proof=payload.carrier_proof,
        historical_count=len(payload.historical_transactions),
        summary=summary
    )
    
    ledger.append_block(
        agent_id="AGENT_GATEKEEPER",
        state_transition="SEAL_AND_DISPATCH",
        payload={
            "dispute_id": dispute_id,
            "decision": "AUTO_DISPATCHED",
            "confidence_score": evaluation.confidence_score,
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
    Routes borderline or unqualified disputes to manual analyst review with gap diagnostics.
    """
    payload = state["payload"]
    dispute_id = state["dispute_id"]
    evaluation = state["evaluation"]
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    raw_dossier_data = f"{dispute_id}||{payload.payment_id}||{evaluation.confidence_score}||{timestamp}"
    sealed_hash = compute_sha256_hash(raw_dossier_data)
    
    gaps_str = "; ".join(evaluation.diagnostic_gaps) if evaluation.diagnostic_gaps else "Confidence threshold < 85.0"
    summary = (
        f"Dispute routed to Human-in-the-Loop review queue. Confidence Score: {evaluation.confidence_score}/100.0. "
        f"Actionable Gaps Identified: {gaps_str}."
    )
    
    dossier = Dossier(
        dispute_id=dispute_id,
        payment_id=payload.payment_id,
        amount_inr=payload.amount_inr,
        card_network=payload.card_network,
        reason_code=payload.reason_code,
        confidence_score=evaluation.confidence_score,
        decision="ROUTE_TO_HITL_QUEUE",
        evaluation=evaluation,
        sealed_hash=sealed_hash,
        timestamp=timestamp,
        telemetry=payload.telemetry,
        carrier_proof=payload.carrier_proof,
        historical_count=len(payload.historical_transactions),
        summary=summary
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


def build_dispute_graph():
    """
    Builds and compiles the LangGraph state machine workflow.
    """
    if not LANGGRAPH_AVAILABLE:
        return None
        
    workflow = StateGraph(DisputeState)
    
    workflow.add_node("triage_agent", triage_agent_node)
    workflow.add_node("aggregator_agent", aggregator_agent_node)
    workflow.add_node("compliance_agent", compliance_agent_node)
    workflow.add_node("auto_dispatch_agent", auto_dispatch_agent_node)
    workflow.add_node("hitl_queue_agent", hitl_queue_agent_node)
    
    workflow.set_entry_point("triage_agent")
    workflow.add_edge("triage_agent", "aggregator_agent")
    workflow.add_edge("aggregator_agent", "compliance_agent")
    
    workflow.add_conditional_edges(
        "compliance_agent",
        gatekeeper_router,
        {
            "auto_dispatch_agent": "auto_dispatch_agent",
            "hitl_queue_agent": "hitl_queue_agent"
        }
    )
    
    workflow.add_edge("auto_dispatch_agent", END)
    workflow.add_edge("hitl_queue_agent", END)
    
    return workflow.compile()


# Pre-compiled graph instance
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
        "amount_inr": payload.amount_inr,
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
    next_node = gatekeeper_router(s3)
    if next_node == "auto_dispatch_agent":
        s4 = auto_dispatch_agent_node(s3)
    else:
        s4 = hitl_queue_agent_node(s3)
        
    return s4["dossier"]
