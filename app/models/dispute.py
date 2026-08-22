from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class CustomerTelemetry(BaseModel):
    ip_address: str = Field(..., description="IPv4 or IPv6 of the customer at checkout")
    device_id: str = Field(..., description="Persistent device fingerprint or UUID")
    user_id: str = Field(..., description="Customer account ID or username")
    shipping_address: str = Field(..., description="Physical delivery address")
    mfa_authenticated: bool = Field(default=False, description="Whether 3DS/2FA was verified")
    session_id: Optional[str] = None
    user_agent: Optional[str] = None


class CarrierProof(BaseModel):
    carrier_name: str = Field(default="BlueDart", description="Logistics partner name")
    tracking_number: str = Field(..., description="Shipment tracking number")
    delivered_status: bool = Field(default=True, description="True if marked delivered")
    delivery_date: Optional[str] = None
    recipient_signature_present: bool = Field(default=True, description="Signature on delivery proof")
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None
    verified_gps: bool = Field(default=False, description="GPS verified within 50m of shipping address")


class HistoricalTransaction(BaseModel):
    transaction_id: str
    payment_id: str
    amount_inr: float
    days_ago: int = Field(..., description="Number of calendar days prior to the dispute")
    card_last4: str
    card_network: str = Field(default="visa")
    ip_address: str
    device_id: str
    user_id: str
    shipping_address: str
    undisputed: bool = Field(default=True, description="Must be true for CE 3.0 / FPT qualification")


class DisputePayload(BaseModel):
    event: str = Field(default="payment.dispute.created")
    dispute_id: str = Field(..., description="Unique Razorpay dispute ID, e.g. disp_123456")
    payment_id: str = Field(..., description="Razorpay payment ID, e.g. pay_123456")
    amount_inr: float = Field(..., description="Disputed amount in INR")
    currency: str = Field(default="INR")
    card_network: str = Field(default="visa", description="visa | mastercard | rupay | amex")
    reason_code: str = Field(default="10.4", description="Dispute reason code (e.g. 10.4 for Visa, 4837 for MC)")
    dispute_date: Optional[str] = None
    telemetry: CustomerTelemetry
    carrier_proof: Optional[CarrierProof] = None
    historical_transactions: List[HistoricalTransaction] = Field(default_factory=list)


class RuleEvaluationResult(BaseModel):
    network: str
    reason_code: str
    ce30_compliant: bool = False
    fpt_compliant: bool = False
    qualifying_orders_count: int = 0
    matched_identifiers: List[str] = Field(default_factory=list)
    ip_or_device_matched: bool = False
    carrier_verified: bool = False
    gps_verified: bool = False
    mfa_verified: bool = False
    confidence_score: float = 0.0
    route_decision: str = "ROUTE_TO_HITL_QUEUE"  # "AUTO_DISPATCH" or "ROUTE_TO_HITL_QUEUE"
    diagnostic_gaps: List[str] = Field(default_factory=list)
    score_breakdown: Dict[str, float] = Field(default_factory=dict)


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
    historical_count: int = 0
    summary: str


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
