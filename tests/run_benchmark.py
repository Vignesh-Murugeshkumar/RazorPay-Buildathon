import sys
import os
import time

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.generate_dataset import generate_benchmark_dataset
from app.graphs.dispute_graph import execute_dispute_workflow
from app.ledger.audit_chain import ledger


def run_benchmark():
    print("=" * 80)
    print("🛡️  SENTINELDISPUTE: 60-SCENARIO SYNTHETIC BENCHMARK EVALUATION SUITE")
    print("=" * 80)

    dataset = generate_benchmark_dataset()
    total_scenarios = len(dataset)
    print(f"Loaded {total_scenarios} synthetic dispute scenarios across 4 cohorts.")
    print("-" * 80)

    start_time = time.time()
    correct_decisions = 0
    auto_dispatch_count = 0
    hitl_count = 0
    total_gmv = 0.0
    recovered_gmv = 0.0
    latencies = []

    cohort_stats = {}

    for idx, item in enumerate(dataset, 1):
        payload = item["payload"]
        expected = item["expected_decision"]
        category = item["category"]

        total_gmv += payload.amount_inr

        t0 = time.time()
        dossier = execute_dispute_workflow(payload)
        latency_ms = (time.time() - t0) * 1000
        latencies.append(latency_ms)

        decision = dossier.decision
        score = dossier.confidence_score

        if decision == "AUTO_DISPATCHED":
            auto_dispatch_count += 1
            recovered_gmv += payload.amount_inr
        else:
            hitl_count += 1

        is_match = (
            (expected == "AUTO_DISPATCH" and decision == "AUTO_DISPATCHED") or
            (expected == "ROUTE_TO_HITL_QUEUE" and decision == "ROUTE_TO_HITL_QUEUE")
        )

        if is_match:
            correct_decisions += 1

        if category not in cohort_stats:
            cohort_stats[category] = {"total": 0, "correct": 0, "auto": 0}
        cohort_stats[category]["total"] += 1
        if is_match:
            cohort_stats[category]["correct"] += 1
        if decision == "AUTO_DISPATCHED":
            cohort_stats[category]["auto"] += 1

        status_emoji = "✅" if is_match else "❌"
        print(f"[{idx:02d}/{total_scenarios}] {status_emoji} {payload.dispute_id:<24} | Score: {score:>5.1f} | Decision: {decision:<20} | Exp: {expected:<20} | {latency_ms:.1f}ms")

    elapsed = time.time() - start_time
    precision = (correct_decisions / total_scenarios) * 100.0
    yield_rate = (auto_dispatch_count / total_scenarios) * 100.0
    avg_latency = sum(latencies) / len(latencies)

    # Check Cryptographic Ledger Integrity
    integrity = ledger.verify_integrity()

    print("=" * 80)
    print("📊 BENCHMARK AGGREGATE RESULTS & METRICS")
    print("=" * 80)
    print(f"• Total Scenarios Evaluated   : {total_scenarios}")
    print(f"• Precision Rate              : {precision:.2f}% (Target: > 90%)")
    print(f"• Autonomous Yield Rate       : {yield_rate:.2f}% (Target: > 65%)")
    print(f"• Total Disputed GMV          : ₹{total_gmv:,.2f}")
    print(f"• Net Recovered GMV           : ₹{recovered_gmv:,.2f} ({recovered_gmv/total_gmv*100:.1f}% recovery)")
    print(f"• Average Execution Latency   : {avg_latency:.2f} ms")
    print(f"• Total Time Elapsed          : {elapsed:.2f} s")
    print(f"• Total Ledger Blocks Appended: {ledger.get_total_count()}")
    print(f"• Ledger Integrity Verified   : {'✅ PASSED (0 Tamper Errors)' if integrity.is_valid else '❌ FAILED'}")
    print("-" * 80)
    print("📋 COHORT BREAKDOWN:")
    for cat, stats in cohort_stats.items():
        cat_prec = (stats['correct'] / stats['total']) * 100.0
        print(f"  - {cat:<48}: {stats['correct']}/{stats['total']} correct ({cat_prec:.1f}%), Auto-Dispatched: {stats['auto']}")
    print("=" * 80)

    # Assertions
    assert precision >= 90.0, f"Precision {precision}% below target 90%"
    assert yield_rate >= 65.0, f"Yield {yield_rate}% below target 65%"
    assert integrity.is_valid, "Cryptographic ledger integrity check failed"
    print("🎉 ALL BENCHMARK CRITERIA AND TARGET THRESHOLDS MET!")


if __name__ == "__main__":
    run_benchmark()
