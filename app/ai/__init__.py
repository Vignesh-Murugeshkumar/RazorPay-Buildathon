"""
SentinelDispute - AI Module.

Provides AI-assisted dispute risk investigation, evidence verification,
and local policy retrieval, strictly bounded by deterministic financial safety gates.
"""

from app.ai.provider import get_ai_provider, AIProvider, MockAIProvider, OpenAIProvider
from app.ai.investigation_agent import EvidenceInvestigationAgent
from app.ai.verifier import AIEvidenceVerifier
from app.ai.policy_kb import policy_knowledge_base

__all__ = [
    "get_ai_provider",
    "AIProvider",
    "MockAIProvider",
    "OpenAIProvider",
    "EvidenceInvestigationAgent",
    "AIEvidenceVerifier",
    "policy_knowledge_base",
]
