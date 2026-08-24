from typing import Optional
from pydantic import BaseModel, Field


class RemediationEvidencePayload(BaseModel):
    """
    Evidence remediation submission schema for Human-in-the-Loop (HITL) queue.
    Allows risk analysts to supply missing carrier proof, GPS telemetry, MFA verification, or digital access logs.
    """
    analyst_id: str = Field(default="ANALYST_01", description="ID or username of the reviewing risk analyst")
    analyst_notes: Optional[str] = Field(None, description="Remediation notes / commentary")
    
    # Carrier Proof updates
    carrier_name: Optional[str] = Field(default="BlueDart", description="Carrier name")
    tracking_number: Optional[str] = Field(None, description="Shipment tracking number")
    delivered_status: Optional[bool] = Field(None, description="Mark as verified delivered")
    recipient_signature_present: Optional[bool] = Field(None, description="Proof of recipient signature")
    gps_latitude: Optional[float] = Field(None, description="Delivery GPS latitude")
    gps_longitude: Optional[float] = Field(None, description="Delivery GPS longitude")
    verified_gps: Optional[bool] = Field(None, description="GPS verified within 50m radius")
    
    # Telemetry updates
    mfa_authenticated: Optional[bool] = Field(None, description="3DS / 2FA verification proof")
    user_id_confirmed: Optional[str] = Field(None, description="Verified customer account ID")
    ip_address_confirmed: Optional[str] = Field(None, description="Verified IP address")
    
    # Digital / SaaS fulfillment updates
    digital_access_logs_verified: Optional[bool] = Field(None, description="SaaS server logs verified")
    digital_ip_subnet_matched: Optional[bool] = Field(None, description="IP subnet match on active login session")
