from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, model_validator
from datetime import datetime


class CustomerTelemetry(BaseModel):
    ip_address: str = Field(..., description="IPv4 or IPv6 of the customer at checkout")
    device_id: str = Field(..., description="Persistent device fingerprint or UUID")
    user_id: str = Field(..., description="Customer account ID or username")
    shipping_address: str = Field(..., description="Physical delivery address")
    mfa_authenticated: bool = Field(default=False, description="Whether 3DS/2FA was verified")
    session_id: Optional[str] = Field(None, description="Checkout session identifier")
    user_agent: Optional[str] = Field(None, description="User Agent string")


class CarrierProof(BaseModel):
    carrier_name: str = Field(default="BlueDart", description="Logistics partner name")
    tracking_number: str = Field(..., description="Shipment tracking number")
    delivered_status: bool = Field(default=True, description="True if marked delivered")
    delivery_date: Optional[str] = Field(None, description="Timestamp of physical delivery")
    recipient_signature_present: bool = Field(default=True, description="Signature on delivery proof")
    gps_latitude: Optional[float] = Field(None, description="Delivery GPS latitude")
    gps_longitude: Optional[float] = Field(None, description="Delivery GPS longitude")
    verified_gps: bool = Field(default=False, description="GPS verified within 50m radius of shipping address")


class DigitalFulfillmentProof(BaseModel):
    service_type: str = Field(default="saas_subscription", description="saas_subscription | digital_download | api_service")
    access_logs_verified: bool = Field(default=True, description="Server access logs showing user consumption")
    download_timestamp: Optional[str] = Field(None, description="ISO timestamp of digital asset access/download")
    user_account_active: bool = Field(default=True, description="Whether user account remained active post-purchase")
    ip_subnet_matched: bool = Field(default=False, description="Whether customer IP subnet matches login session")
    license_key: Optional[str] = Field(None, description="Software license key / access token")


class HistoricalTransaction(BaseModel):
    transaction_id: str = Field(..., description="Historical transaction ID")
    payment_id: str = Field(..., description="Razorpay historical payment ID")
    amount_inr: float = Field(..., description="Historical transaction amount in INR")
    days_ago: int = Field(..., description="Calendar days prior to the dispute creation")
    card_last4: str = Field(default="4242", description="Last 4 digits of the card")
    card_network: str = Field(default="visa", description="visa | mastercard | rupay | amex")
    ip_address: str = Field(..., description="IP recorded during historical order")
    device_id: str = Field(..., description="Device fingerprint recorded during historical order")
    user_id: str = Field(..., description="User ID associated with historical order")
    shipping_address: str = Field(..., description="Shipping address for historical order")
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
            # Resolve amount vs amount_inr
            if "amount_inr" not in values or values.get("amount_inr") is None:
                amt = values.get("amount", 0.0)
                # If amount > 10000 and looks like paise, support paise conversion if needed
                values["amount_inr"] = float(amt) if amt else 1000.0
            if "amount" not in values or values.get("amount") is None:
                values["amount"] = values.get("amount_inr", 1000.0)
            
            # Default telemetry if not provided for generic webhook testing
            if "telemetry" not in values or values.get("telemetry") is None:
                values["telemetry"] = {
                    "ip_address": "127.0.0.1",
                    "device_id": "generic_device_fp",
                    "user_id": "generic_user",
                    "shipping_address": "General Delivery, India",
                    "mfa_authenticated": False
                }
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
    # Economic Expected Value Engine Fields
    p_win: float = 0.0
    expected_value_inr: float = 0.0
    issuer_fee_inr: float = 1500.0
    operational_cost_inr: float = 40.0
    economic_decision: str = "ROUTE_TO_HITL_QUEUE"
    # Multimodal RAG Non-Fraud Fields
    rebuttal_letter: Optional[Dict[str, Any]] = None
    evidence_category: str = "FRAUD_CE30_FPT"  # "FRAUD_CE30_FPT" | "SERVICE_DISPUTE_RAG" | "CANCELLATION_RAG"


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
    telemetry: CustomerTelemetry
    carrier_proof: Optional[CarrierProof] = None
    digital_proof: Optional[DigitalFulfillmentProof] = None
    historical_count: int = 0
    summary: str
    expected_value_inr: Optional[float] = None
    p_win: Optional[float] = None
    rebuttal_letter: Optional[Dict[str, Any]] = None


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
    expected_value_inr: Optional[float] = None
    p_win: Optional[float] = None
