"""
SentinelDispute - Win Probability Estimators.

Separates raw telemetry/reasoning confidence scores from win probability estimates P(win | x).
Provides:
  1. BaseWinProbabilityEstimator (Abstract interface)
  2. HeuristicBaselineEstimator (Explicitly labeled heuristic baseline for buildathon/early production)
  3. PlattScalingCalibratedEstimator (Pluggable interface for future historical-outcome trained models)
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field


class ProbabilityEstimate(BaseModel):
    """
    Structured outcome of probability estimation.
    Explicitly tracks calibration method and notes to prevent mistaking heuristic scores for true posteriors.
    """
    p_win: float = Field(..., ge=0.0, le=1.0, description="Estimated probability of representment success")
    method: str = Field(..., description="Estimation technique: 'heuristic_baseline' | 'platt_calibrated' | 'isotonic'")
    is_calibrated: bool = Field(default=False, description="True ONLY if fitted against empirical historical dispute outcomes")
    features_used: Dict[str, Any] = Field(default_factory=dict, description="Feature inputs used in deduction")
    calibration_notes: str = Field(..., description="Methodological disclaimer or provenance notes")


class BaseWinProbabilityEstimator(ABC):
    """Abstract interface for dispute win probability estimators."""

    @abstractmethod
    def estimate(
        self,
        confidence_score: float,
        ce30_compliant: bool = False,
        fpt_compliant: bool = False,
        issuer_adjustment: float = 0.0,
        extra_features: Optional[Dict[str, Any]] = None
    ) -> ProbabilityEstimate:
        """Computes estimated P(win | x) for given dispute features."""
        pass


class HeuristicBaselineEstimator(BaseWinProbabilityEstimator):
    """
    Deterministic Piecewise Heuristic Baseline.
    Maps evidence telemetry score [0, 100] and network compliance flags to estimated win rate.
    
    IMPORTANT NOTICE:
    This is an expert-curated HEURISTIC BASELINE, NOT an empirically calibrated ML model.
    True statistical calibration (e.g. Platt scaling, isotonic regression) strictly requires
    an empirical dataset of historical merchant dispute outcomes (settled wins/losses).
    """

    def estimate(
        self,
        confidence_score: float,
        ce30_compliant: bool = False,
        fpt_compliant: bool = False,
        issuer_adjustment: float = 0.0,
        extra_features: Optional[Dict[str, Any]] = None
    ) -> ProbabilityEstimate:
        score = max(0.0, min(100.0, float(confidence_score)))

        if (ce30_compliant or fpt_compliant) and (score >= 85.0):
            # Network liability shift threshold (Visa CE 3.0 or Mastercard FPT)
            base_p = 0.70 + (0.28 * ((score - 85.0) / 15.0 if score > 85.0 else 0.0))
        elif score >= 85.0:
            base_p = 0.70 + (0.25 * ((score - 85.0) / 15.0))
        elif score >= 50.0:
            base_p = 0.40 + (0.30 * ((score - 50.0) / 35.0))
        else:
            base_p = max(0.05, 0.10 + (0.30 * (score / 50.0)))

        # Apply issuer intelligence delta (clamped to [0.01, 0.99])
        adjusted_p = max(0.01, min(0.99, base_p + issuer_adjustment))
        p_rounded = round(adjusted_p, 4)

        return ProbabilityEstimate(
            p_win=p_rounded,
            method="heuristic_baseline",
            is_calibrated=False,
            features_used={
                "confidence_score": score,
                "ce30_compliant": ce30_compliant,
                "fpt_compliant": fpt_compliant,
                "issuer_adjustment": issuer_adjustment
            },
            calibration_notes=(
                "Heuristic baseline: piecewise linear estimation. "
                "Requires real historical dispute resolution outcomes for empirical probability calibration."
            )
        )


class PlattScalingCalibratedEstimator(BaseWinProbabilityEstimator):
    """
    Pluggable Calibrated Estimator interface.
    Applies logistic sigmoid calibration over standardized evidence features:
      z = w0 + w_score * normalized_score + w_ce30 * ce30 + w_fpt * fpt + w_iss * issuer_adj
      P(win | x) = 1 / (1 + exp(-z))
    
    If weights are not supplied, raises ValueError to prevent manufacturing ungrounded predictions.
    """

    def __init__(self, weights: Optional[Dict[str, float]] = None, intercept: Optional[float] = None):
        self.weights = weights
        self.intercept = intercept

    @property
    def is_fitted(self) -> bool:
        return self.weights is not None and self.intercept is not None

    def estimate(
        self,
        confidence_score: float,
        ce30_compliant: bool = False,
        fpt_compliant: bool = False,
        issuer_adjustment: float = 0.0,
        extra_features: Optional[Dict[str, Any]] = None
    ) -> ProbabilityEstimate:
        if not self.is_fitted:
            raise ValueError(
                "PlattScalingCalibratedEstimator has not been fitted with empirical historical outcome weights. "
                "To estimate win probability without historical data, use HeuristicBaselineEstimator."
            )

        import math
        norm_score = float(confidence_score) / 100.0
        z = (
            self.intercept
            + self.weights.get("score", 0.0) * norm_score
            + self.weights.get("ce30", 0.0) * (1.0 if ce30_compliant else 0.0)
            + self.weights.get("fpt", 0.0) * (1.0 if fpt_compliant else 0.0)
            + self.weights.get("issuer_adj", 0.0) * float(issuer_adjustment)
        )

        p = 1.0 / (1.0 + math.exp(-z))
        p_clamped = max(0.01, min(0.99, p))

        return ProbabilityEstimate(
            p_win=round(p_clamped, 4),
            method="platt_calibrated",
            is_calibrated=True,
            features_used={
                "confidence_score": confidence_score,
                "ce30_compliant": ce30_compliant,
                "fpt_compliant": fpt_compliant,
                "issuer_adjustment": issuer_adjustment
            },
            calibration_notes="Calibrated via empirical Platt logistic regression against historical outcomes."
        )


_DEFAULT_ESTIMATOR = HeuristicBaselineEstimator()


def get_win_probability_estimator(estimator_name: Optional[str] = None) -> BaseWinProbabilityEstimator:
    """Factory returning configured win probability estimator."""
    if estimator_name == "platt":
        return PlattScalingCalibratedEstimator()
    return _DEFAULT_ESTIMATOR
