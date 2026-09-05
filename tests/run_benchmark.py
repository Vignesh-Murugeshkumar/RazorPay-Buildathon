"""
SentinelDispute - Comprehensive Benchmark Evaluation Suite.

Evaluates SentinelDispute on the true held-out test set (115 scenarios across categories A-P).
Computes mathematically rigorous confusion matrix (TP, FP, TN, FN), precision, recall,
F1 score, false-positive cost, GMV recovery metrics, AI grounding rate, and verifier rejection rate.
Never confuses accuracy with precision.
"""

import sys
import os
import time
import json
import argparse
from typing import List, Dict, Any

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Ensure UTF-8 output on Windows consoles
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.schemas.dispute import DisputePayload
from app.graphs.dispute_graph import execute_dispute_workflow
from app.services.ledger import ledger
from app.core.db import db


def run_benchmark(dataset_path: str = None) -> Dict[str, Any]:
    if dataset_path is None:
        dataset_path = os.path.join(os.path.dirname(__file__), "data", "held_out", "held_out_dataset.json")

    print("=" * 85)
    print("SENTINELDISPUTE: AI RISK MANAGER HELD-OUT BENCHMARK EVALUATION")
    print("=" * 85)
    print(f"Loading held-out evaluation dataset: {dataset_path}")

    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    # Clean test state for deterministic benchmark & tamper-evident chain verification
    ledger.reset_for_tests()
    db.clear_all_data()

    total_scenarios = len(dataset)
    print(f"Loaded {total_scenarios} held-out dispute scenarios across cohorts A through P.")
    print("-" * 85)

    # Initialize counters for confusion matrix
    tp = 0  # Truly defensible, correctly auto-dispatched
    fp = 0  # Not defensible / fraudulent, erroneously auto-dispatched (CRITICAL FAILURE)
    tn = 0  # Not defensible, correctly routed to HITL or Auto-Accept
    fn = 0  # Truly defensible, routed to HITL or Auto-Accept

    total_disputed_gmv = 0.0
    auto_action_gmv = 0.0
    correctly_recovered_gmv = 0.0
    incorrect_auto_action_gmv = 0.0
    false_positive_financial_cost = 0.0
    false_negative_financial_cost = 0.0

    hitl_count = 0
    auto_accept_count = 0
    auto_dispatch_count = 0

    total_ai_claims = 0
    grounded_ai_claims = 0
    verifier_rejections = 0
    hallucination_traps_intercepted = 0

    latencies = []
    category_stats = {}

    start_time = time.time()

    for idx, item in enumerate(dataset, 1):
        case_id = item["case_id"]
        cat_code = item["category_code"]
        cat_name = item["category_name"]
        is_defensible = item["is_truly_defensible"]
        payload_dict = item["payload"]
        amount = float(payload_dict.get("amount_inr", 1000.0))
        total_disputed_gmv += amount

        payload = DisputePayload.model_validate(payload_dict)

        t0 = time.time()
        dossier = execute_dispute_workflow(payload)
        lat_ms = (time.time() - t0) * 1000.0
        latencies.append(lat_ms)

        decision = dossier.decision
        score = dossier.confidence_score
        is_auto_dispatched = decision in ("AUTO_DISPATCHED", "AUTO_SUBMIT_REPRESENTMENT")

        # Track Action counts
        if is_auto_dispatched:
            auto_dispatch_count += 1
            auto_action_gmv += amount
        elif decision in ("ROUTE_TO_HITL_QUEUE", "HITL_REVIEW"):
            hitl_count += 1
        elif decision == "AUTO_ACCEPT_OR_REFUND":
            auto_accept_count += 1

        # Track Confusion Matrix
        if is_defensible:
            if is_auto_dispatched:
                tp += 1
                correctly_recovered_gmv += amount
            else:
                fn += 1
                # If erroneously auto-accepted, recovery is completely lost
                if decision == "AUTO_ACCEPT_OR_REFUND":
                    false_negative_financial_cost += amount
        else:
            if is_auto_dispatched:
                fp += 1
                incorrect_auto_action_gmv += amount
                # FP incurs lost amount + ₹1,500 non-refundable fee
                false_positive_financial_cost += (amount + 1500.0)
            else:
                tn += 1

        # Track AI Claims and Verifier stats
        ai_inv = dossier.ai_investigation or {}
        ai_claims = ai_inv.get("claims", [])
        total_ai_claims += len(ai_claims)

        verif = dossier.ai_verification or {}
        if verif:
            grounded_ai_claims += verif.get("grounded_claims", 0)
            if not verif.get("passed", True):
                verifier_rejections += 1

        if cat_code == "O":  # Hallucination trap cohort
            if not verif.get("passed", True) or decision != "AUTO_DISPATCHED":
                hallucination_traps_intercepted += 1

        # Cohort tracking
        if cat_code not in category_stats:
            category_stats[cat_code] = {"name": cat_name, "total": 0, "correct_gate": 0, "auto": 0}
        category_stats[cat_code]["total"] += 1
        if (is_defensible and is_auto_dispatched) or (not is_defensible and not is_auto_dispatched):
            category_stats[cat_code]["correct_gate"] += 1
        if is_auto_dispatched:
            category_stats[cat_code]["auto"] += 1

        status_sym = "[PASS]" if ((is_defensible and is_auto_dispatched) or (not is_defensible and not is_auto_dispatched)) else "[WARN]"
        print(f"[{idx:03d}/{total_scenarios}] {status_sym} [{cat_code}] {case_id:<12} | "
              f"Score: {score:>5.1f} | Decision: {decision:<20} | Defensible: {str(is_defensible):<5} | {lat_ms:.1f}ms")

    elapsed_time = time.time() - start_time

    # Mathematical metric calculations
    precision = (tp / (tp + fp)) * 100.0 if (tp + fp) > 0 else 0.0
    recall = (tp / (tp + fn)) * 100.0 if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    accuracy = ((tp + tn) / total_scenarios) * 100.0 if total_scenarios > 0 else 0.0

    fpr = (fp / (fp + tn)) * 100.0 if (fp + tn) > 0 else 0.0
    fnr = (fn / (tp + fn)) * 100.0 if (tp + fn) > 0 else 0.0

    hitl_rate = (hitl_count / total_scenarios) * 100.0
    auto_dispatch_rate = (auto_dispatch_count / total_scenarios) * 100.0

    ai_grounding_rate = (grounded_ai_claims / total_ai_claims * 100.0) if total_ai_claims > 0 else 100.0
    unsupported_claim_rate = 100.0 - ai_grounding_rate
    verifier_rejection_pct = (verifier_rejections / total_scenarios) * 100.0

    latencies.sort()
    p50_lat = latencies[int(len(latencies) * 0.50)]
    p95_lat = latencies[int(len(latencies) * 0.95)]
    avg_lat = sum(latencies) / len(latencies)

    # Cryptographic ledger check
    integrity = ledger.verify_integrity()

    print("\n" + "=" * 85)
    print("[METRICS] CONFUSION MATRIX & ACCURACY (AUTONOMOUS DISPATCH GATE)")
    print("=" * 85)
    print(f"                Actual Positive (Defensible)   Actual Negative (Not Defensible)")
    print(f"Pred Auto       TP: {tp:<26}  FP: {fp:<26}")
    print(f"Pred Hold/Accept FN: {fn:<26}  TN: {tn:<26}")
    print("-" * 85)
    print(f"- Precision (PPV)             : {precision:.2f}%  [TP / (TP + FP)]")
    print(f"- Recall / Sensitivity (TPR)  : {recall:.2f}%  [TP / (TP + FN)]")
    print(f"- F1 Score                    : {f1:.2f}%")
    print(f"- Overall Gate Accuracy       : {accuracy:.2f}%  [(TP + TN) / Total]")
    print(f"- False Positive Rate (FPR)   : {fpr:.2f}%  [FP / (FP + TN)] (Goal: near 0%)")
    print(f"- False Negative Rate (FNR)   : {fnr:.2f}%  [FN / (TP + FN)]")

    print("\n" + "=" * 85)
    print("[FINANCIAL] FINANCIAL LOSS & GMV RECOVERY METRICS")
    print("=" * 85)
    print(f"- Total Disputed GMV          : INR {total_disputed_gmv:,.2f}")
    print(f"- Autonomous Action GMV       : INR {auto_action_gmv:,.2f} ({auto_action_gmv/total_disputed_gmv*100:.1f}%)")
    print(f"- Correctly Recovered GMV (TP): INR {correctly_recovered_gmv:,.2f} ({correctly_recovered_gmv/total_disputed_gmv*100:.1f}%)")
    print(f"- Incorrect Auto Action GMV   : INR {incorrect_auto_action_gmv:,.2f}")
    print(f"- False Positive Financial Cost: INR {false_positive_financial_cost:,.2f} (Includes INR 1,500 dispute fees)")
    print(f"- False Negative Financial Cost: INR {false_negative_financial_cost:,.2f} (Missed recovery)")
    print(f"- Autonomous Dispatch Yield   : {auto_dispatch_rate:.1f}% ({auto_dispatch_count} disputes)")
    print(f"- Human-in-the-Loop (HITL) Rate: {hitl_rate:.1f}% ({hitl_count} disputes routed)")
    print(f"- Auto-Accept / Refund Rate   : {auto_accept_count/total_scenarios*100:.1f}% ({auto_accept_count} disputes)")

    print("\n" + "=" * 85)
    print("[AI AUDIT] AI EVALUATION & EVIDENCE GROUNDING METRICS")
    print("=" * 85)
    print(f"- Total AI Claims Emitted     : {total_ai_claims}")
    print(f"- Verified Grounded Claims    : {grounded_ai_claims} ({ai_grounding_rate:.2f}%)")
    print(f"- Unsupported Claim Rate      : {unsupported_claim_rate:.2f}%")
    print(f"- Verifier Interception Rate  : {verifier_rejection_pct:.1f}% ({verifier_rejections} cases blocked)")
    print(f"- Hallucination Traps Caught  : {hallucination_traps_intercepted} / 4 (Category O)")

    print("\n" + "=" * 85)
    print("[SYSTEM] SYSTEM PERFORMANCE & CRYPTOGRAPHIC AUDIT")
    print("=" * 85)
    print(f"- Execution Latency P50       : {p50_lat:.2f} ms")
    print(f"- Execution Latency P95       : {p95_lat:.2f} ms")
    print(f"- Execution Latency Average   : {avg_lat:.2f} ms")
    print(f"- Total Benchmark Runtime     : {elapsed_time:.2f} s")
    print(f"- Total Ledger Blocks Appended: {ledger.get_total_count()}")
    print(f"- Ledger Integrity Audit      : {'[PASS] 100% Tamper-evident' if integrity.is_valid else '[FAIL]'}")
    print("=" * 85)

    return {
        "total_scenarios": total_scenarios,
        "confusion_matrix": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "accuracy": accuracy,
        "fpr": fpr,
        "fnr": fnr,
        "total_disputed_gmv": total_disputed_gmv,
        "correctly_recovered_gmv": correctly_recovered_gmv,
        "false_positive_financial_cost": false_positive_financial_cost,
        "hitl_rate": hitl_rate,
        "ai_grounding_rate": ai_grounding_rate,
        "p50_latency_ms": p50_lat,
        "p95_latency_ms": p95_lat,
        "ledger_integrity": integrity.is_valid
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run SentinelDispute Benchmark")
    parser.add_argument("--dev", action="store_true", help="Run against development dataset instead of held-out")
    args = parser.parse_args()

    target_file = (
        os.path.join(os.path.dirname(__file__), "data", "development", "development_dataset.json")
        if args.dev else None
    )
    run_benchmark(target_file)
