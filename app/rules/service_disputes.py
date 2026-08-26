from typing import List, Dict, Tuple, Any, Optional
from pydantic import BaseModel, Field

from app.models.dispute import (
    DisputePayload,
    RuleEvaluationResult
)


def evaluate_service_dispute_compliance(payload: DisputePayload) -> Tuple[bool, float, List[str], Dict[str, float]]:
    """
    Evaluates Non-Fraud Reason Codes:
    - Visa 13.1: Merchandise / Services Not Received
    - Visa 13.7: Cancelled Merchandise / Services
    - Mastercard 4853: Goods / Services Not as Described
    - Mastercard 4855: Goods / Services Not Provided

    Returns:
    - (is_compliant, confidence_score, gaps, score_breakdown)
    """
    gaps: List[str] = []
    score_breakdown: Dict[str, float] = {}
    code = str(payload.reason_code).strip()
    score = 0.0

    has_carrier = payload.carrier_proof is not None
    carrier_delivered = has_carrier and payload.carrier_proof.delivered_status
    has_signature = has_carrier and payload.carrier_proof.recipient_signature_present
    has_gps = has_carrier and payload.carrier_proof.verified_gps

    has_digital = payload.digital_proof is not None
    digital_access = has_digital and payload.digital_proof.access_logs_verified

    # 1. Delivery & Proof-of-Fulfillment Scoring (45 points)
    if carrier_delivered or digital_access:
        score += 45.0
        score_breakdown["fulfillment_delivery_proof"] = 45.0
    else:
        gaps.append(f"Reason {code} requires verified carrier delivery receipt or digital access logs")

    # 2. Recipient Signature / Explicit Authorization (25 points)
    if has_signature:
        score += 25.0
        score_breakdown["recipient_signature"] = 25.0
    elif digital_access and payload.digital_proof.ip_subnet_matched:
        score += 25.0
        score_breakdown["digital_ip_subnet_match"] = 25.0
    else:
        gaps.append("Missing recipient physical signature or authenticated digital access proof")

    # 3. GPS Geofence Verification (15 points)
    if has_gps:
        score += 15.0
        score_breakdown["gps_geofence_verified"] = 15.0
    elif has_digital and payload.digital_proof.user_account_active:
        score += 15.0
        score_breakdown["active_account_consumption"] = 15.0

    # 4. MFA / 3D-Secure Authorization (15 points)
    if payload.telemetry and payload.telemetry.mfa_authenticated:
        score += 15.0
        score_breakdown["mfa_3ds_authenticated"] = 15.0

    # Specific Reason Code Requirements
    if code in ("13.7", "4853"):
        # Cancellation / Description disputes require Terms of Service / Refund Policy evidence
        score_breakdown["terms_and_cancellation_policy"] = 10.0
        score = min(100.0, score + 10.0)

    is_compliant = score >= 70.0
    if not is_compliant and not gaps:
        gaps.append(f"Dossier score {score}/100.0 falls below standard network representment threshold")

    return is_compliant, round(score, 1), gaps, score_breakdown
