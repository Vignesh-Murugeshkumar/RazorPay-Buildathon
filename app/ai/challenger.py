"""
SentinelDispute - Adversarial Claim Challenger.

For every significant claim, introduces a deliberate attempt to DISPROVE it.
Asks: "What evidence would make this claim false?"

Pipeline Role:
Evidence -> Claim -> [CHALLENGE] -> Verification -> Policy -> Decision -> Provenance

For each claim generates:
- Claim ID
- Challenge inquiry
- Contrary evidence IDs
- Alternative explanation
- Missing evidence
- Challenge strength (0.0 - 1.0)
- Challenge result ("overturned" | "weakened" | "sustained")
"""

from typing import List, Dict, Any, Optional
from app.schemas.dispute import (
    EvidenceItem,
    EvidenceStatus,
    EvidenceContradiction,
    ClaimChallenge,
    InvestigationClaim
)
from app.ai.prompts import AIClaimItem, DisputeInvestigationReport
from app.core.logger import get_logger

logger = get_logger("claim_challenger")


class ClaimChallenger:
    """
    Adversarial reasoning engine that actively seeks disconfirming evidence
    and counter-narratives for every factual assertion made during investigation.
    """

    def challenge_claims(
        self,
        claims: List[Any],  # List of AIClaimItem or InvestigationClaim or dicts
        evidence_items: List[EvidenceItem],
        contradictions: List[EvidenceContradiction],
        dispute_metadata: Optional[Dict[str, Any]] = None
    ) -> List[ClaimChallenge]:
        """
        Executes adversarial challenge pass against each candidate claim.
        Returns a list of structured ClaimChallenge objects.
        """
        item_map: Dict[str, EvidenceItem] = {item.evidence_id: item for item in evidence_items}
        challenges: List[ClaimChallenge] = []
        conflicted_ev_ids = set()
        for c in contradictions:
            conflicted_ev_ids.update(c.evidence_ids)

        metadata = dispute_metadata or {}
        reason_code = str(metadata.get("reason_code", "10.4")).strip()

        for raw_claim in claims:
            cid = getattr(raw_claim, "claim_id", None) or raw_claim.get("claim_id", "CLM-UNKNOWN")
            ctext = getattr(raw_claim, "claim", None) or getattr(raw_claim, "claim_text", "") or raw_claim.get("claim", "")
            cited_ev_ids = getattr(raw_claim, "evidence_ids", None) or raw_claim.get("evidence_ids", [])
            
            ctext_lower = ctext.lower()
            contrary_ids: List[str] = []
            missing_ids: List[str] = []
            alt_explanation = ""
            challenge_query = ""
            strength = 0.15
            result = "sustained"

            # -----------------------------------------------------------------
            # 1. Delivery & Fulfillment Claims Challenge
            # -----------------------------------------------------------------
            if any(k in ctext_lower for k in ("delivery", "delivered", "carrier", "tracking", "fulfillment", "shipped")):
                ev_gps = item_map.get("EV-005")
                ev_carrier = item_map.get("EV-004")

                # Check GPS Geofence Contradiction
                if ev_gps and ev_gps.status == EvidenceStatus.CONTRADICTED:
                    contrary_ids.append("EV-005")
                    challenge_query = "Carrier coordinates deviate from cardholder shipping address perimeter."
                    alt_explanation = (
                        "Package marked delivered by carrier was dropped outside the 50-meter perimeter "
                        "(possible misdelivery or courier scan error), which supports cardholder's non-receipt dispute."
                    )
                    strength = 0.88
                    result = "overturned"
                elif ev_gps and ev_gps.status in (EvidenceStatus.MISSING, EvidenceStatus.UNVERIFIED):
                    missing_ids.append("EV-005")
                    challenge_query = "Carrier proof lacks GPS geolocation match within 50m radius."
                    alt_explanation = "Tracking number confirmed but lacks strict GPS coordinates confirming actual drop-off location."
                    strength = 0.55
                    result = "weakened"

                # Check Tracking unconfirmed or signature missing
                if ev_carrier and ev_carrier.status == EvidenceStatus.PARTIALLY_VERIFIED:
                    challenge_query = "Carrier tracking number exists but status is in-transit or unconfirmed."
                    alt_explanation = "Shipment was initiated by merchant but delivery was not completed before dispute was filed."
                    strength = max(strength, 0.65)
                    result = "weakened" if result != "overturned" else result
                elif ev_carrier and ev_carrier.status == EvidenceStatus.MISSING:
                    missing_ids.append("EV-004")
                    challenge_query = "Physical goods dispute submitted with no carrier proof."
                    alt_explanation = "No proof of dispatch or delivery available to rebut claim."
                    strength = 0.95
                    result = "overturned"

            # -----------------------------------------------------------------
            # 2. Cardholder Authentication / 3DS Claims Challenge
            # -----------------------------------------------------------------
            elif any(k in ctext_lower for k in ("3ds", "authentication", "authorized", "mfa", "passcode", "otp")):
                ev_mfa = item_map.get("EV-003")
                if ev_mfa and ev_mfa.status in (EvidenceStatus.MISSING, EvidenceStatus.UNVERIFIED):
                    contrary_ids.append("EV-003")
                    challenge_query = "Transaction was processed without Verified by Visa / Mastercard Identity Check 3DS shift."
                    alt_explanation = "Lack of 2FA/3DS authentication means liability shift does not protect merchant against fraud claims."
                    strength = 0.82
                    result = "overturned"
                elif ev_mfa and ev_mfa.value is False:
                    contrary_ids.append("EV-003")
                    challenge_query = "Payment gateway confirms transaction was NOT 3DS authenticated."
                    alt_explanation = "Non-3DS frictionless transaction leaves merchant liable under network fraud rules."
                    strength = 0.90
                    result = "overturned"

            # -----------------------------------------------------------------
            # 3. Behavioral Anomaly / Identity Claims Challenge
            # -----------------------------------------------------------------
            elif any(k in ctext_lower for k in ("anomaly", "inconsistent", "device", "ip", "telemetry", "behavior")):
                ev_ip = item_map.get("EV-001")
                ev_dev = item_map.get("EV-002")
                ev_hist = item_map.get("EV-006")

                # If claim asserts customer IP or device matched, but evidence shows missing or mismatched
                if ("matched" in ctext_lower or "verified" in ctext_lower):
                    if ev_ip and ev_ip.status in (EvidenceStatus.MISSING, EvidenceStatus.UNVERIFIED):
                        contrary_ids.append("EV-001")
                        challenge_query = "Customer IP address not verified against prior transaction history."
                        alt_explanation = "Customer may have purchased from an unfamiliar network or commercial proxy."
                        strength = max(strength, 0.60)
                        result = "weakened"
                    if ev_dev and ev_dev.status in (EvidenceStatus.MISSING, EvidenceStatus.UNVERIFIED):
                        contrary_ids.append("EV-002")
                        challenge_query = "Device fingerprint missing from checkout session."
                        alt_explanation = "Device identification absent; purchase could have originated from new or untrusted device."
                        strength = max(strength, 0.65)
                        result = "weakened"
                
                # If claim asserts customer behavioral fraud, but historical orders exist
                if ("fraud" in ctext_lower or "unusual" in ctext_lower or "suspicious" in ctext_lower):
                    if ev_hist and ev_hist.status == EvidenceStatus.VERIFIED:
                        contrary_ids.append("EV-006")
                        challenge_query = "Cardholder has legitimate undisputed historical transactions with merchant."
                        alt_explanation = (
                            "Unusual transaction amount or frequency may represent a legitimate holiday/gift purchase "
                            "consistent with cardholder's multi-month account tenure."
                        )
                        strength = 0.72
                        result = "weakened"

            # -----------------------------------------------------------------
            # 4. Digital SaaS / License Consumption Claims Challenge
            # -----------------------------------------------------------------
            elif any(k in ctext_lower for k in ("digital", "saas", "license", "access", "download", "login")):
                ev_dig = item_map.get("EV-007")
                if ev_dig and ev_dig.status == EvidenceStatus.CONTRADICTED:
                    contrary_ids.append("EV-007")
                    challenge_query = "Access logs claimed as consumed while customer account is inactive or closed."
                    alt_explanation = "Account closed or banned prior to consumption indicates customer did not receive usable access."
                    strength = 0.92
                    result = "overturned"
                elif ev_dig and ev_dig.status in (EvidenceStatus.MISSING, EvidenceStatus.UNVERIFIED):
                    missing_ids.append("EV-007")
                    challenge_query = "No digital server access or download logs recorded for transaction."
                    alt_explanation = "Merchant cannot prove service utilization or software activation."
                    strength = 0.85
                    result = "overturned"
                elif ev_dig and ev_dig.status == EvidenceStatus.PARTIALLY_VERIFIED:
                    challenge_query = "Digital logs verified but user account is currently inactive."
                    alt_explanation = "Customer logged in initially but requested cancellation/refund before service period elapsed."
                    strength = 0.58
                    result = "weakened"

            # -----------------------------------------------------------------
            # 5. Network Rule Compliance (CE 3.0 / FPT) Challenge
            # -----------------------------------------------------------------
            elif any(k in ctext_lower for k in ("ce30", "ce 3.0", "fpt", "lookback", "qualifying", "rule")):
                ev_hist = item_map.get("EV-006")
                if ev_hist and (ev_hist.status in (EvidenceStatus.MISSING, EvidenceStatus.UNVERIFIED) or (isinstance(ev_hist.value, int) and ev_hist.value < 2)):
                    contrary_ids.append("EV-006")
                    challenge_query = "Merchant has fewer than 2 undisputed qualifying historical orders in 120-365 day window."
                    alt_explanation = "Visa CE 3.0 / Mastercard FPT require minimum 2 historical orders; requirement not met."
                    strength = 0.95
                    result = "overturned"

            # -----------------------------------------------------------------
            # 6. Fallback Challenge for Any Cited Conflicted Evidence
            # -----------------------------------------------------------------
            for cited_id in cited_ev_ids:
                if cited_id in conflicted_ev_ids and cited_id not in contrary_ids:
                    contrary_ids.append(cited_id)
                    challenge_query = f"Cited evidence {cited_id} has an unresolved objective contradiction."
                    alt_explanation = f"Evidence {cited_id} conflicts with secondary telemetry in the case file."
                    strength = 0.89
                    result = "overturned"

            # Default challenge if none of the above triggered
            if not challenge_query:
                challenge_query = f"Could claim '{ctext[:60]}...' be invalidated by missing issuer context or alternate buyer intent?"
                alt_explanation = "Cardholder dispute statement may present alternative claims of family fraud or billing confusion."
                strength = 0.20
                result = "sustained"

            challenges.append(ClaimChallenge(
                claim_id=cid,
                challenge=challenge_query,
                contrary_evidence_ids=contrary_ids,
                alternative_explanation=alt_explanation,
                missing_evidence=missing_ids,
                challenge_strength=round(strength, 2),
                challenge_result=result
            ))

        return challenges


claim_challenger = ClaimChallenger()
