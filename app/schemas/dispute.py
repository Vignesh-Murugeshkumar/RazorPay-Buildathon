from typing import List, Optional, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field, model_validator
from datetime import datetime


class EvidenceStatus(str, Enum):
    VERIFIED = "VERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    MISSING = "MISSING"
    CONTRADICTED = "CONTRADICTED"


class EvidenceItem(BaseModel):
    evidence_id: str
    evidence_type: str
    status: EvidenceStatus = EvidenceStatus.MISSING
    value: Any = None
    source: str = "unknown"
    rule_ids: List[str] = Field(default_factory=list)
    score_contribution: float = 0.0
    supports_claim_ids: List[str] = Field(default_factory=list)
    details: Optional[Dict[str, Any]] = None


class EvidenceContradiction(BaseModel):
    conflict_id: str
    evidence_ids: List[str] = Field(default_factory=list)
    fields: List[str] = Field(default_factory=list)
    description: str
    severity: str = "HIGH"  # HIGH | MEDIUM


class CustomerTelemetry(BaseModel):
    ip_address: Optional[str] = Field(None, description="IPv4 or IPv6 of the customer at checkout")
    device_id: Optional[str] = Field(None, description="Persistent device fingerprint or UUID")
    user_id: Optional[str] = Field(None, description="Customer account ID or username")
    shipping_address: Optional[str] = Field(None, description="Physical delivery address")
    mfa_authenticated: bool = Field(default=False, description="Whether 3DS/2FA was verified")
    session_id: Optional[str] = Field(None, description="Checkout session identifier")
    user_agent: Optional[str] = Field(None, description="User Agent string")


class CarrierProof(BaseModel):
    carrier_name: Optional[str] = Field(None, description="Logistics partner name")
    tracking_number: Optional[str] = Field(None, description="Shipment tracking number")
    delivered_status: bool = Field(default=False, description="True if marked delivered")
    delivery_date: Optional[str] = Field(None, description="Timestamp of physical delivery")
    recipient_signature_present: bool = Field(default=False, description="Signature on delivery proof")
    gps_latitude: Optional[float] = Field(None, description="Delivery GPS latitude")
    gps_longitude: Optional[float] = Field(None, description="Delivery GPS longitude")
    verified_gps: bool = Field(default=False, description="GPS verified within 50m radius of shipping address")


class DigitalFulfillmentProof(BaseModel):
    service_type: str = Field(default="saas_subscription", description="saas_subscription | digital_download | api_service")
    access_logs_verified: bool = Field(default=False, description="Server access logs showing user consumption")
    download_timestamp: Optional[str] = Field(None, description="ISO timestamp of digital asset access/download")
    user_account_active: bool = Field(default=False, description="Whether user account remained active post-purchase")
    ip_subnet_matched: bool = Field(default=False, description="Whether customer IP subnet matches login session")
    license_key: Optional[str] = Field(None, description="Software license key / access token")


class HistoricalTransaction(BaseModel):
    transaction_id: str = Field(..., description="Historical transaction ID")
    payment_id: str = Field(..., description="Razorpay historical payment ID")
    amount_inr: float = Field(..., description="Historical transaction amount in INR")
    days_ago: int = Field(..., description="Calendar days prior to the dispute creation")
    card_last4: str = Field(default="4242", description="Last 4 digits of the card")
    card_network: str = Field(default="visa", description="visa | mastercard | rupay | amex")
    ip_address: Optional[str] = Field(None, description="IP recorded during historical order")
    device_id: Optional[str] = Field(None, description="Device fingerprint recorded during historical order")
    user_id: Optional[str] = Field(None, description="User ID associated with historical order")
    shipping_address: Optional[str] = Field(None, description="Shipping address for historical order")
    undisputed: bool = Field(default=True, description="Must be true for CE 3.0 / FPT qualification")


class RazorpayDisputeWebhook(BaseModel):
    """
    Pydantic v2 schema for incoming Razorpay payment.dispute.created webhooks.
    """
    event: str = Field(default="payment.dispute.created", description="Webhook event name")
    dispute_id: str = Field(..., description="Unique Razorpay dispute ID, e.g. disp_123456")
    payment_id: str = Field(..., description="Razorpay payment ID, e.g. pay_123456")
    amount: Optional[float] = Field(None, description="Disputed amount in INR or paise")
    amount_inr: Optional[float] = Field(None, description="Disputed amount in INR")
    currency: str = Field(default="INR", description="Currency code")
    card_network: str = Field(default="visa", description="visa | mastercard | rupay | amex")
    reason_code: str = Field(default="10.4", description="Dispute reason code (e.g. 10.4, 4837)")
    service_type: str = Field(default="physical", description="physical | digital_saas")
    status: str = Field(default="open", description="Dispute status: open | under_review | lost | won")
    due_by: Optional[int] = Field(None, description="Unix timestamp deadline for evidence submission")
    dispute_date: Optional[str] = None
    telemetry: Optional[CustomerTelemetry] = None
    carrier_proof: Optional[CarrierProof] = None
    digital_proof: Optional[DigitalFulfillmentProof] = None
    historical_transactions: List[HistoricalTransaction] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_amounts_and_telemetry(cls, values: Any) -> Any:
        if isinstance(values, dict):
            # Support standard nested Razorpay webhook structure:
            # {"event": "...", "payload": {"dispute": {"entity": {...}}}}
            if "payload" in values and isinstance(values.get("payload"), dict):
                dispute_wrapper = values["payload"].get("dispute", {})
                entity = dispute_wrapper.get("entity", {}) if isinstance(dispute_wrapper, dict) else {}
                if isinstance(entity, dict) and entity:
                    if "dispute_id" not in values:
                        values["dispute_id"] = entity.get("id") or entity.get("dispute_id")
                    if "payment_id" not in values:
                        values["payment_id"] = entity.get("payment_id")
                    if "amount" not in values and "amount" in entity:
                        raw_amt = float(entity["amount"])
                        values["amount"] = raw_amt
                        if "amount_inr" not in values:
                            # Razorpay amounts are in paise (e.g. 250000 paise = 2500 INR)
                            values["amount_inr"] = raw_amt / 100.0 if raw_amt >= 100 else raw_amt
                    if "currency" not in values and "currency" in entity:
                        values["currency"] = entity.get("currency", "INR")
                    if "reason_code" not in values and "reason_code" in entity:
                        values["reason_code"] = entity.get("reason_code", "10.4")
                    if "status" not in values and "status" in entity:
                        values["status"] = entity.get("status", "open")
                    if "due_by" not in values and "due_by" in entity:
                        values["due_by"] = entity.get("due_by")

            # Resolve amount vs amount_inr
            if "amount_inr" not in values or values.get("amount_inr") is None:
                amt = values.get("amount", 0.0)
                values["amount_inr"] = float(amt) if amt else 1000.0
            if "amount" not in values or values.get("amount") is None:
                values["amount"] = values.get("amount_inr", 1000.0)
            
            # NOTE: Never fabricate telemetry if absent; keep None to avoid polluting comparisons
        return values


# Alias for backward compatibility
DisputePayload = RazorpayDisputeWebhook


class RuleEvaluationResult(BaseModel):
    network: str
    reason_code: str
    ce30_compliant: bool = False
    fpt_compliant: bool = False
    qualifying_orders_count: int = 0
    matched_identifiers: List[str] = Field(default_factory=list)
    ip_or_device_matched: bool = False
    carrier_verified: bool = False
    digital_verified: bool = False
    gps_verified: bool = False
    mfa_verified: bool = False
    confidence_score: float = 0.0
    route_decision: str = "ROUTE_TO_HITL_QUEUE"  # "AUTO_DISPATCH", "ROUTE_TO_HITL_QUEUE", or "AUTO_ACCEPT_OR_REFUND"
    diagnostic_gaps: List[str] = Field(default_factory=list)
    score_breakdown: Dict[str, float] = Field(default_factory=dict)
    
    # Evidence Semantics & Central Model
    evidence_statuses: Dict[str, EvidenceStatus] = Field(default_factory=dict)
    evidence_items: List[EvidenceItem] = Field(default_factory=list)
    contradictions: List[EvidenceContradiction] = Field(default_factory=list)
    
    # Economic Expected Value Engine Fields (canonical: estimated_win_probability)
    estimated_win_probability: float = 0.0
    p_win: float = 0.0  # deprecated compatibility alias
    expected_value_inr: float = 0.0
    issuer_fee_inr: float = 1500.0
    operational_cost_inr: float = 40.0
    economic_decision: str = "ROUTE_TO_HITL_QUEUE"
    # Rebuttal Fields
    rebuttal_letter: Optional[Dict[str, Any]] = None
    evidence_category: str = "FRAUD_CE30_FPT"


class DecisionExplanation(BaseModel):
    summary: str
    top_positive_factors: List[str] = Field(default_factory=list)
    top_negative_factors: List[str] = Field(default_factory=list)
    confidence_breakdown: Dict[str, float] = Field(default_factory=dict)
    rule_applied: str = ""
    estimated_win_probability: float = 0.0
    win_probability: float = 0.0  # deprecated alias
    expected_value_inr: float = 0.0
    recommendation: str = ""
    ai_risk_assessment: str = ""
    ai_recommended_action: str = ""
    ai_verifier_status: str = ""
    safety_gate_alignment: str = ""


class Dossier(BaseModel):
    dispute_id: str
    payment_id: str
    amount_inr: float
    card_network: str
    reason_code: str
    confidence_score: float
    decision: str
    evaluation: RuleEvaluationResult
    sealed_hash: str
    timestamp: str
    telemetry: Optional[CustomerTelemetry] = None
    carrier_proof: Optional[CarrierProof] = None
    digital_proof: Optional[DigitalFulfillmentProof] = None
    historical_count: int = 0
    summary: str
    
    # Central Evidence Items & Semantics
    evidence_items: List[EvidenceItem] = Field(default_factory=list)
    evidence_statuses: Dict[str, EvidenceStatus] = Field(default_factory=dict)
    contradictions: List[EvidenceContradiction] = Field(default_factory=list)

    # Probability & Economic Fields
    estimated_win_probability: Optional[float] = None
    p_win: Optional[float] = None  # deprecated compatibility alias
    win_probability: Optional[float] = None  # deprecated compatibility alias
    expected_value: Optional[float] = None
    expected_value_inr: Optional[float] = None  # deprecated compatibility alias
    ev_breakdown: Optional[Dict[str, Any]] = None

    # Rebuttal & Intelligence
    rebuttal_letter: Optional[Dict[str, Any]] = None
    payment_authentication: Optional[str] = None
    delivery_proof: Optional[Dict[str, Any]] = None
    gps_verification: Optional[Dict[str, Any]] = None
    mfa_verification: bool = False
    ip_address: Optional[str] = None
    device_info: Optional[Dict[str, Any]] = None
    customer_history_summary: Optional[Dict[str, Any]] = None
    digital_access_logs: Optional[Dict[str, Any]] = None

    # Explainable AI, Verifier & Safety Gate
    decision_explanation: Optional[DecisionExplanation] = None
    assigned_to: Optional[str] = None
    due_by: Optional[int] = None
    priority_score: float = 0.0
    urgency: str = "normal"  # critical | urgent | normal
    priority_factors: Dict[str, float] = Field(default_factory=dict)
    ai_investigation: Optional[Dict[str, Any]] = None
    ai_verification: Optional[Dict[str, Any]] = None
    safety_gate: Optional[Dict[str, Any]] = None
    failure_provenance: Optional[Dict[str, Any]] = None



class DisputeSummary(BaseModel):
    dispute_id: str
    payment_id: str
    amount_inr: float
    card_network: str
    reason_code: str
    confidence_score: float
    decision: str
    timestamp: str
    sealed_hash: str
    estimated_win_probability: Optional[float] = None
    p_win: Optional[float] = None
    win_probability: Optional[float] = None
    expected_value: Optional[float] = None
    expected_value_inr: Optional[float] = None
    assigned_to: Optional[str] = None
    due_by: Optional[int] = None
    priority_score: float = 0.0
    urgency: str = "normal"
    has_contradiction: bool = False
