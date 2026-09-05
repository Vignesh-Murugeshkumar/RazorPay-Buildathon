"""
SentinelDispute - Probability Calibration Assessment & Metric Utilities.

Provides mathematical tooling to evaluate whether estimated probabilities P(win | x)
reflect true empirical likelihoods of dispute representment success.
Computes:
  - Brier Score (Mean Squared Probability Error)
  - Expected Calibration Error (ECE)
  - Calibration Curve (Reliability Diagram Data)
  - Cost-Sensitive Financial Loss Analysis
"""

from typing import List, Dict, Any, Tuple, Optional


def calculate_brier_score(y_true: List[int], y_prob: List[float]) -> float:
    """
    Computes the Brier score: mean squared difference between predicted probability and actual binary outcome.
    BS = (1/N) * sum((p_i - y_i)^2)
    Lower score indicates better calibrated and more accurate probabilities (0.0 is perfect, 0.25 is random guessing).
    """
    if not y_true or not y_prob or len(y_true) != len(y_prob):
        raise ValueError("y_true and y_prob must be non-empty lists of identical length.")

    n = len(y_true)
    squared_errors = [(float(p) - float(y)) ** 2 for y, p in zip(y_true, y_prob)]
    return round(sum(squared_errors) / float(n), 4)


def calculate_expected_calibration_error(
    y_true: List[int],
    y_prob: List[float],
    n_bins: int = 10
) -> float:
    """
    Calculates Expected Calibration Error (ECE):
    ECE = sum_{m=1}^M (|B_m| / N) * |acc(B_m) - conf(B_m)|
    Measures the weighted average absolute difference between predicted confidence and observed empirical accuracy.
    """
    if not y_true or not y_prob or len(y_true) != len(y_prob):
        raise ValueError("y_true and y_prob must be non-empty lists of identical length.")

    n = len(y_true)
    bins: Dict[int, List[Tuple[int, float]]] = {i: [] for i in range(n_bins)}

    for y, p in zip(y_true, y_prob):
        bin_idx = min(int(p * n_bins), n_bins - 1)
        bins[bin_idx].append((y, p))

    ece = 0.0
    for bin_idx, items in bins.items():
        if not items:
            continue
        bin_size = len(items)
        avg_acc = sum(y for y, _ in items) / float(bin_size)
        avg_conf = sum(p for _, p in items) / float(bin_size)
        ece += (bin_size / float(n)) * abs(avg_acc - avg_conf)

    return round(ece, 4)


def generate_calibration_curve(
    y_true: List[int],
    y_prob: List[float],
    n_bins: int = 10
) -> Dict[str, Any]:
    """
    Generates reliability diagram data points (observed accuracy vs mean predicted confidence across bins).
    """
    if not y_true or not y_prob or len(y_true) != len(y_prob):
        raise ValueError("y_true and y_prob must be non-empty lists of identical length.")

    bins: Dict[int, List[Tuple[int, float]]] = {i: [] for i in range(n_bins)}

    for y, p in zip(y_true, y_prob):
        bin_idx = min(int(p * n_bins), n_bins - 1)
        bins[bin_idx].append((y, p))

    bin_data = []
    for i in range(n_bins):
        items = bins[i]
        bin_lower = i / float(n_bins)
        bin_upper = (i + 1) / float(n_bins)
        if items:
            mean_prob = round(sum(p for _, p in items) / float(len(items)), 4)
            empirical_accuracy = round(sum(y for y, _ in items) / float(len(items)), 4)
            sample_count = len(items)
        else:
            mean_prob = round((bin_lower + bin_upper) / 2.0, 4)
            empirical_accuracy = None
            sample_count = 0

        bin_data.append({
            "bin_index": i,
            "range": [round(bin_lower, 2), round(bin_upper, 2)],
            "mean_confidence": mean_prob,
            "empirical_accuracy": empirical_accuracy,
            "sample_count": sample_count
        })

    return {
        "n_bins": n_bins,
        "total_samples": len(y_true),
        "bins": bin_data,
        "brier_score": calculate_brier_score(y_true, y_prob),
        "expected_calibration_error": calculate_expected_calibration_error(y_true, y_prob, n_bins)
    }


def calculate_cost_sensitive_loss(
    y_true: List[int],
    actions: List[str],
    amounts: List[float],
    fee: float = 1500.0
) -> Dict[str, float]:
    """
    Computes asymmetric financial loss resulting from dispute decisions:
      - False Positive (Auto-dispatched non-defensible): Loss = Disputed Amount + Arbitration Fee
      - False Negative (Auto-accepted defensible): Loss = Disputed Amount (opportunity cost)
      - True Positive (Auto-dispatched defensible): Defended Revenue = Disputed Amount
    """
    if len(y_true) != len(actions) or len(actions) != len(amounts):
        raise ValueError("Inputs must have identical length.")

    fp_cost = 0.0
    fn_cost = 0.0
    defended_gmv = 0.0

    for yt, act, amt in zip(y_true, actions, amounts):
        is_auto = act in ("AUTO_DISPATCHED", "AUTO_SUBMIT_REPRESENTMENT")
        if is_auto and yt == 0:
            # False positive: lost amount + non-refundable penalty fee
            fp_cost += (amt + fee)
        elif not is_auto and yt == 1:
            # False negative: forfeited defensible amount
            fn_cost += amt
        elif is_auto and yt == 1:
            # True positive: protected GMV
            defended_gmv += amt

    return {
        "false_positive_financial_penalty": round(fp_cost, 2),
        "false_negative_opportunity_cost": round(fn_cost, 2),
        "defended_gmv_proxy": round(defended_gmv, 2),
        "net_loss": round(fp_cost + fn_cost, 2)
    }


def fit_platt_scaling_model(
    outcomes: List[Dict[str, Any]],
    min_samples: int = 50,
    learning_rate: float = 0.05,
    max_epochs: int = 250,
    l2_reg: float = 0.01
) -> Tuple[Optional[Any], Dict[str, Any]]:
    """
    Fits an empirical Platt Scaling (logistic regression) model on historical dispute resolution outcomes.
    
    Requires at least `min_samples` (default: 50) resolved outcomes to prevent overfitting
    and ungrounded parameter estimation.
    
    Features extracted per record:
      - score: normalized confidence_score [0.0, 1.0]
      - ce30: 1.0 if CE 3.0 qualifying else 0.0
      - fpt: 1.0 if Mastercard FPT qualifying else 0.0
      - issuer_adj: issuer intelligence propensity adjustment [-0.5, 0.5]
    
    Target:
      - y = 1 if outcome.lower() in ("won", "dispute.won") else 0
    
    Returns:
      (fitted_estimator_or_None, diagnostic_metadata)
    """
    import math
    from app.services.probability.estimator import PlattScalingCalibratedEstimator

    n_samples = len(outcomes)
    if n_samples < min_samples:
        return None, {
            "status": "insufficient_data",
            "samples_provided": n_samples,
            "min_required_samples": min_samples,
            "is_fitted": False,
            "message": (
                f"Empirical probability calibration requires at least {min_samples} resolved dispute outcomes "
                f"(received {n_samples}). Retaining HeuristicBaselineEstimator to prevent statistical overfitting."
            )
        }

    # Extract dataset matrices
    X = []
    y = []
    for item in outcomes:
        outcome_str = str(item.get("outcome", "")).lower()
        target = 1 if outcome_str in ("won", "dispute.won", "payment.dispute.won", "1", "true") else 0

        score = float(item.get("confidence_score", 50.0)) / 100.0
        ce30 = 1.0 if item.get("ce30_compliant") or "ce30" in str(item.get("evidence_types_used", "")) else 0.0
        fpt = 1.0 if item.get("fpt_compliant") or "fpt" in str(item.get("evidence_types_used", "")) else 0.0
        iss_adj = float(item.get("issuer_adjustment", 0.0))

        X.append([score, ce30, fpt, iss_adj])
        y.append(target)

    # Initialize weights: [w_score, w_ce30, w_fpt, w_iss] and w0 (intercept)
    w = [0.5, 0.5, 0.5, 0.1]
    w0 = 0.0

    # L2-regularized logistic regression via gradient descent
    final_loss = 0.0
    for epoch in range(max_epochs):
        grad_w = [0.0, 0.0, 0.0, 0.0]
        grad_w0 = 0.0
        total_loss = 0.0

        for xi, yi in zip(X, y):
            z = w0 + sum(wj * xij for wj, xij in zip(w, xi))
            # Sigmoid with numerical stability guard
            z_clipped = max(-20.0, min(20.0, z))
            p = 1.0 / (1.0 + math.exp(-z_clipped))

            # Cross-entropy loss
            p_safe = max(1e-7, min(1.0 - 1e-7, p))
            loss = -(yi * math.log(p_safe) + (1 - yi) * math.log(1.0 - p_safe))
            total_loss += loss

            error = p - yi
            grad_w0 += error
            for j in range(4):
                grad_w[j] += error * xi[j]

        # Apply L2 regularization to weights (excluding intercept)
        grad_w0 /= n_samples
        for j in range(4):
            grad_w[j] = (grad_w[j] / n_samples) + (l2_reg * w[j])
            w[j] -= learning_rate * grad_w[j]
        w0 -= learning_rate * grad_w0
        final_loss = total_loss / n_samples

    weights_dict = {
        "score": round(w[0], 4),
        "ce30": round(w[1], 4),
        "fpt": round(w[2], 4),
        "issuer_adj": round(w[3], 4)
    }
    intercept_val = round(w0, 4)

    estimator = PlattScalingCalibratedEstimator(weights=weights_dict, intercept=intercept_val)

    # Calculate post-training calibration metrics
    y_pred_probs = []
    for xi in X:
        z = intercept_val + sum(w_val * xij for w_val, xij in zip(w, xi))
        p = 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, z))))
        y_pred_probs.append(round(p, 4))

    brier = calculate_brier_score(y, y_pred_probs)
    ece = calculate_expected_calibration_error(y, y_pred_probs)

    diagnostics = {
        "status": "calibrated",
        "samples_trained": n_samples,
        "epochs": max_epochs,
        "final_loss": round(final_loss, 4),
        "brier_score": brier,
        "expected_calibration_error": ece,
        "weights": weights_dict,
        "intercept": intercept_val,
        "is_fitted": True,
        "message": f"Successfully calibrated PlattScalingCalibratedEstimator on {n_samples} historical outcomes."
    }

    return estimator, diagnostics
