# 🛡️ SentinelDispute — Autonomous AI Risk Manager

> **Razorpay AI Buildathon — Selected Track: AI Risk Manager**  
> *Autonomous Dispute & Chargeback Defense Engine with Verifiable Evidence Grounding, Deterministic Safety Gates, and Tamper-Evident Audit Ledgers*

[![Vercel Deployment](https://img.shields.io/badge/Vercel-Production%20Live-brightgreen?logo=vercel)](https://razor-pay-buildathon-pi.vercel.app/)
[![CI Workflow](https://github.com/Vignesh-Murugeshkumar/RazorPay-Buildathon/actions/workflows/ci.yml/badge.svg)](https://github.com/Vignesh-Murugeshkumar/RazorPay-Buildathon/actions)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![PyTest Suite](https://img.shields.io/badge/PyTest-125%20Passed-success)](tests/)
[![Security](https://img.shields.io/badge/HMAC--SHA256-Constant--Time-brightgreen)](#cryptographic-security)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## 📑 Core Documentation Directory

- **[System Architecture & Trust Boundary (`ARCHITECTURE.md`)](ARCHITECTURE.md)**: Deep dive into the advisory-only AI boundary, local policy KB, AI verifier, deterministic safety gates, and adversarial threat model.
- **[Empirical Evaluation & Benchmark (`EVALUATION.md`)](EVALUATION.md)**: 115-scenario held-out dataset evaluation (Cohorts A–P), confusion matrix, precision vs recall, financial GMV recovery, comparative modes, and AI grounding rates.
- **[Production Readiness Assessment (`PRODUCTION_READINESS.md`)](PRODUCTION_READINESS.md)**: 12-domain gap analysis covering API security, database, AI provider, audit, async processing, PII protection, and deployment.
- **[5-Minute Presentation & Demo Script (`DEMO.md`)](DEMO.md)**: Complete pitch flow with timestamps, adversarial demonstration, and live benchmark walkthrough.

---

## 📖 Executive Summary & Problem Domain

Card-Not-Present (CNP) fraud and first-party "friendly fraud" represent an escalating multi-billion-dollar loss vector for digital merchants. When cardholders file disputes under reason codes such as **Visa 10.4** or **Mastercard 4837/4855**, merchants face:

1. **Short Representment Windows**: 30 days (Visa Resolve Online - VROL) and 45 days (Mastercom).
2. **High Arbitration Risk**: Erroneously auto-dispatching unprovable disputes incurs a non-refundable **₹1,500 – ₹45,000 issuer penalty**.
3. **The AI Hallucination Danger**: Giving an unconstrained LLM direct authority to move money or submit legal filings results in catastrophic false-positive bleed.

**SentinelDispute** solves this through a strictly bounded, defense-in-depth architecture:

$$\text{Ingest (HMAC)} \longrightarrow \text{Evidence Extraction} \longrightarrow \text{Policy Retrieval (Local KB)} \longrightarrow \text{AI Investigation Agent} \longrightarrow \text{AI Evidence Verifier} \longrightarrow \text{Deterministic Rules} \longrightarrow \text{Expected Value } E[V] \longrightarrow \text{Deterministic Safety Gate} \longrightarrow \text{Cryptographic Ledger}$$

---

## 🏛️ System Architecture & Data Flow

```mermaid
flowchart TD
    subgraph INGESTION["1. Ingestion Layer"]
        RZP[Razorpay Webhook] -->|HMAC-SHA256 Verified| PAYLOAD[Pydantic DisputePayload]
    end

    subgraph EVIDENCE["2. Evidence Engine"]
        PAYLOAD --> EXTRACT[Evidence Extractor]
        EXTRACT --> EV_ITEMS[Normalized Evidence Items EV-001..EV-007]
        EXTRACT --> CONFLICT[Contradiction Detector]
    end

    subgraph AI_LAYER["3. AI Advisory Layer (Advisory-Only)"]
        EV_ITEMS --> AGENT[Evidence Investigation Agent]
        KB[(Local Policy KB - Visa / MC / 3DS / POD)] -->|TF-IDF Retrieval| AGENT
        AGENT -->|Schema Validated JSON| REPORT[DisputeInvestigationReport]
        REPORT --> VERIFIER[AI Evidence Verifier]
        EV_ITEMS -.->|Grounding Truth| VERIFIER
        CONFLICT -.->|Negative Constraint| VERIFIER
    end

    subgraph DETERMINISTIC["4. Deterministic Financial Safety"]
        VERIFIER -->|VerificationResult| GATE[Deterministic Safety Gate]
        RULES[Visa CE 3.0 / MC FPT Engines] --> GATE
        EV_ENG[Expected Value Engine E[V]] --> GATE
        CONFLICT --> GATE
    end

    subgraph EXECUTION["5. Settlement & Audit"]
        GATE -->|Allowed Auto-Dispatch| DISPATCH[Auto-Submit Representment]
        GATE -->|Evidence Gap / Contradiction| HITL[Route to HITL Review Queue]
        GATE -->|Negative EV / Ineligible| REFUND[Auto-Accept / Refund]
        
        DISPATCH --> LEDGER[(SHA-256 Tamper-Evident Ledger)]
        HITL --> LEDGER
        REFUND --> LEDGER
    end
```

---

## 📊 Measured Benchmark Results (115 Held-Out Scenarios)

Evaluated against a held-out dataset of **115 dispute scenarios** across 16 adversarial and operational cohorts ([Categories A through P](EVALUATION.md)).

> [!NOTE]
> **Evaluation Distinction**: These benchmark figures represent **synthetic scenario-defined evaluations** on a controlled, held-out dataset designed to test edge cases, contradictions, and policy compliance. The recovered GMV is a **defended-GMV proxy**, not a claim of retrospective real-world recovered cash.

```
                              ACTUAL POSITIVE        ACTUAL NEGATIVE
                           (Truly Defensible: 45)  (Not Defensible: 70)
                        +-------------------------+-------------------------+
PREDICTED AUTONOMOUS    |                         |                         |
(AUTO_DISPATCHED)       |   TP = 45               |   FP = 0                |
                        |                         |                         |
------------------------+-------------------------+-------------------------+
PREDICTED WITHHELD      |                         |                         |
(HITL / AUTO_ACCEPT)    |   FN = 0                |   TN = 70               |
                        |                         |                         |
                        +-------------------------+-------------------------+
```

| Metric | Formula | Value | Impact |
| :--- | :--- | :---: | :--- |
| **Precision (PPV)** | $\frac{TP}{TP + FP}$ | **100.00%** | Zero false representments; zero arbitration penalty bleed |
| **Recall (TPR)** | $\frac{TP}{TP + FN}$ | **100.00%** | Captured 100% of legitimately recoverable disputes |
| **F1 Score** | $2 \cdot \frac{P \cdot R}{P + R}$ | **100.00%** | Optimal balance of precision and coverage |
| **Gate Accuracy** | $\frac{TP + TN}{\text{Total}}$ | **100.00%** | Correctly gated all 115 disputes |
| **False Positive Rate** | $\frac{FP}{FP + TN}$ | **0.00%** | Strict prevention of illegitimate auto-dispatches |
| **Total Disputed GMV** | $\sum \text{Amount}$ | **₹5,40,024.00** | Complete held-out portfolio evaluated |
| **Defended GMV Proxy (TP)** | Net Recovery Proxy | **₹3,35,400.00** | **62.1% net capital protected** |
| **AI Evidence Grounding** | Grounded / Total | **100.00%** | 249/249 claims verified against valid `EV-xxx` tokens |
| **Hallucination Traps** | Category O | **4 / 4 Caught** | 100% intercepted by AI Verifier |
| **P50 Latency** | Execution Speed | **69.26 ms** | Fast real-time webhook turnaround |
| **Cryptographic Ledger** | SHA-256 Chain | **100% Valid** | Tamper-evident SHA-256 hash chain audit |

---

## 🛡️ Two-Pass Self-Challenge & Deterministic Safety Gate

To guarantee safety for payment gateways and merchants, SentinelDispute uses a **two-pass AI investigation with independent verification**:

```
[Evidence & Policies] 
        ↓
Pass 1: Structured AI Investigation (Evidence Grounding, Win Probability, Reasoning Confidence)
        ↓
Pass 2: Adversarial Self-Challenge (Devil's Advocate, Alternative Interpretation, Confidence Adjustment)
        ↓
Independent AI Verifier (Audits hallucinated IDs, ungrounded claims, unretrieved policy citations)
        ↓
Deterministic Network Rules (Visa CE 3.0 / Mastercard FPT Engine)
        ↓
Expected Value Engine E[V] (Net recovery vs ₹1,500 non-refundable arbitration risk)
        ↓
Deterministic Safety Gate (Autonomous Action Authority: AUTO_REPRESENT | HITL | ACCEPT)
```

### Safety & Grounding Invariants:
1. **Advisory-Only AI**: The LLM investigates and provides structured advice; it can **never** directly authorize representment or money movement.
2. **Strict Verification**: If the verifier catches a single hallucinated evidence ID or ungrounded assertion, autonomous action is **strictly blocked**.
3. **Fail-Safe Provider Error Handling**: If OpenAI errors or fails, the pipeline routes immediately to **HITL**. It **never** silently falls back to MockAI or pretends OpenAI succeeded.
4. **Hard Gate Threshold**: Requires Verified Evidence + Valid Network Policy + $E[V] > 0$ + Win Prob $\ge 70\%$ + Confidence Score $\ge 85.0$.

---

## 🚀 Quickstart & Benchmark Commands

### 1. Installation
```bash
git clone https://github.com/Vignesh-Murugeshkumar/RazorPay-Buildathon.git
cd RazorPay-Buildathon
pip install -r requirements.txt
```

### 2. Run Test Suite (125 Tests)
```bash
pytest tests/
```

### 3. Run Benchmark Suite (Comparative & Single-Mode)
```bash
# Run 3-mode comparative evaluation (RULES_ONLY vs AI_ONLY vs SENTINEL) on all 115 cases
python tests/run_benchmark.py --mode all --provider mock

# Run Sentinel full pipeline in mock mode
python tests/run_benchmark.py --mode sentinel --provider mock

# Run real OpenAI validation on 10 representative cases (Preserves API budget)
# Requires OPENAI_API_KEY set in environment
python tests/run_benchmark.py --mode sentinel --provider openai --limit 10
```

### 4. Start Dashboard Server
```bash
uvicorn app.main:app --reload --port 8000
```
Open **[http://localhost:8000](http://localhost:8000)** for the interactive dashboard or **[http://localhost:8000/docs](http://localhost:8000/docs)** for the OpenAPI Swagger interface.

---

## 🔌 Core API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/webhook/dispute` | Razorpay dispute webhook ingress with HMAC-SHA256 verification |
| `POST` | `/api/v1/webhook?async=true` | Fast-ACK async webhook ingress, returns HTTP 202 with `task_id` |
| `GET` | `/api/v1/queue/tasks/{task_id}` | Poll async dispute processing task status |
| `GET` | `/api/v1/disputes` | List evaluated dispute dossiers, scores, and gate decisions |
| `GET` | `/api/v1/disputes/{id}` | Deep-dive evidence dossier, AI investigation report, and cryptographic seal |
| `POST` | `/api/v1/disputes/{id}/remediate` | Human-in-the-Loop evidence remediation endpoint |
| `GET` | `/api/v1/disputes/{id}/representment-pdf` | Download signed legal representment document |
| `POST` | `/api/v1/disputes/outcomes/batch` | Batch ingest gateway settlement dispute resolution outcomes |
| `GET` | `/api/v1/disputes/calibration/status` | Empirical win probability calibration status and Brier/ECE metrics |
| `POST` | `/api/v1/disputes/calibration/train` | Empirical Platt Scaling calibrator training on historical outcomes |
| `GET` | `/api/v1/audit/integrity` | Verify SHA-256 cryptographic hash chain integrity |
| `GET` | `/api/v1/audit/blocks` | Inspect raw tamper-evident ledger blocks |
| `POST` | `/api/v1/simulate` | Interactive dispute scenario simulation |
| `POST` | `/api/v1/benchmark/run` | Execute 115-scenario held-out benchmark on demand |

---

## 🛡️ License
Distributed under the MIT License. Built for the Razorpay AI Buildathon 2026.