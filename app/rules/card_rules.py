from typing import List, Dict, Tuple, Any
from app.schemas.dispute import (
    DisputePayload,
    HistoricalTransaction,
    RuleEvaluationResult
)


def normalize_str(val: str) -> str:
    if not val:
        return ""
    return str(val).strip().lower()


def is_ip_or_subnet_match(ip1: str, ip2: str) -> bool:
    """Checks exact IP match or /24 CIDR subnet match."""
    s1 = normalize_str(ip1)
    s2 = normalize_str(ip2)
    if not s1 or not s2:
        return False
    if s1 == s2:
        return True
    parts1 = s1.split(".")
    parts2 = s2.split(".")
    if len(parts1) == 4 and len(parts2) == 4:
        return parts1[:3] == parts2[:3]
    return False


def evaluate_visa_ce30(
    payload: DisputePayload
) -> Tuple[bool, int, List[str], bool, List[str]]:
    """
    Evaluates Visa Compelling Evidence 3.0 (CE 3.0) compliance for Reason Code 10.4:
    1. Transaction Quantity: >= 2 historical undisputed transactions.
    2. Lookback Window: Between 120 and 365 calendar days prior to dispute.
    3. Data Matching Criteria: At least 2 of 4 core customer identifiers match:
       - Customer IP Address (or /24 subnet match)
       - Device ID / Fingerprint
       - Account Login / User ID
       - Shipping Address (or Digital SaaS account)
    4. Mandatory Condition: At least 1 of the matched identifiers must be IP Address OR Device ID.
    
    Returns:
    - (is_compliant, qualifying_count, matched_identifiers, ip_or_device_matched, gaps)
    """
    gaps: List[str] = []
    
    # 1. Filter qualifying historical orders (undisputed and 120 <= days_ago <= 365)
    qualifying_orders: List[HistoricalTransaction] = []
    for tx in payload.historical_transactions:
        if tx.undisputed and 120 <= tx.days_ago <= 365:
            qualifying_orders.append(tx)
            
    if len(qualifying_orders) < 2:
        gaps.append(
            f"Visa CE 3.0 requires >= 2 qualifying undisputed transactions in 120-365d window; found {len(qualifying_orders)}"
        )
        return False, len(qualifying_orders), [], False, gaps

    # Take the top qualifying orders (at least 2)
    orders_to_check = qualifying_orders[:2]
    
    # 2. Check 4 core identifiers across dispute telemetry and qualifying historical orders
    curr_ip = normalize_str(payload.telemetry.ip_address)
    curr_device = normalize_str(payload.telemetry.device_id)
    curr_user = normalize_str(payload.telemetry.user_id)
    curr_addr = normalize_str(payload.telemetry.shipping_address)
    
    ip_matches = all(is_ip_or_subnet_match(tx.ip_address, curr_ip) for tx in orders_to_check)
    device_matches = all(normalize_str(tx.device_id) == curr_device and curr_device != "" for tx in orders_to_check)
    user_matches = all(normalize_str(tx.user_id) == curr_user and curr_user != "" for tx in orders_to_check)
    addr_matches = all(normalize_str(tx.shipping_address) == curr_addr and curr_addr != "" for tx in orders_to_check)
    
    matched_ids: List[str] = []
    if ip_matches:
        matched_ids.append("ip_address")
    if device_matches:
        matched_ids.append("device_id")
    if user_matches:
        matched_ids.append("user_id")
    if addr_matches:
        matched_ids.append("shipping_address")
        
    ip_or_device = ip_matches or device_matches
    
    if len(matched_ids) < 2:
        gaps.append(
            f"Visa CE 3.0 requires >= 2 matched identifiers across all 3 transactions; matched {len(matched_ids)}: {matched_ids}"
        )
        
    if not ip_or_device:
        gaps.append(
            "Visa CE 3.0 mandatory condition failed: Neither IP Address nor Device ID matched across transactions"
        )
        
    is_compliant = (len(matched_ids) >= 2) and ip_or_device
    return is_compliant, len(qualifying_orders), matched_ids, ip_or_device, gaps


def evaluate_mastercard_fpt(
    payload: DisputePayload
) -> Tuple[bool, int, List[str], bool, List[str]]:
    """
    Evaluates Mastercard First-Party Trust (FPT) compliance for Reason Codes 4837, 4853, 4855:
    1. >= 2 prior undisputed orders within 365 days lookback.
    2. 3-tier matching matrix:
       - Tier 1 (Device Identity): Persistent Device Fingerprint or IP address match.
       - Tier 2 (Delivery Factor): Carrier proof of physical delivery or digital fulfillment access logs.
       - Tier 3 (Authentication Factor): 2FA/MFA/3DS or account login match.
    """
    gaps: List[str] = []
    
    # Filter qualifying historical orders (undisputed and days_ago <= 365)
    qualifying_orders = [tx for tx in payload.historical_transactions if tx.undisputed and 1 <= tx.days_ago <= 365]
    if len(qualifying_orders) < 2:
        gaps.append(
            f"Mastercard FPT requires >= 2 undisputed transactions in 365d lookback; found {len(qualifying_orders)}"
        )
        return False, len(qualifying_orders), [], False, gaps

    curr_ip = normalize_str(payload.telemetry.ip_address)
    curr_device = normalize_str(payload.telemetry.device_id)
    curr_user = normalize_str(payload.telemetry.user_id)
    
    orders_to_check = qualifying_orders[:2]
    ip_matches = all(is_ip_or_subnet_match(tx.ip_address, curr_ip) for tx in orders_to_check)
    device_matches = all(normalize_str(tx.device_id) == curr_device and curr_device != "" for tx in orders_to_check)
    user_matches = all(normalize_str(tx.user_id) == curr_user and curr_user != "" for tx in orders_to_check)
    
    matched_ids: List[str] = []
    if ip_matches:
        matched_ids.append("ip_address")
    if device_matches:
        matched_ids.append("device_id")
    if user_matches:
        matched_ids.append("user_id")
        
    tier1_device_id = ip_matches or device_matches
    
    # Tier 2: Carrier physical proof OR digital fulfillment logs
    is_digital = (payload.service_type == "digital_saas") or (payload.digital_proof is not None)
    if is_digital and payload.digital_proof:
        tier2_delivery = payload.digital_proof.access_logs_verified
    else:
        tier2_delivery = payload.carrier_proof is not None and payload.carrier_proof.delivered_status

    tier3_auth = payload.telemetry.mfa_authenticated or user_matches
    
    if not tier1_device_id:
        gaps.append("Mastercard FPT Tier 1 failed: No consistent Device Fingerprint or IP address match")
    if not tier2_delivery:
        gaps.append("Mastercard FPT Tier 2 failed: Missing verified carrier delivery or digital access confirmation")
    if not tier3_auth:
        gaps.append("Mastercard FPT Tier 3 failed: No 2FA/MFA or account login factor match")
        
    # Full FPT compliance requires Tier 1 and Tier 2, supported by Tier 3
    is_compliant = tier1_device_id and tier2_delivery and (tier3_auth or len(matched_ids) >= 2)
    return is_compliant, len(qualifying_orders), matched_ids, tier1_device_id, gaps


def calculate_confidence_score(
    network_compliant: bool,
    carrier_delivered: bool,
    carrier_gps_verified: bool,
    mfa_verified: bool,
    digital_verified: bool = False,
    digital_active_verified: bool = False
) -> Tuple[float, Dict[str, float]]:
    """
    Calculates the Dossier Confidence Score Sc in [0.0, 100.0]:
    Sc = w_compliance + w_fulfillment + w_location_or_activity + w_mfa
    - w_compliance = 55.0 (CE 3.0 / FPT network compliance)
    - w_fulfillment = 35.0 (Carrier delivery or Digital access logs verified)
    - location/active bonus = 10.0 (GPS within 50m radius or active session + subnet match)
    - w_mfa = 5.0 (3DS / 2FA verified)
    
    Max score is 100.0.
    Gatekeeper rule: Sc >= 85.0 -> AUTO_DISPATCH, Sc < 85.0 -> ROUTE_TO_HITL_QUEUE
    """
    fulfillment_verified = carrier_delivered or digital_verified
    location_or_activity_bonus = (carrier_delivered and carrier_gps_verified) or (digital_verified and digital_active_verified)

    w_compliance = 55.0 if network_compliant else 0.0
    w_fulfillment = 35.0 if fulfillment_verified else 0.0
    w_bonus = 10.0 if location_or_activity_bonus else 0.0
    w_mfa = 5.0 if mfa_verified else 0.0
    
    raw_score = w_compliance + w_fulfillment + w_bonus + w_mfa
    score = min(100.0, round(raw_score, 2))
    
    breakdown = {
        "network_compliance_points": w_compliance,
        "fulfillment_delivery_points": w_fulfillment,
        "carrier_gps_or_activity_bonus": w_bonus,
        "mfa_verification_points": w_mfa,
        "total_score": score
    }
    # Keep legacy key aliases for backwards compatibility
    breakdown["carrier_delivery_points"] = w_fulfillment
    breakdown["carrier_gps_bonus"] = w_bonus
    return score, breakdown


def evaluate_dispute_compliance(payload: DisputePayload) -> RuleEvaluationResult:
    """
    Master compliance evaluation for incoming dispute payloads.
    Routes to Visa CE 3.0 or Mastercard FPT based on card network and service type.
    """
    network = normalize_str(payload.card_network)
    reason_code = str(payload.reason_code).strip()
    
    ce30_compliant = False
    fpt_compliant = False
    qualifying_count = 0
    matched_ids: List[str] = []
    ip_or_device = False
    gaps: List[str] = []
    
    if "visa" in network or reason_code == "10.4":
        ce30_compliant, qualifying_count, matched_ids, ip_or_device, gaps = evaluate_visa_ce30(payload)
        network_compliant = ce30_compliant
    elif "mastercard" in network or reason_code in ["4837", "4853", "4855"]:
        fpt_compliant, qualifying_count, matched_ids, ip_or_device, gaps = evaluate_mastercard_fpt(payload)
        network_compliant = fpt_compliant
    else:
        # Generic Card Network Evaluation (Fallback to CE 3.0 standard)
        ce30_compliant, qualifying_count, matched_ids, ip_or_device, gaps = evaluate_visa_ce30(payload)
        network_compliant = ce30_compliant

    # Fulfillment verification (Physical Carrier OR Digital SaaS)
    is_digital = (payload.service_type == "digital_saas") or (payload.digital_proof is not None)
    
    carrier_delivered = bool(payload.carrier_proof and payload.carrier_proof.delivered_status)
    carrier_gps = bool(payload.carrier_proof and payload.carrier_proof.verified_gps)
    
    digital_verified = bool(payload.digital_proof and payload.digital_proof.access_logs_verified)
    digital_active = bool(payload.digital_proof and payload.digital_proof.user_account_active and payload.digital_proof.ip_subnet_matched)

    if not is_digital and not carrier_delivered:
        gaps.append("Carrier proof is missing or delivery status is unconfirmed")
    elif is_digital and not digital_verified:
        gaps.append("Digital SaaS fulfillment proof is missing or access logs unverified")
        
    # MFA verification
    mfa_verified = bool(payload.telemetry.mfa_authenticated)
    
    # Calculate score
    confidence_score, breakdown = calculate_confidence_score(
        network_compliant=network_compliant,
        carrier_delivered=carrier_delivered,
        carrier_gps_verified=carrier_gps,
        mfa_verified=mfa_verified,
        digital_verified=digital_verified,
        digital_active_verified=digital_active
    )
    
    # Gatekeeper Decision: >= 85 -> AUTO_DISPATCH, else ROUTE_TO_HITL_QUEUE
    route_decision = "AUTO_DISPATCH" if confidence_score >= 85.0 else "ROUTE_TO_HITL_QUEUE"
    
    return RuleEvaluationResult(
        network=payload.card_network,
        reason_code=payload.reason_code,
        ce30_compliant=ce30_compliant,
        fpt_compliant=fpt_compliant,
        qualifying_orders_count=qualifying_count,
        matched_identifiers=matched_ids,
        ip_or_device_matched=ip_or_device,
        carrier_verified=carrier_delivered,
        digital_verified=digital_verified,
        gps_verified=carrier_gps or digital_active,
        mfa_verified=mfa_verified,
        confidence_score=confidence_score,
        route_decision=route_decision,
        diagnostic_gaps=gaps,
        score_breakdown=breakdown
    )
