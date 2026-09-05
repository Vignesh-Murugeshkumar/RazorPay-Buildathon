"""
SentinelDispute - 6-Tier Evidence Provenance Graph & Audit Trail.

Constructs an end-to-end provenance DAG:
Evidence -> Claim -> Challenge -> Verification -> Policy -> Decision

Provides tamper-evident event hash chains and structured audit justifications
answering exactly:
- Why was this decision made?
- Which evidence supported it?
- Which evidence contradicted it?
- Which claims were rejected or overturned?
- Which policies were evaluated?
- What did the challenger find?
- What did the verifier confirm?
- What information was missing?
"""

from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException
from app.core.db import db
from app.services.ledger import ledger
from app.schemas.dispute import Dossier, EvidenceStatus, ClaimVerificationResult

router = APIRouter(prefix="/disputes", tags=["Evidence Provenance Graph"])


def build_provenance_payload(dispute_id: str) -> Dict[str, Any]:
    """
    Constructs the complete 6-tier provenance DAG and tamper-evident audit trail for a dispute.
    """
    dossier: Optional[Dossier] = db.get_dossier(dispute_id)
    if not dossier:
        from app.api.v1.endpoints.webhooks import get_dossiers_db
        dossier = get_dossiers_db().get(dispute_id)
    if not dossier:
        raise HTTPException(status_code=404, detail=f"Dispute {dispute_id} not found")

    p_win = (
        dossier.estimated_win_probability if dossier.estimated_win_probability is not None
        else (dossier.win_probability if dossier.win_probability is not None else (dossier.p_win or 0.0))
    )

    items = dossier.evidence_items or []
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    # -------------------------------------------------------------------------
    # Tier 1: SOURCE & EVIDENCE NODES
    # -------------------------------------------------------------------------
    item_by_id = {}
    source_nodes_added = set()
    provenance_chains = []

    for item in items:
        item_by_id[item.evidence_id] = item
        ev_status_str = item.status.value if hasattr(item.status, "value") else str(item.status)

        # Source Node
        src_id = f"SRC-{item.evidence_type}"
        if src_id not in source_nodes_added:
            source_nodes_added.add(src_id)
            nodes.append({
                "id": src_id,
                "label": item.source,
                "tier": 0,
                "type": "SOURCE",
                "data": {"source_name": item.source}
            })

        nodes.append({
            "id": item.evidence_id,
            "label": f"{item.evidence_id}: {item.evidence_type}",
            "tier": 1,
            "type": "EVIDENCE",
            "status": ev_status_str,
            "data": {
                "evidence_id": item.evidence_id,
                "evidence_type": item.evidence_type,
                "source": item.source,
                "source_type": getattr(item, "source_type", "system"),
                "value": item.value,
                "content": getattr(item, "content", ""),
                "reliability": getattr(item, "reliability", 1.0),
                "hash": getattr(item, "hash", ""),
                "score_contribution": item.score_contribution
            }
        })

        # Edge: Source -> Evidence
        edges.append({
            "from": src_id,
            "to": item.evidence_id,
            "relationship": "EXTRACTS"
        })

        provenance_chains.append({
            "evidence_id": item.evidence_id,
            "evidence_type": item.evidence_type,
            "status": ev_status_str,
            "value": item.value,
            "source": item.source,
            "rules": item.rule_ids,
            "score_contribution": item.score_contribution,
            "decision": dossier.decision,
            "claims_supported": item.supports_claim_ids
        })

    # -------------------------------------------------------------------------
    # Tier 2: CLAIM NODES
    # -------------------------------------------------------------------------
    claims_list = dossier.investigation_claims or []
    # Fallback to AI report claims if empty
    if not claims_list and dossier.ai_investigation:
        raw_claims = dossier.ai_investigation.get("claims", [])
        for rc in raw_claims:
            claims_list.append(rc)

    claim_by_id = {}
    for cl in claims_list:
        cid = getattr(cl, "claim_id", None) or (cl.get("claim_id") if isinstance(cl, dict) else "CLM-001")
        ctext = getattr(cl, "claim", None) or (cl.get("claim") or cl.get("claim_text", "") if isinstance(cl, dict) else "")
        cev_ids = getattr(cl, "evidence_ids", None) or (cl.get("evidence_ids", []) if isinstance(cl, dict) else [])
        cconf = getattr(cl, "confidence", 1.0) if not isinstance(cl, dict) else cl.get("confidence", 1.0)
        ctype = getattr(cl, "claim_type", "factual") if not isinstance(cl, dict) else cl.get("claim_type", "factual")

        claim_by_id[cid] = cl
        nodes.append({
            "id": cid,
            "label": f"Claim {cid}",
            "tier": 2,
            "type": "CLAIM",
            "data": {
                "claim_id": cid,
                "claim": ctext,
                "evidence_ids": cev_ids,
                "confidence": cconf,
                "claim_type": ctype
            }
        })

        # Edge: Evidence -> Claim
        for ev_id in cev_ids:
            if ev_id in item_by_id:
                edges.append({
                    "from": ev_id,
                    "to": cid,
                    "relationship": "SUPPORTS"
                })

    # -------------------------------------------------------------------------
    # Tier 3: CHALLENGE NODES
    # -------------------------------------------------------------------------
    challenges = dossier.claim_challenges or []
    for chal in challenges:
        chal_id = f"CHAL-{chal.claim_id}"
        nodes.append({
            "id": chal_id,
            "label": f"Challenge: {chal.challenge_result.upper()}",
            "tier": 3,
            "type": "CHALLENGE",
            "data": {
                "claim_id": chal.claim_id,
                "challenge": chal.challenge,
                "contrary_evidence_ids": chal.contrary_evidence_ids,
                "alternative_explanation": chal.alternative_explanation,
                "missing_evidence": chal.missing_evidence,
                "challenge_strength": chal.challenge_strength,
                "challenge_result": chal.challenge_result
            }
        })

        # Edge: Claim -> Challenge
        if chal.claim_id in claim_by_id:
            edges.append({
                "from": chal.claim_id,
                "to": chal_id,
                "relationship": "CHALLENGES"
            })

        # Edge: Contrary Evidence -> Challenge
        for ce_id in chal.contrary_evidence_ids:
            if ce_id in item_by_id:
                edges.append({
                    "from": ce_id,
                    "to": chal_id,
                    "relationship": "CONTRADICTS"
                })

    # -------------------------------------------------------------------------
    # Tier 4: VERIFICATION NODES
    # -------------------------------------------------------------------------
    verifs = dossier.claim_verifications or []
    for vf in verifs:
        verif_id = f"VERIF-{vf.claim_id}"
        nodes.append({
            "id": verif_id,
            "label": f"Verification: {vf.verification_status.upper()}",
            "tier": 4,
            "type": "VERIFICATION",
            "data": {
                "claim_id": vf.claim_id,
                "status": vf.verification_status,
                "supporting_evidence": vf.supporting_evidence,
                "contradicting_evidence": vf.contradicting_evidence,
                "unsupported_reason": vf.unsupported_reason,
                "verified_confidence": vf.verified_confidence
            }
        })

        # Edge: Challenge -> Verification
        chal_id = f"CHAL-{vf.claim_id}"
        edges.append({
            "from": chal_id,
            "to": verif_id,
            "relationship": "EVALUATES"
        })

    # -------------------------------------------------------------------------
    # Tier 5: POLICY ENGINE NODE
    # -------------------------------------------------------------------------
    inv_dec = dossier.investigation_decision
    policy_ids = inv_dec.policy_ids if inv_dec else [f"POL-{dossier.card_network.upper()}-CE30"]
    pol_node_id = "POL-ENGINE"
    nodes.append({
        "id": pol_node_id,
        "label": f"Policy: {', '.join(policy_ids)}",
        "tier": 5,
        "type": "POLICY",
        "data": {
            "policy_ids": policy_ids,
            "ce30_compliant": dossier.evaluation.ce30_compliant if dossier.evaluation else False,
            "fpt_compliant": dossier.evaluation.fpt_compliant if dossier.evaluation else False,
            "primary_rule": getattr(dossier.evaluation, "evidence_category", "FRAUD_CE30_FPT")
        }
    })

    # Edge: Verifications -> Policy Engine
    for vf in verifs:
        verif_id = f"VERIF-{vf.claim_id}"
        edges.append({
            "from": verif_id,
            "to": pol_node_id,
            "relationship": "FEEDS_POLICY"
        })

    # -------------------------------------------------------------------------
    # Tier 6: DECISION NODE
    # -------------------------------------------------------------------------
    dec_node_id = f"DEC-{dossier.decision}"
    risk_level = inv_dec.risk_level if inv_dec else ("CONFIRMED_RISK" if dossier.contradictions else "LIKELY_LEGITIMATE")
    nodes.append({
        "id": dec_node_id,
        "label": f"Decision: {dossier.decision} ({risk_level})",
        "tier": 6,
        "type": "DECISION",
        "data": {
            "decision": dossier.decision,
            "risk_level": risk_level,
            "estimated_win_probability": p_win,
            "confidence_score": dossier.confidence_score,
            "sealed_hash": dossier.sealed_hash,
            "insufficient_evidence": inv_dec.insufficient_evidence if inv_dec else False
        }
    })

    # Edge: Policy -> Decision
    edges.append({
        "from": pol_node_id,
        "to": dec_node_id,
        "relationship": "DETERMINES"
    })

    # -------------------------------------------------------------------------
    # Tamper-Evident Audit Event Hash Chain
    # -------------------------------------------------------------------------
    audit_chain: List[Dict[str, Any]] = []
    case_blocks = ledger.get_blocks_by_dispute(dispute_id)
    for block in case_blocks:
        payload_hash = getattr(block, "payload_hash", None)
        if not payload_hash:
            from app.core.security import compute_sha256_hash
            import json
            payload_hash = compute_sha256_hash(json.dumps(block.payload, sort_keys=True, default=str))

        audit_chain.append({
            "event_id": f"EVT-{block.index:04d}",
            "case_id": dispute_id,
            "timestamp": block.timestamp,
            "event_type": block.state_transition,
            "agent_id": block.agent_id,
            "payload_hash": payload_hash,
            "previous_event_hash": block.previous_hash,
            "block_hash": block.block_hash
        })

    # -------------------------------------------------------------------------
    # 8-Question Decision Provenance Summary
    # -------------------------------------------------------------------------
    rejected_claims = [
        vf.claim_id for vf in verifs
        if vf.verification_status in ("unsupported", "contradicted")
    ]
    challenger_overturns = [
        c.claim_id for c in challenges
        if c.challenge_result == "overturned"
    ]
    confirmed_claims = [
        vf.claim_id for vf in verifs
        if vf.verification_status in ("supported", "partially_supported")
    ]

    missing_info = []
    if dossier.decision_explanation and dossier.decision_explanation.top_negative_factors:
        missing_info.extend(dossier.decision_explanation.top_negative_factors)

    provenance_summary = {
        "why_decision_made": (
            f"Decision '{dossier.decision}' reached with risk level '{risk_level}'. "
            f"{dossier.summary}"
        ),
        "supporting_evidence": [
            item.evidence_id for item in items
            if item.status in (EvidenceStatus.VERIFIED, EvidenceStatus.PARTIALLY_VERIFIED)
        ],
        "contradicting_evidence": [
            item.evidence_id for item in items
            if item.status == EvidenceStatus.CONTRADICTED
        ],
        "rejected_claims": rejected_claims,
        "applied_policies": policy_ids,
        "challenger_findings": {
            "total_challenges": len(challenges),
            "overturned_claims": challenger_overturns,
            "details": [
                {
                    "claim_id": c.claim_id,
                    "result": c.challenge_result,
                    "contrary_evidence": c.contrary_evidence_ids,
                    "alternative_narrative": c.alternative_explanation
                }
                for c in challenges
            ]
        },
        "verifier_confirmations": {
            "grounded_ratio": getattr(dossier.ai_verification, "get", lambda k, d=None: d)("grounded_claims_ratio", 1.0) if isinstance(dossier.ai_verification, dict) else 1.0,
            "verified_claims": confirmed_claims
        },
        "missing_information": missing_info or ["None"]
    }

    return {
        "case_id": dispute_id,
        "dispute_id": dispute_id,
        "decision": dossier.decision,
        "risk_level": risk_level,
        "estimated_win_probability": p_win,
        "confidence_score": dossier.confidence_score,
        "sealed_hash": dossier.sealed_hash,
        "nodes": nodes,
        "edges": edges,
        "provenance_chains": provenance_chains,
        "provenance_summary": provenance_summary,
        "decision_explainer": dossier.decision_explainer.model_dump() if dossier.decision_explainer else None,
        "audit_event_hash_chain": audit_chain,
        "chain_tamper_evident": ledger.verify_integrity().is_valid
    }


@router.get("/{dispute_id}/provenance")
async def get_dispute_provenance_graph(dispute_id: str):
    """
    Returns structured 6-tier evidence provenance graph for a dispute:
    Evidence -> Claim -> Challenge -> Verification -> Policy -> Decision
    Includes SHA-256 tamper-evident audit event hash chain.
    """
    return build_provenance_payload(dispute_id)
