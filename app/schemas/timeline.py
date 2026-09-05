from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class TimelineEvent(BaseModel):
    id: Optional[int] = None
    dispute_id: str
    event_type: str = Field(..., description="WEBHOOK_RECEIVED, RULE_EVALUATION, DECISION_SEALED, ASSIGNED, etc.")
    title: str
    description: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
