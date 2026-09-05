from typing import Dict, Any
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/rules", tags=["Rule Engine & Regulatory Frameworks"])

RULES_REGISTRY = {
    "visa": {
        "network": "Visa",
        "regulations": [
            {
                "id": "VISA_CE30",
                "name": "Compelling Evidence 3.0 (CE 3.0)",
                "reason_codes": ["10.4"],
                "description": "Deterministic rule framework allowing merchants to establish legitimate cardholder participation via historical undisputed transactions.",
                "lookback_window_days": {
                    "min": 120,
                    "max": 365
                },
                "qualifying_threshold": 2,
                "matching_requirements": [
                    "Card fingerprint / PAN match",
                    "Device fingerprint or IP address match",
                    "At least one secondary credential (shipping address, user ID, or verified account ID)"
                ],
                "liability_shift_eligible": True,
                "confidence_weights": {
                    "historical_transactions": 55.0,
                    "carrier_proof": 25.0,
                    "gps_verification": 10.0,
                    "mfa_3ds": 10.0
                },
                "routing_thresholds": {
                    "auto_dispatch": "Sc >= 70.0 and E[V] > 0",
                    "hitl_review": "40.0 <= Sc < 70.0 and E[V] > 0",
                    "auto_accept": "E[V] <= 0"
                }
            },
            {
                "id": "VISA_13_1",
                "name": "Merchandise / Services Not Received",
                "reason_codes": ["13.1"],
                "description": "Rules for physical and digital delivery disputes requiring carrier proof of delivery, tracking number, and recipient signature.",
                "requirements": [
                    "Physical carrier tracking number and proof of delivery status",
                    "Recipient signature on delivery record",
                    "Optional GPS delivery scan within 50m of delivery address"
                ],
                "confidence_weights": {
                    "carrier_delivered": 45.0,
                    "recipient_signature": 25.0,
                    "gps_match": 15.0,
                    "mfa_verified": 15.0
                }
            },
            {
                "id": "VISA_13_7",
                "name": "Cancelled Merchandise / Services",
                "reason_codes": ["13.7"],
                "description": "Disputes relating to recurring billing or cancellation requests.",
                "requirements": [
                    "Transparent cancellation policy acknowledged at checkout",
                    "Digital access logs proving service usage post-disputed date",
                    "Customer interaction communication records"
                ]
            }
        ]
    },
    "mastercard": {
        "network": "Mastercard",
        "regulations": [
            {
                "id": "MC_FPT",
                "name": "First-Party Trust (FPT)",
                "reason_codes": ["4837"],
                "description": "Mastercard First-Party Trust program for friendly fraud defense using prior verified cardholder transaction history.",
                "lookback_window_days": {
                    "min": 30,
                    "max": 365
                },
                "qualifying_threshold": 1,
                "matching_requirements": [
                    "PAN / Card account token match",
                    "Device ID or IP address match",
                    "Delivery address or biometric authentication match"
                ],
                "liability_shift_eligible": True,
                "confidence_weights": {
                    "historical_transactions": 50.0,
                    "carrier_proof": 30.0,
                    "gps_verification": 10.0,
                    "mfa_3ds": 10.0
                }
            },
            {
                "id": "MC_4853",
                "name": "Goods or Services Not as Described",
                "reason_codes": ["4853"],
                "description": "Proof of item description, terms and conditions agreement, and customer support records."
            },
            {
                "id": "MC_4855",
                "name": "Goods Not Delivered",
                "reason_codes": ["4855"],
                "description": "Carrier tracking verification and physical delivery confirmation."
            }
        ]
    },
    "rupay": {
        "network": "RuPay",
        "regulations": [
            {
                "id": "RUPAY_FRAUD_DEFENSE",
                "name": "RuPay Compelling Evidence Standard",
                "reason_codes": ["10.4", "DR-01"],
                "description": "NPCI RuPay dispute defense framework leveraging 2FA/OTP records, delivery slips, and transaction logs.",
                "requirements": [
                    "OTP / SMS 2FA verification log",
                    "Carrier delivery confirmation",
                    "Merchant invoice and terms disclosure"
                ]
            }
        ]
    },
    "amex": {
        "network": "American Express",
        "rule_status": "demo_implementation",
        "source": "scheme_rules_reference",
        "last_reviewed": None,
        "implementation_notes": [
            "Implementation for demonstration purposes; verify current scheme documentation before production use"
        ],
        "regulations": [
            {
                "id": "AMEX_INQUIRY_DEFENSE",
                "name": "Amex Inquiry & Chargeback Defense",
                "reason_codes": ["F29", "C08"],
                "description": "American Express pre-dispute inquiry and formal chargeback representment guidelines."
            }
        ]
    }
}

DISCLAIMER_TEXT = "Implementation for demonstration purposes; verify current scheme documentation before production use."

# Inject accuracy metadata into each network
for net_key, net_obj in RULES_REGISTRY.items():
    net_obj["rule_status"] = "demo_implementation"
    net_obj["source"] = "scheme_rules_reference"
    net_obj["last_reviewed"] = None
    net_obj["disclaimer"] = DISCLAIMER_TEXT
    net_obj["implementation_notes"] = [
        "Implementation for demonstration purposes; verify current scheme documentation before production use",
        "Derived from card scheme reference specifications"
    ]


@router.get("/{network}")
async def get_network_rules(network: str):
    """
    Retrieves regulatory rules, qualification criteria, and scoring weights
    for a specific card network (visa, mastercard, rupay, amex, or all).
    """
    net_clean = network.lower().strip()
    if net_clean == "all":
        return {
            "disclaimer": DISCLAIMER_TEXT,
            "rule_status": "demo_implementation",
            "networks": list(RULES_REGISTRY.keys()),
            "rules": RULES_REGISTRY
        }
    
    if net_clean not in RULES_REGISTRY:
        raise HTTPException(
            status_code=404,
            detail=f"Network '{network}' not supported. Supported networks: visa, mastercard, rupay, amex, all"
        )
    
    res = dict(RULES_REGISTRY[net_clean])
    res["disclaimer"] = DISCLAIMER_TEXT
    return res
