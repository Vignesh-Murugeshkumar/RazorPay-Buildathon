from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field


class GatewayDisputeEvent(BaseModel):
    gateway: str
    dispute_id: str
    payment_id: str
    amount: float
    currency: str
    reason: str
    status: str
    network: Optional[str] = "visa"
    raw_event: Dict[str, Any] = Field(default_factory=dict)


class BaseGatewayAdapter(ABC):
    @abstractmethod
    def parse_webhook(self, raw_payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> GatewayDisputeEvent:
        pass

    @abstractmethod
    def submit_evidence(self, dispute_id: str, dossier_payload: Dict[str, Any]) -> Dict[str, Any]:
        pass
