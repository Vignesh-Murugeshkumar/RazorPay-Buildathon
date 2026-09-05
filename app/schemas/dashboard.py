from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field


class NetworkBreakdown(BaseModel):
    network: str
    count: int
    total_amount_inr: float
    win_rate: float = 0.0


class ReasonCodeBreakdown(BaseModel):
    reason_code: str
    count: int
    total_amount_inr: float


class DashboardSummary(BaseModel):
    total_disputes: int = 0
    total_amount_inr: float = 0.0
    recovered_amount_inr: float = 0.0
    win_rate: float = 0.0
    auto_decision_rate: float = 0.0
    avg_confidence_score: float = 0.0
    status_counts: Dict[str, int] = Field(default_factory=dict)
    decision_counts: Dict[str, int] = Field(default_factory=dict)
    network_breakdown: List[NetworkBreakdown] = Field(default_factory=list)
    reason_breakdown: List[ReasonCodeBreakdown] = Field(default_factory=list)
    hitl_pending_count: int = 0
    recent_disputes: List[Dict[str, Any]] = Field(default_factory=list)
