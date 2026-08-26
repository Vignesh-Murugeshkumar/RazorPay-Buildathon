import time
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from app.core.redis_telemetry import telemetry_hot_cache
from app.core.db import db
from app.core.logger import get_logger
from app.services.ledger import ledger

logger = get_logger("pre_dispute_engine")


class PreDisputeInquiry(BaseModel):
    inquiry_id: str = Field(..., description="Unique Network Pre-Dispute Inquiry/Alert ID")
    network: str = Field(..., description="visa (Verifi Order Insight) | mastercard (Ethoca / Consumer Clarity)")
    card_fingerprint: str = Field(..., description="Hashed card token or PAN fingerprint")
    customer_id: Optional[str] = Field(None, description="Customer Account ID")
    ip_address: Optional[str] = Field(None, description="Current disputed session IP")
    device_fingerprint: Optional[str] = Field(None, description="Current disputed device fingerprint")
    shipping_address: Optional[str] = Field(None, description="Current shipping address")
    amount_inr: float = Field(default=0.0, description="Disputed amount")
    reason_code: Optional[str] = Field(default="10.4", description="Inquiry reason code")
    timestamp: Optional[float] = Field(None, description="Inquiry timestamp")


def matches_ce30_criteria(inquiry_data: Dict[str, Any], historical_orders: List[Dict[str, Any]]) -> bool:
    """
    Evaluates CE 3.0 matching for pre-dispute deflection:
    Requires >= 2 qualifying orders between 120-365 days prior to dispute,
    with >= 2 matched identifiers, at least 1 being IP or Device ID.
    """
    if len(historical_orders) < 2:
        return False

    curr_ip = str(inquiry_data.get("ip_address") or "").strip().lower()
    curr_device = str(inquiry_data.get("device_fingerprint") or "").strip().lower()
    curr_user = str(inquiry_data.get("customer_id") or "").strip().lower()
    curr_addr = str(inquiry_data.get("shipping_address") or "").strip().lower()

    qualifying_subset = historical_orders[:2]

    def check_ip(tx_ip: str, target: str) -> bool:
        if not tx_ip or not target:
            return False
        if tx_ip == target:
            return True
        p1 = tx_ip.split(".")
        p2 = target.split(".")
        return len(p1) == 4 and len(p2) == 4 and p1[:3] == p2[:3]

    ip_matches = all(check_ip(str(tx.get("ip_address", "")).strip().lower(), curr_ip) for tx in qualifying_subset)
    device_matches = all(str(tx.get("device_fingerprint", "")).strip().lower() == curr_device and curr_device != "" for tx in qualifying_subset)
    user_matches = all(str(tx.get("customer_id", "")).strip().lower() == curr_user and curr_user != "" for tx in qualifying_subset)
    addr_matches = all(str(tx.get("shipping_address", "")).strip().lower() == curr_addr and curr_addr != "" for tx in qualifying_subset)

    matched_count = sum([1 if ip_matches else 0, 1 if device_matches else 0, 1 if user_matches else 0, 1 if addr_matches else 0])
    ip_or_device = ip_matches or device_matches

    return matched_count >= 2 and ip_or_device


async def handle_pre_dispute_inquiry(inquiry_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deterministic Upstream Pre-Dispute Interception Engine.
    Responds within the mandatory <= 2-second network SLA to deflect inquiries
    before they convert into formal chargebacks, protecting VAMP & ECM dispute ratios.
    """
    start_time = time.perf_counter()
    inquiry_id = inquiry_payload.get("inquiry_id", f"inq_{int(time.time()*1000)}")
    network = inquiry_payload.get("network", "visa").lower()
    card_fingerprint = inquiry_payload.get("card_fingerprint", "")

    # Query Hot Redis Cache for qualifying CE 3.0 / FPT credentials (120-365 days lookback)
    history = telemetry_hot_cache.get_qualifying_orders(
        card_fingerprint=card_fingerprint,
        min_days=120,
        max_days=365,
        reference_time=inquiry_payload.get("timestamp")
    )

    is_deflected = False
    evidence_type = None
    orders_to_return = []

    if len(history) >= 2 and matches_ce30_criteria(inquiry_payload, history):
        is_deflected = True
        evidence_type = "CE_3_0" if network == "visa" else "FPT_TIER_1"
        orders_to_return = history[:2]
        status_result = "DEFLECTED"
    else:
        status_result = "NO_MATCH"

    elapsed_ms = (time.perf_counter() - start_time) * 1000.0

    # Log to cryptographic ledger
    ledger.append_block(
        agent_id="PRE_DISPUTE_INTERCEPTION_ENGINE",
        state_transition="PRE_DISPUTE_EVALUATED",
        payload={
            "inquiry_id": inquiry_id,
            "network": network,
            "card_fingerprint": card_fingerprint[:16] + "..." if len(card_fingerprint) > 16 else card_fingerprint,
            "status": status_result,
            "evidence_type": evidence_type,
            "qualifying_orders_found": len(history),
            "response_time_ms": round(elapsed_ms, 3)
        }
    )

    # Persist log in DB
    db.save_pre_dispute_log(
        inquiry_id=inquiry_id,
        network=network,
        card_fingerprint=card_fingerprint,
        status=status_result,
        evidence_type=evidence_type,
        response_time_ms=round(elapsed_ms, 3),
        payload=inquiry_payload
    )

    logger.info(
        "Pre-dispute inquiry evaluated",
        inquiry_id=inquiry_id,
        network=network,
        status=status_result,
        response_time_ms=round(elapsed_ms, 3)
    )

    if is_deflected:
        return {
            "status": "DEFLECTED",
            "inquiry_id": inquiry_id,
            "network": network,
            "evidence_type": evidence_type,
            "orders": orders_to_return,
            "sla_guaranteed": elapsed_ms <= 2000.0,
            "response_time_ms": round(elapsed_ms, 3),
            "message": "Inquiry successfully deflected under Compelling Evidence 3.0 / First-Party Trust rules."
        }

    return {
        "status": "NO_MATCH",
        "inquiry_id": inquiry_id,
        "network": network,
        "sla_guaranteed": elapsed_ms <= 2000.0,
        "response_time_ms": round(elapsed_ms, 3),
        "message": "Insufficient matching historical transactions to qualify for pre-dispute deflection."
    }
