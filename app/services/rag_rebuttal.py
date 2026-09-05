"""
Backward-compatibility wrapper for Rule-Constrained Rebuttal Synthesizer.
Transfers all functionality to app.services.rebuttal_synthesizer.
"""

from app.services.rebuttal_synthesizer import (
    RebuttalEvidenceClause,
    RebuttalClaim,
    NetworkRebuttalLetter,
    RebuttalLetterSynthesizer,
    rule_constrained_synthesizer,
    rebuttal_synthesizer,
)

# Compatibility alias for existing callers
rag_synthesizer = rebuttal_synthesizer

__all__ = [
    "RebuttalEvidenceClause",
    "RebuttalClaim",
    "NetworkRebuttalLetter",
    "RebuttalLetterSynthesizer",
    "rule_constrained_synthesizer",
    "rebuttal_synthesizer",
    "rag_synthesizer",
]
