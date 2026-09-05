"""
SentinelDispute - Win Probability Estimation & Calibration Layer.

Defines the pluggable estimator abstraction separating raw confidence scores
from mathematically calibrated probability estimates P(win | x).
"""

from app.services.probability.estimator import (
    BaseWinProbabilityEstimator,
    HeuristicBaselineEstimator,
    PlattScalingCalibratedEstimator,
    ProbabilityEstimate,
    get_win_probability_estimator,
)
from app.services.probability.calibration import (
    calculate_brier_score,
    calculate_expected_calibration_error,
    generate_calibration_curve,
    calculate_cost_sensitive_loss,
)

__all__ = [
    "BaseWinProbabilityEstimator",
    "HeuristicBaselineEstimator",
    "PlattScalingCalibratedEstimator",
    "ProbabilityEstimate",
    "get_win_probability_estimator",
    "calculate_brier_score",
    "calculate_expected_calibration_error",
    "generate_calibration_curve",
    "calculate_cost_sensitive_loss",
]
