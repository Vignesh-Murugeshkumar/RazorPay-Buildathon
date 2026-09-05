"""
SentinelDispute Domain Exception Hierarchy & Failure Provenance.

Provides strongly typed exceptions for all system boundaries:
- Webhooks & HMAC validation
- Database & persistence
- AI Provider & LLM communication
- Evidence verification & policy contracts
- Pipeline execution & workflow failure provenance
"""

import uuid
import traceback
import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class FailureProvenance(BaseModel):
    """
    Structured record documenting system failure, origin component, and safe routing action.
    Stored on dossiers and audit ledgers when fallbacks occur.
    """
    failure_id: str = Field(default_factory=lambda: f"fail_{uuid.uuid4().hex[:12]}")
    failure_type: str = Field(..., description="Exception class or category")
    component: str = Field(..., description="Originating subsystem (e.g., InvestigationAgent, AIProvider, Verifier)")
    timestamp: str = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    correlation_id: Optional[str] = Field(None, description="Request correlation identifier")
    dispute_id: Optional[str] = Field(None, description="Affected dispute ID")
    action_taken: str = Field("ROUTE_TO_HITL_QUEUE", description="Deterministic safe action executed upon failure")
    reason: str = Field(..., description="Human-readable root-cause summary")
    stack_summary: Optional[str] = Field(None, description="Sanitized top of stack trace")

    def to_audit_dict(self) -> Dict[str, Any]:
        return {
            "failure_id": self.failure_id,
            "failure_type": self.failure_type,
            "component": self.component,
            "action_taken": self.action_taken,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


class SentinelError(Exception):
    """Base exception for all SentinelDispute domain errors."""
    def __init__(self, message: str, component: str = "CORE", dispute_id: Optional[str] = None, correlation_id: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.component = component
        self.dispute_id = dispute_id
        self.correlation_id = correlation_id

    def to_provenance(self, action_taken: str = "ROUTE_TO_HITL_QUEUE") -> FailureProvenance:
        return FailureProvenance(
            failure_type=self.__class__.__name__,
            component=self.component,
            dispute_id=self.dispute_id,
            correlation_id=self.correlation_id,
            action_taken=action_taken,
            reason=self.message,
            stack_summary=traceback.format_exc(limit=3) if traceback.format_exc() != "NoneType: None\n" else None
        )


class WebhookValidationError(SentinelError):
    """Raised when incoming webhook payload signature, timestamp, or structure fails validation."""
    def __init__(self, message: str, correlation_id: Optional[str] = None):
        super().__init__(message, component="WEBHOOK_INGRESS", correlation_id=correlation_id)


class DatabaseUnavailableError(SentinelError):
    """Raised when the primary database is unreachable and fail-closed policy applies."""
    def __init__(self, message: str, dispute_id: Optional[str] = None, correlation_id: Optional[str] = None):
        super().__init__(message, component="DATABASE", dispute_id=dispute_id, correlation_id=correlation_id)


class AIProviderError(SentinelError):
    """Raised when an external AI/LLM provider fails, times out, rate limits, or returns invalid schema."""
    def __init__(self, message: str, dispute_id: Optional[str] = None, correlation_id: Optional[str] = None):
        super().__init__(message, component="AI_PROVIDER", dispute_id=dispute_id, correlation_id=correlation_id)


class EvidenceVerificationFailure(SentinelError):
    """Raised when mandatory evidence is absent or verification contracts are violated."""
    def __init__(self, message: str, dispute_id: Optional[str] = None, correlation_id: Optional[str] = None):
        super().__init__(message, component="DETERMINISTIC_VERIFIER", dispute_id=dispute_id, correlation_id=correlation_id)


class ContradictionDetectedError(SentinelError):
    """Raised when irreconcilable evidence contradictions prevent automated representment."""
    def __init__(self, message: str, dispute_id: Optional[str] = None, correlation_id: Optional[str] = None):
        super().__init__(message, component="CONTRADICTION_DETECTOR", dispute_id=dispute_id, correlation_id=correlation_id)


class PipelineExecutionError(SentinelError):
    """Raised when workflow pipeline graph encounters an unexpected internal error."""
    def __init__(self, message: str, dispute_id: Optional[str] = None, correlation_id: Optional[str] = None):
        super().__init__(message, component="DISPUTE_GRAPH", dispute_id=dispute_id, correlation_id=correlation_id)
