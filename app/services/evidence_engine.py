"""
SentinelDispute - Central Evidence Engine & Contradiction Detection Service.

Extracts canonical EvidenceItem objects from incoming dispute payloads, assigns
stable IDs (EV-001 through EV-007), identifies deterministic factual contradictions,
and computes evidence confidence contributions with full audit provenance.
"""

import json
import datetime
from typing import List, Dict, Tuple, Optional, Any
from app.schemas.dispute import (
    DisputePayload,
    EvidenceItem,
    EvidenceStatus,
    EvidenceContradiction
)
from app.core.security import compute_sha256_hash
from app.core.logger import get_logger

logger = get_logger("evidence_engine")


def detect_contradictions(payload: DisputePayload) -> List[EvidenceContradiction]:
    """
    Executes deterministic contradiction detection on objective evidence fields.
    Identifies conflicting facts without probabilistic or LLM ambiguity.

    Checks:
    1. Carrier delivery assert delivered_status=True while tracking_number is missing or empty.
    2. Recipient signature recorded while delivery status is unconfirmed/false.
    3. GPS coordinates outside 50m delivery perimeter on delivered shipment (>50m distance/unverified).
    4. Digital access logs claimed as consumed while customer account is inactive or closed.
    """
    contradictions: List[EvidenceContradiction] = []
    has_carrier = payload.carrier_proof is not None
    has_digital = payload.digital_proof is not None

    # 1. Carrier delivery claim with missing tracking number
    if has_carrier and payload.carrier_proof.delivered_status:
        trk = payload.carrier_proof.tracking_number
        if not trk or not str(trk).strip():
            contradictions.append(EvidenceContradiction(
                conflict_id="CONF-001",
                evidence_ids=["EV-004"],
                fields=["delivered_status", "tracking_number"],
                description="Carrier proof asserts delivered_status=True but tracking_number is missing or empty.",
                severity="HIGH"
            ))

    # 2. Recipient signature recorded on undelivered shipment
    if has_carrier and (not payload.carrier_proof.delivered_status) and payload.carrier_proof.recipient_signature_present:
        contradictions.append(EvidenceContradiction(
            conflict_id="CONF-002",
            evidence_ids=["EV-004"],
            fields=["delivered_status", "recipient_signature_present"],
            description="Recipient signature recorded on delivery slip while carrier delivery status is false/unconfirmed.",
            severity="HIGH"
        ))

    # 3. GPS coordinates outside 50m perimeter on delivered shipment (>50m distance)
    if has_carrier and payload.carrier_proof.gps_latitude is not None and payload.carrier_proof.delivered_status and not payload.carrier_proof.verified_gps:
        contradictions.append(EvidenceContradiction(
            conflict_id="CONF-003",
            evidence_ids=["EV-005"],
            fields=["gps_latitude", "verified_gps"],
            description="Carrier GPS coordinates recorded at delivery lie outside the 50m cardholder address perimeter despite delivery confirmation.",
            severity="HIGH"
        ))

    # 4. Digital service consumed while cardholder account inactive
    if has_digital and payload.digital_proof.access_logs_verified and (not payload.digital_proof.user_account_active):
        contradictions.append(EvidenceContradiction(
            conflict_id="CONF-004",
            evidence_ids=["EV-007"],
            fields=["access_logs_verified", "user_account_active"],
            description="Digital access logs verified as consumed while cardholder account is inactive/closed.",
            severity="HIGH"
        ))

    return contradictions


def _reliability_for_status(status: EvidenceStatus) -> float:
    if status == EvidenceStatus.VERIFIED:
        return 1.0
    elif status == EvidenceStatus.PARTIALLY_VERIFIED:
        return 0.65
    elif status == EvidenceStatus.UNVERIFIED:
        return 0.30
    return 0.0


def _compute_item_hash(case_id: str, ev_id: str, ev_type: str, status: str, value: Any, source: str) -> str:
    raw = f"{case_id}:{ev_id}:{ev_type}:{status}:{json.dumps(value, sort_keys=True, default=str)}:{source}"
    return compute_sha256_hash(raw)


def extract_evidence_items(
    payload: DisputePayload,
    contradictions: Optional[List[EvidenceContradiction]] = None
) -> Tuple[List[EvidenceItem], Dict[str, EvidenceStatus]]:
    """
    Extracts canonical EvidenceItems (EV-001 through EV-007) with explicit status,
    stable identity, cryptographic hash, reliability, and score contributions.
    Never fabricates missing evidence.
    """
    if contradictions is None:
        contradictions = detect_contradictions(payload)

    conflicted_ev_ids = set()
    for conf in contradictions:
        conflicted_ev_ids.update(conf.evidence_ids)

    case_id = payload.dispute_id or "disp_unknown"
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    items: List[EvidenceItem] = []
    has_telemetry = payload.telemetry is not None
    has_carrier = payload.carrier_proof is not None
    has_digital = payload.digital_proof is not None

    # EV-001: Customer IP
    ip_val = payload.telemetry.ip_address if has_telemetry else None
    if ip_val:
        ev01_status = EvidenceStatus.VERIFIED
        ev01_contrib = 5.0
        ev01_content = f"Customer checkout IP address: {ip_val}"
    else:
        ev01_status = EvidenceStatus.MISSING
        ev01_contrib = 0.0
        ev01_content = "Customer IP address missing from telemetry."
    
    items.append(EvidenceItem(
        evidence_id="EV-001",
        evidence_type="CUSTOMER_IP",
        status=ev01_status,
        value=ip_val,
        source="checkout_telemetry",
        rule_ids=["RULE-IP-TELEMETRY"],
        score_contribution=ev01_contrib,
        case_id=case_id,
        source_type="telemetry",
        source_id=f"{case_id}_EV-001",
        content=ev01_content,
        timestamp=now_iso,
        metadata={"ip_address": ip_val} if ip_val else {},
        reliability=_reliability_for_status(ev01_status),
        retrieval_score=1.0,
        hash=_compute_item_hash(case_id, "EV-001", "CUSTOMER_IP", ev01_status.value, ip_val, "checkout_telemetry"),
        created_at=now_iso
    ))

    # EV-002: Device Fingerprint
    dev_val = payload.telemetry.device_id if has_telemetry else None
    if dev_val:
        ev02_status = EvidenceStatus.VERIFIED
        ev02_contrib = 5.0
        ev02_content = f"Customer device fingerprint identifier: {dev_val}"
    else:
        ev02_status = EvidenceStatus.MISSING
        ev02_contrib = 0.0
        ev02_content = "Device fingerprint missing from checkout telemetry."
        
    items.append(EvidenceItem(
        evidence_id="EV-002",
        evidence_type="DEVICE_FINGERPRINT",
        status=ev02_status,
        value=dev_val,
        source="checkout_telemetry",
        rule_ids=["RULE-DEVICE-FP"],
        score_contribution=ev02_contrib,
        case_id=case_id,
        source_type="telemetry",
        source_id=f"{case_id}_EV-002",
        content=ev02_content,
        timestamp=now_iso,
        metadata={"device_id": dev_val} if dev_val else {},
        reliability=_reliability_for_status(ev02_status),
        retrieval_score=1.0,
        hash=_compute_item_hash(case_id, "EV-002", "DEVICE_FINGERPRINT", ev02_status.value, dev_val, "checkout_telemetry"),
        created_at=now_iso
    ))

    # EV-003: Payment Authentication / 3DS MFA
    mfa_val = payload.telemetry.mfa_authenticated if has_telemetry else None
    if not has_telemetry:
        ev03_status = EvidenceStatus.MISSING
        ev03_contrib = 0.0
        ev03_content = "Payment 3DS authentication status missing (no telemetry)."
    elif payload.telemetry.mfa_authenticated:
        ev03_status = EvidenceStatus.VERIFIED
        ev03_contrib = 20.0
        ev03_content = "3DS / 2FA strong customer authentication verified at payment gateway."
    else:
        ev03_status = EvidenceStatus.UNVERIFIED
        ev03_contrib = 0.0
        ev03_content = "Transaction processed without verified 3DS / MFA authentication."
        
    items.append(EvidenceItem(
        evidence_id="EV-003",
        evidence_type="PAYMENT_AUTHENTICATION",
        status=ev03_status,
        value=mfa_val,
        source="checkout_telemetry",
        rule_ids=["RULE-3DS-MFA"],
        score_contribution=ev03_contrib,
        case_id=case_id,
        source_type="telemetry",
        source_id=f"{case_id}_EV-003",
        content=ev03_content,
        timestamp=now_iso,
        metadata={"mfa_authenticated": mfa_val},
        reliability=_reliability_for_status(ev03_status),
        retrieval_score=1.0,
        hash=_compute_item_hash(case_id, "EV-003", "PAYMENT_AUTHENTICATION", ev03_status.value, mfa_val, "checkout_telemetry"),
        created_at=now_iso
    ))

    # EV-004: Carrier Delivery Proof
    if not has_carrier:
        ev04_status = EvidenceStatus.MISSING
        ev04_contrib = 0.0
        ev04_val = None
        ev04_content = "Carrier delivery tracking proof missing."
    elif "EV-004" in conflicted_ev_ids:
        ev04_status = EvidenceStatus.CONTRADICTED
        ev04_contrib = 0.0
        ev04_val = {
            "carrier_name": payload.carrier_proof.carrier_name,
            "tracking_number": payload.carrier_proof.tracking_number,
            "delivered_status": payload.carrier_proof.delivered_status
        }
        ev04_content = f"Carrier proof CONTRADICTED: Delivered status {payload.carrier_proof.delivered_status} contradicts missing tracking number or signature."
    elif payload.carrier_proof.delivered_status:
        ev04_status = EvidenceStatus.VERIFIED
        ev04_contrib = 25.0
        ev04_val = {
            "carrier_name": payload.carrier_proof.carrier_name,
            "tracking_number": payload.carrier_proof.tracking_number,
            "delivered_status": True
        }
        ev04_content = f"Carrier {payload.carrier_proof.carrier_name or 'courier'} confirmed physical delivery with tracking #{payload.carrier_proof.tracking_number}."
    elif payload.carrier_proof.tracking_number:
        ev04_status = EvidenceStatus.PARTIALLY_VERIFIED
        ev04_contrib = 10.0
        ev04_val = {
            "carrier_name": payload.carrier_proof.carrier_name,
            "tracking_number": payload.carrier_proof.tracking_number,
            "delivered_status": False
        }
        ev04_content = f"Carrier tracking #{payload.carrier_proof.tracking_number} created, but delivery confirmation status is pending/unconfirmed."
    else:
        ev04_status = EvidenceStatus.UNVERIFIED
        ev04_contrib = 0.0
        ev04_val = None
        ev04_content = "Carrier proof unverified with no tracking details."
        
    items.append(EvidenceItem(
        evidence_id="EV-004",
        evidence_type="CARRIER_DELIVERY_PROOF",
        status=ev04_status,
        value=ev04_val,
        source="logistics_carrier",
        rule_ids=["RULE-DELIVERY-VERIFIED"],
        score_contribution=ev04_contrib,
        case_id=case_id,
        source_type="logistics",
        source_id=f"{case_id}_EV-004",
        content=ev04_content,
        timestamp=now_iso,
        metadata=ev04_val or {},
        reliability=_reliability_for_status(ev04_status),
        retrieval_score=1.0,
        hash=_compute_item_hash(case_id, "EV-004", "CARRIER_DELIVERY_PROOF", ev04_status.value, ev04_val, "logistics_carrier"),
        created_at=now_iso
    ))

    # EV-005: Delivery GPS Geolocation
    if not has_carrier or payload.carrier_proof.gps_latitude is None:
        ev05_status = EvidenceStatus.MISSING
        ev05_contrib = 0.0
        ev05_val = None
        ev05_content = "Carrier delivery GPS geolocation telemetry missing."
    elif "EV-005" in conflicted_ev_ids:
        ev05_status = EvidenceStatus.CONTRADICTED
        ev05_contrib = 0.0
        ev05_val = {
            "latitude": payload.carrier_proof.gps_latitude,
            "longitude": payload.carrier_proof.gps_longitude,
            "verified_50m": False
        }
        ev05_content = f"Delivery GPS coordinates ({payload.carrier_proof.gps_latitude}, {payload.carrier_proof.gps_longitude}) lie OUTSIDE the 50m delivery perimeter."
    elif payload.carrier_proof.verified_gps:
        ev05_status = EvidenceStatus.VERIFIED
        ev05_contrib = 15.0
        ev05_val = {
            "latitude": payload.carrier_proof.gps_latitude,
            "longitude": payload.carrier_proof.gps_longitude,
            "verified_50m": True
        }
        ev05_content = f"Carrier delivery GPS verified within 50m geofence radius of cardholder address."
    else:
        ev05_status = EvidenceStatus.UNVERIFIED
        ev05_contrib = 0.0
        ev05_val = {
            "latitude": payload.carrier_proof.gps_latitude,
            "longitude": payload.carrier_proof.gps_longitude,
            "verified_50m": False
        }
        ev05_content = f"Carrier delivery GPS recorded ({payload.carrier_proof.gps_latitude}, {payload.carrier_proof.gps_longitude}) but 50m geofence match unconfirmed."
        
    items.append(EvidenceItem(
        evidence_id="EV-005",
        evidence_type="GPS_GEOLOCATION",
        status=ev05_status,
        value=ev05_val,
        source="carrier_gps_telemetry",
        rule_ids=["RULE-GPS-GEOFENCE"],
        score_contribution=ev05_contrib,
        case_id=case_id,
        source_type="logistics_telemetry",
        source_id=f"{case_id}_EV-005",
        content=ev05_content,
        timestamp=now_iso,
        metadata=ev05_val or {},
        reliability=_reliability_for_status(ev05_status),
        retrieval_score=1.0,
        hash=_compute_item_hash(case_id, "EV-005", "GPS_GEOLOCATION", ev05_status.value, ev05_val, "carrier_gps_telemetry"),
        created_at=now_iso
    ))

    # EV-006: Historical Undisputed Orders
    hist = payload.historical_transactions
    if not hist:
        ev06_status = EvidenceStatus.MISSING
        ev06_contrib = 0.0
        ev06_content = "Zero historical transaction records available in merchant ledger."
    elif any(h.undisputed for h in hist):
        ev06_status = EvidenceStatus.VERIFIED
        ev06_contrib = 20.0
        undisputed_cnt = sum(1 for h in hist if h.undisputed)
        ev06_content = f"Found {len(hist)} prior transactions in core ledger ({undisputed_cnt} undisputed historical orders)."
    else:
        ev06_status = EvidenceStatus.UNVERIFIED
        ev06_contrib = 0.0
        ev06_content = f"Found {len(hist)} prior transactions, but none are confirmed undisputed."
        
    items.append(EvidenceItem(
        evidence_id="EV-006",
        evidence_type="HISTORICAL_ORDERS",
        status=ev06_status,
        value=len(hist),
        source="core_ledger_history",
        rule_ids=["RULE-CE30-COMPLIANCE", "RULE-FPT-COMPLIANCE"],
        score_contribution=ev06_contrib,
        case_id=case_id,
        source_type="ledger",
        source_id=f"{case_id}_EV-006",
        content=ev06_content,
        timestamp=now_iso,
        metadata={"historical_count": len(hist), "undisputed_count": sum(1 for h in hist if h.undisputed)},
        reliability=_reliability_for_status(ev06_status),
        retrieval_score=1.0,
        hash=_compute_item_hash(case_id, "EV-006", "HISTORICAL_ORDERS", ev06_status.value, len(hist), "core_ledger_history"),
        created_at=now_iso
    ))

    # EV-007: Digital Access Logs
    if not has_digital:
        ev07_status = EvidenceStatus.MISSING
        ev07_contrib = 0.0
        ev07_val = None
        ev07_content = "Digital service fulfillment and access telemetry missing."
    elif "EV-007" in conflicted_ev_ids:
        ev07_status = EvidenceStatus.CONTRADICTED
        ev07_contrib = 0.0
        ev07_val = {
            "access_logs_verified": payload.digital_proof.access_logs_verified,
            "user_account_active": payload.digital_proof.user_account_active
        }
        ev07_content = "Digital access logs CONTRADICTION: Access logs claimed as consumed while customer account is inactive or closed."
    elif payload.digital_proof.access_logs_verified and payload.digital_proof.user_account_active:
        ev07_status = EvidenceStatus.VERIFIED
        ev07_contrib = 20.0
        ev07_val = {
            "access_logs_verified": True,
            "user_account_active": True
        }
        ev07_content = "Digital SaaS access logs verified and user account remains active post-purchase."
    elif payload.digital_proof.access_logs_verified:
        ev07_status = EvidenceStatus.PARTIALLY_VERIFIED
        ev07_contrib = 10.0
        ev07_val = {
            "access_logs_verified": True,
            "user_account_active": False
        }
        ev07_content = "Digital SaaS access logs verified, but user account is not active post-purchase."
    else:
        ev07_status = EvidenceStatus.UNVERIFIED
        ev07_contrib = 0.0
        ev07_val = None
        ev07_content = "Digital fulfillment proof unverified with no access log confirmation."
        
    items.append(EvidenceItem(
        evidence_id="EV-007",
        evidence_type="DIGITAL_ACCESS_LOGS",
        status=ev07_status,
        value=ev07_val,
        source="saas_application_telemetry",
        rule_ids=["RULE-DIGITAL-ACCESS"],
        score_contribution=ev07_contrib,
        case_id=case_id,
        source_type="application",
        source_id=f"{case_id}_EV-007",
        content=ev07_content,
        timestamp=now_iso,
        metadata=ev07_val or {},
        reliability=_reliability_for_status(ev07_status),
        retrieval_score=1.0,
        hash=_compute_item_hash(case_id, "EV-007", "DIGITAL_ACCESS_LOGS", ev07_status.value, ev07_val, "saas_application_telemetry"),
        created_at=now_iso
    ))

    statuses = {item.evidence_type: item.status for item in items}
    return items, statuses
    return items, statuses


def extract_evidence_and_contradictions(
    payload: DisputePayload
) -> Tuple[List[EvidenceItem], List[EvidenceContradiction], Dict[str, EvidenceStatus]]:
    """
    Main Evidence Engine Ingress Function:
    Detects contradictions and extracts canonical evidence items with statuses.
    """
    contradictions = detect_contradictions(payload)
    items, statuses = extract_evidence_items(payload, contradictions)
    return items, contradictions, statuses


def calculate_hitl_priority(
    payload: DisputePayload,
    confidence_score: float,
    estimated_win_probability: Optional[float],
    has_contradictions: bool
) -> Tuple[float, str, Dict[str, float]]:
    """
    Calculates Human-in-the-Loop triage priority score [0.0 - 100.0] and urgency level.
    Handles missing deadlines, active deadlines, and overdue deadlines:
    - Overdue (due_by <= now): 50 pts (critical) - ranks ABOVE <6h
    - Urgent (<6h): 40 pts (critical)
    - Warning (<24h): 25 pts (urgent)
    - Normal (>24h or missing): 5 pts (normal)
    Plus amount factor (up to 30 pts), uncertainty factor (up to 20 pts),
    and contradiction boost (15 pts).
    """
    import datetime
    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    due_by = payload.due_by

    if due_by is not None:
        hours_left = (due_by - now) / 3600.0
        if hours_left <= 0:
            deadline_score = 50.0
            urgency = "critical"
        elif hours_left <= 6.0:
            deadline_score = 40.0
            urgency = "critical"
        elif hours_left <= 24.0:
            deadline_score = 25.0
            urgency = "urgent"
        else:
            deadline_score = 5.0
            urgency = "normal"
    else:
        deadline_score = 5.0
        urgency = "normal"

    # Amount factor (0 - 30 pts, max at INR 50,000)
    amt = payload.amount_inr or 0.0
    amount_score = min(30.0, round((amt / 50000.0) * 30.0, 2))

    p = estimated_win_probability if estimated_win_probability is not None else 0.5
    uncertainty_score = round((1.0 - 2.0 * abs(p - 0.5)) * 20.0, 2)

    contradiction_boost = 15.0 if has_contradictions else 0.0
    if has_contradictions and urgency == "normal":
        urgency = "urgent"

    total = min(100.0, round(deadline_score + amount_score + uncertainty_score + contradiction_boost, 1))
    factors = {
        "deadline_score": deadline_score,
        "amount_score": amount_score,
        "uncertainty_score": uncertainty_score,
        "contradiction_boost": contradiction_boost
    }
    return total, urgency, factors


# Compatibility alias
calculate_hitl_priority_score = calculate_hitl_priority

