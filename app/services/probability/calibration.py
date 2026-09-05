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

from typing import List, Dict, Any, Tuple


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
