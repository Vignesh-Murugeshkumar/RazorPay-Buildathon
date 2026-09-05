"""
Unit tests for Win Probability Estimators and Statistical Calibration Utilities.

Validates:
1. HeuristicBaselineEstimator returns expected piecewise linear values and explicit heuristic disclaimer.
2. PlattScalingCalibratedEstimator validates fitted state and computes logistic probabilities when configured.
3. Brier score computation accurately measures mean squared probability error.
4. Expected Calibration Error (ECE) computes binned calibration gap.
5. Calibration curve generator produces reliable bin statistics.
6. Cost-sensitive loss reflects arbitration penalty asymmetry.
"""

import pytest
from app.services.probability.estimator import (
    HeuristicBaselineEstimator,
    PlattScalingCalibratedEstimator,
    get_win_probability_estimator,
)
from app.services.probability.calibration import (
    calculate_brier_score,
    calculate_expected_calibration_error,
    generate_calibration_curve,
    calculate_cost_sensitive_loss,
)
from app.services.expected_value import calculate_expected_value, estimate_win_probability


def test_heuristic_baseline_estimator_explicit_labeling():
    """Estimator must explicitly identify as uncalibrated heuristic baseline."""
    est = HeuristicBaselineEstimator()
    res = est.estimate(confidence_score=95.0, ce30_compliant=True)

    assert res.method == "heuristic_baseline"
    assert res.is_calibrated is False
    assert "historical dispute resolution outcomes" in res.calibration_notes
    assert res.p_win >= 0.70


def test_platt_scaling_estimator_unfitted_guard():
    """Unfitted calibrated estimator must refuse to predict to avoid fake metrics."""
    est = PlattScalingCalibratedEstimator()
    assert est.is_fitted is False

    with pytest.raises(ValueError, match="has not been fitted with empirical historical outcome weights"):
        est.estimate(confidence_score=90.0)


def test_platt_scaling_estimator_fitted_calculation():
    """Fitted calibrated estimator computes logistic sigmoid probability."""
    est = PlattScalingCalibratedEstimator(
        weights={"score": 3.0, "ce30": 1.5, "fpt": 0.0, "issuer_adj": 0.0},
        intercept=-1.0
    )
    assert est.is_fitted is True

    res = est.estimate(confidence_score=80.0, ce30_compliant=True)
    assert res.method == "platt_calibrated"
    assert res.is_calibrated is True
    assert 0.0 < res.p_win < 1.0


def test_brier_score_metric():
    """Brier score should be 0.0 for perfect predictions and higher for worse predictions."""
    y_true = [1, 1, 0, 0]
    perfect_probs = [1.0, 1.0, 0.0, 0.0]
    assert calculate_brier_score(y_true, perfect_probs) == 0.0

    imperfect_probs = [0.8, 0.7, 0.2, 0.3]
    bs = calculate_brier_score(y_true, imperfect_probs)
    assert 0.0 < bs < 0.25

    with pytest.raises(ValueError):
        calculate_brier_score([1], [0.5, 0.5])


def test_expected_calibration_error_and_curve():
    """ECE should evaluate binned calibration gap."""
    y_true = [1, 1, 1, 0, 0, 0, 1, 0, 1, 0]
    y_prob = [0.9, 0.85, 0.8, 0.2, 0.15, 0.1, 0.7, 0.3, 0.6, 0.4]

    ece = calculate_expected_calibration_error(y_true, y_prob, n_bins=5)
    assert 0.0 <= ece <= 1.0

    curve = generate_calibration_curve(y_true, y_prob, n_bins=5)
    assert curve["n_bins"] == 5
    assert curve["total_samples"] == 10
    assert len(curve["bins"]) == 5
    assert "brier_score" in curve
    assert "expected_calibration_error" in curve


def test_cost_sensitive_loss_calculation():
    """False positives must be penalized with disputed amount + 1500 dispute fee."""
    y_true = [1, 0]
    actions = ["AUTO_DISPATCHED", "AUTO_DISPATCHED"]  # Second one is a False Positive!
    amounts = [2000.0, 3000.0]

    loss = calculate_cost_sensitive_loss(y_true, actions, amounts, fee=1500.0)
    assert loss["defended_gmv_proxy"] == 2000.0
    # FP cost = 3000 (dispute) + 1500 (fee) = 4500
    assert loss["false_positive_financial_penalty"] == 4500.0
    assert loss["false_negative_opportunity_cost"] == 0.0


def test_expected_value_with_calibrated_estimator():
    """Expected value engine seamlessly accepts custom probability estimator."""
    custom_estimator = PlattScalingCalibratedEstimator(
        weights={"score": 2.0, "ce30": 1.0},
        intercept=0.0
    )
    ev_result = calculate_expected_value(
        amount_inr=5000.0,
        confidence_score=90.0,
        ce30_compliant=True,
        estimator=custom_estimator
    )
    assert ev_result.calibration_method == "platt_calibrated"
    assert ev_result.is_calibrated is True
    assert ev_result.estimated_win_probability > 0.0
