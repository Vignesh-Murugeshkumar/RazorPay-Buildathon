from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException
from app.core.db import db
from app.schemas.dispute import Dossier, EvidenceStatus

router = APIRouter(prefix="/disputes", tags=["Evidence Provenance Graph"])


@router.get("/{dispute_id}/provenance")
async def get_dispute_provenance_graph(dispute_id: str):
    """
    Returns structured evidence provenance graph for a dispute:
    Source -> EvidenceItem [EV-xxx] -> Rule -> Score Contribution -> Decision -> Rebuttal Claim [CL-xxx]
    Derived directly from persisted evidence items in the dispute dossier.
    """
    dossier: Dossier = db.get_dossier(dispute_id)
    if not dossier:
        raise HTTPException(status_code=404, detail=f"Dispute {dispute_id} not found")

    p_win = (
        dossier.estimated_win_probability if dossier.estimated_win_probability is not None
        else (dossier.win_probability if dossier.win_probability is not None else (dossier.p_win or 0.0))
    )

    items = dossier.evidence_items or []
    nodes = []
    edges = []
    provenance_chains = []

    # Decision Node
    dec_node_id = f"DEC-{dossier.decision}"
    nodes.append({
        "id": dec_node_id,
        "label": f"Decision: {dossier.decision}",
        "type": "DECISION",
        "data": {
            "decision": dossier.decision,
            "estimated_win_probability": p_win,
            "confidence_score": dossier.confidence_score,
            "has_contradictions": len(dossier.contradictions) > 0
        }
    })

    # Claims map
    claims_list = []
    if dossier.rebuttal_letter and isinstance(dossier.rebuttal_letter, dict):
        claims_list = dossier.rebuttal_letter.get("claims", [])
    
    claim_nodes_added = set()
    for cl in claims_list:
        cid = cl.get("claim_id", "CL-UNKNOWN")
        if cid not in claim_nodes_added:
            claim_nodes_added.add(cid)
            nodes.append({
                "id": cid,
                "label": f"Claim {cid}",
                "type": "CLAIM",
                "data": {
                    "text": cl.get("claim_text", ""),
                    "supported_by": cl.get("supported_by", []),
                    "status": cl.get("evidence_status", "VERIFIED")
                }
            })

    # Build provenance chains from persisted evidence items
    source_nodes_added = set()
    rule_nodes_added = set()

    for item in items:
        # Source Node
        src_id = f"SRC-{item.evidence_type}"
        if src_id not in source_nodes_added:
            source_nodes_added.add(src_id)
            nodes.append({
                "id": src_id,
                "label": item.source,
                "type": "SOURCE",
                "data": {"source_name": item.source}
            })

        # Evidence Item Node
        ev_status_str = item.status.value if hasattr(item.status, "value") else str(item.status)
        nodes.append({
            "id": item.evidence_id,
            "label": f"{item.evidence_id}: {item.evidence_type}",
            "type": "EVIDENCE",
            "status": ev_status_str,
            "data": {
                "value": item.value,
                "status": ev_status_str,
                "score_contribution": item.score_contribution
            }
        })

        # Edge Source -> Evidence
        edges.append({
            "from": src_id,
            "to": item.evidence_id,
            "relationship": "EXTRACTS"
        })

        # Rule Nodes & Edges Evidence -> Rule
        for r_id in item.rule_ids:
            rule_node_id = f"RULE-{r_id}"
            if rule_node_id not in rule_nodes_added:
                rule_nodes_added.add(rule_node_id)
                nodes.append({
                    "id": rule_node_id,
                    "label": f"Rule: {r_id}",
                    "type": "RULE",
                    "data": {"rule_id": r_id}
                })

            edges.append({
                "from": item.evidence_id,
                "to": rule_node_id,
                "relationship": "EVALUATES",
                "score_contribution": item.score_contribution
            })

            edges.append({
                "from": rule_node_id,
                "to": dec_node_id,
                "relationship": "DETERMINES"
            })

        # Edges Decision -> Claims supported
        for cl_id in item.supports_claim_ids:
            edges.append({
                "from": item.evidence_id,
                "to": cl_id,
                "relationship": "SUPPORTS"
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

    return {
        "dispute_id": dossier.dispute_id,
        "decision": dossier.decision,
        "estimated_win_probability": p_win,
        "confidence_score": dossier.confidence_score,
        "contradictions": [c.model_dump() for c in dossier.contradictions],
        "evidence_items": [i.model_dump() for i in items],
        "nodes": nodes,
        "edges": edges,
        "provenance_chains": provenance_chains
    }
