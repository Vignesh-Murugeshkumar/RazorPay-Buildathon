# 🛡️ SentinelDispute — AI-Assisted Dispute Defense Engine

> **Razorpay AI Buildathon — Selected Track: AI Risk Manager**  
> *Autonomous Dispute & Chargeback Defense Engine with Verifiable Evidence Grounding, Deterministic Financial Safety Gates, and Tamper-Evident Audit Chains*

[![Vercel Deployment](https://img.shields.io/badge/Vercel-Production%20Live-brightgreen?logo=vercel)](https://razor-pay-buildathon-pi.vercel.app/)
[![CI Workflow](https://github.com/Vignesh-Murugeshkumar/RazorPay-Buildathon/actions/workflows/ci.yml/badge.svg)](https://github.com/Vignesh-Murugeshkumar/RazorPay-Buildathon/actions)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![PyTest Suite](https://img.shields.io/badge/PyTest-125%20Passed-success)](tests/)
[![Security](https://img.shields.io/badge/HMAC--SHA256-Constant--Time-brightgreen)](#security-and-compliance-invariants)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## 📑 Core Documentation Directory

- **[Known Limitations & System Boundaries (`LIMITATIONS.md`)](LIMITATIONS.md)**: **Mandatory reading.** Explicit audit of uncalibrated heuristics, synthetic benchmark scope, in-memory queue boundaries, and unproven claims.
- **[Production Readiness Assessment (`PRODUCTION_READINESS.md`)](PRODUCTION_READINESS.md)**: 12-domain honest gap analysis distinguishing production-ready components from prototype-grade and infrastructure-dependent capabilities.
- **[System Architecture & Trust Boundary (`ARCHITECTURE.md`)](ARCHITECTURE.md)**: Deep dive into the advisory-only AI boundary, local policy KB, deterministic verifier, safety gates, and adversarial threat model.
- **[Empirical Evaluation & Benchmark (`EVALUATION.md`)](EVALUATION.md)**: 115-scenario synthetic held-out benchmark (Cohorts A–P), confusion matrix, comparative modes, and AI grounding rates.
- **[5-Minute Presentation & Demo Script (`DEMO.md`)](DEMO.md)**: Complete pitch flow with timestamps, adversarial demonstration, and live benchmark walkthrough.

---

## ⚡ 60-Second Senior Recruiter & Staff Engineer Overview

### 1. What Problem Does It Solve?
Automating cardholder dispute investigation and representment (Visa CE 3.0, Mastercard FPT) while strictly preventing unsafe AI-driven financial actions. Erroneously auto-dispatching unprovable chargebacks triggers catastrophic **₹1,500–₹45,000 non-refundable bank arbitration penalties**.

### 2. Core Architectural Insight
**"AI should investigate, but deterministic code must hold all financial authority."**  
The LLM is an unprivileged, advisory-only reasoning component. It synthesizes messy multi-source evidence, drafts factual claims, and challenges its own reasoning. It has **zero execution authority** to move money, authorize representment, or bypass network rules.

### 3. Canonical Architecture Pipeline

```text
                  SENTINELDISPUTE AI-ASSISTED DISPUTE DEFENSE
                                    RAZORPAY
                                       │ HMAC + Replay
                                       ▼
                                Evidence Engine
                                       │ EV-001...EV-007
                                       ▼
                                AI INVESTIGATOR
                                ┌──────┴──────┐
                                │             │
                            Policy KB   Self-Challenge
                                │             │
                                └──────┬──────┘
                                       ▼
                             DETERMINISTIC VERIFIER
                                       ▼
                                 NETWORK RULES
                                       ▼
                                EXPECTED VALUE
                                       ▼
                                  SAFETY GATE
                                       │
                      ┌────────────────┼────────────────┐
                      ▼                ▼                ▼
                     AUTO             HITL            ACCEPT
                      │                │                │
                      └────────────────┼────────────────┘
                                       ▼
                                  AUDIT CHAIN
```

```mermaid
flowchart TD
    RZP[Razorpay Webhook Ingress] -->|HMAC-SHA256 + Replay Guard| EE[Evidence Engine EV-001..EV-007]
    
    subgraph AI_ADVISORY["AI Advisory Layer (Zero Financial Authority)"]
        EE --> AI[AI Investigator]
        KB[(Local Policy KB)] -->|TF-IDF Excerpts| AI
        AI --> SC[2-Pass Adversarial Self-Challenge]
    end
    
    subgraph DETERMINISTIC_AUTHORITY["Deterministic Decision & Financial Control"]
        SC --> DEV[Deterministic Evidence Verifier]
        EE -.->|Grounding Truth| DEV
        DEV --> NR[Network Policy Rules: Visa CE 3.0 / MC FPT]
        NR --> EV[Expected Value Engine E[V]]
        EV --> SG[Deterministic Financial Safety Gate]
    end
    
    SG -->|Sc >= 85, E[V] > 0, Verified| AUTO[AUTO_REPRESENT]
    SG -->|Evidence Gap, Conflict, Uncertain| HITL[HITL_REVIEW]
    SG -->|E[V] <= 0, Non-Defensible| ACCEPT[ACCEPT_LOSS]
    
    AUTO --> AC[(Tamper-Evident SHA-256 Audit Chain)]
    HITL --> AC
    ACCEPT --> AC
```

---

## 🔍 Canonical Evidence Engine (`EV-001` through `EV-007`)

SentinelDispute normalizes all heterogeneous dispute signals into 7 immutable canonical tokens before invoking any AI or rule evaluation:

| Token | Evidence Dimension | Source & Telemetry | Verification Criteria |
| :---: | :--- | :--- | :--- |
| **`EV-001`** | **Device & IP Telemetry** | Session telemetry, IP, User-Agent | IP match or device fingerprint match against historical orders |
| **`EV-002`** | **Customer Identification** | Customer account ID, verified phone/email | Matches registered account on file |
| **`EV-003`** | **3D Secure / MFA Authentication** | Gateway liability shift authentication | 3DS cryptographic auth code or SMS/App OTP confirmation |
| **`EV-004`** | **Carrier Proof of Delivery (POD)**| Logistics carrier (Delhivery, Shiprocket, BlueDart)| Tracking number present + delivery confirmed + signature |
| **`EV-005`** | **GPS Geolocation Perimeter** | Courier GPS delivery coordinate scan | Verified delivery coordinate within 50m of cardholder address |
| **`EV-006`** | **Historical Lookback Transactions**| Prior undisputed settled transaction records | 2+ qualifying orders between 120–365 days (Visa CE 3.0 / MC FPT) |
| **`EV-007`** | **Digital Fulfillment & Server Logs**| SaaS server access logs, download receipts | Verified server timestamp logs while user account is active |

### Deterministic Contradiction Detection:
Before any AI report is evaluated, the system executes deterministic conflict detection:
- `CONF-001`: Carrier marked delivered, but tracking number is empty or missing.
- `CONF-002`: Recipient signature present, but carrier status is unconfirmed/false.
- `CONF-003`: Delivery confirmed, but GPS coordinates lie >50m from cardholder address.
- `CONF-004`: Digital access claimed as consumed, but user account is closed/inactive.
*Any contradiction immediately disqualifies autonomous representment and routes to Human-in-the-Loop (HITL).*

---

## 🛡️ The Two-Stage Deterministic Safety Boundary

To ensure the system never makes autonomous financial mistakes, SentinelDispute separates investigation from verification and execution:

### Stage 1: Deterministic Evidence Verifier
1. **Evidence Grounding**: Every claim `[CL-xxx]` must cite verified canonical tokens (`EV-001`..`EV-007`).
2. **Hallucination Interception**: Any non-existent token (e.g. `EV-999`, `EV-CARRIER-SATELLITE`) triggers an immediate verification failure.
3. **Contradiction Enforcement**: Rejects any report that cites a contradicted evidence token as positive justification.
4. **Policy Retrieval Verification**: Validates that all cited policy document IDs match session-retrieved excerpts.

### Stage 2: Deterministic Safety Gate (4 Hard Financial Rules)
The final financial decision is executed by 100% deterministic Python code:
1. **Hard Rule 1 (Verifier Failure)**: If evidence verification fails $\to$ `HITL_REVIEW` (strict override).
2. **Hard Rule 2 (Objective Contradiction)**: If any evidence contradiction exists $\to$ `HITL_REVIEW` (strict override).
3. **Hard Rule 3 (Negative Expected Value)**: If $E[V] \le 0$ and $P(\text{win}) < 0.40 \to$ `ACCEPT_LOSS` (auto-refunds to prevent arbitration penalties).
4. **Hard Rule 4 (Autonomous Representment Qualification)**: Requires:
   - Network compliance verified (Visa CE 3.0 or Mastercard FPT)
   - Verified fulfillment proof (POD or digital logs)
   - $E[V] > 0$
   - Win probability $P(\text{win}) \ge 0.70$
   - Confidence score $S_c \ge 85.0$
   - AI reasoning confidence $\ge 70\%$
   *Otherwise $\to$ default fallback to `HITL_REVIEW`.*

---

## 📊 Measured Synthetic Benchmark Results (115 Scenarios)

Evaluated against a held-out dataset of **115 dispute scenarios** across 16 adversarial and operational cohorts ([Categories A through P](EVALUATION.md)).

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

| Metric | Formula | Value | Production Impact |
| :--- | :--- | :---: | :--- |
| **Precision (PPV)** | $\frac{TP}{TP + FP}$ | **100.00%** | Zero false representments; zero arbitration penalty bleed |
| **Recall (TPR)** | $\frac{TP}{TP + FN}$ | **100.00%** | Captured 100% of legitimately recoverable disputes |
| **F1 Score** | $2 \cdot \frac{P \cdot R}{P + R}$ | **100.00%** | Optimal balance of precision and safety |
| **Gate Accuracy** | $\frac{TP + TN}{\text{Total}}$ | **100.00%** | Correctly gated all 115 test scenarios |
| **False Positive Rate** | $\frac{FP}{FP + TN}$ | **0.00%** | Strict prevention of illegitimate auto-dispatches |
| **Total Disputed GMV** | $\sum \text{Amount}$ | **₹5,40,024.00** | Complete held-out portfolio evaluated |
| **Defended GMV Proxy (TP)** | Net Recovery Proxy | **₹3,35,400.00** | **62.1% net capital protected** |
| **AI Evidence Grounding** | Grounded / Total | **100.00%** | 249/249 claims verified against valid `EV-xxx` tokens |
| **Hallucination Traps** | Category O | **4 / 4 Caught** | 100% intercepted by Deterministic Evidence Verifier |
| **Contradictions Blocked**| Category G | **6 / 6 Caught** | 100% blocked from autonomous representment |
| **Audit Ledger Integrity**| SHA-256 Chain | **100% Valid** | Tamper-evident SHA-256 hash chain verified |

---

## ⚖️ Honest Limitations & Boundaries (What We Do NOT Claim)

SentinelDispute adheres strictly to honest engineering disclosures:
1. **Synthetic Regression Benchmark**: The 115-case test suite validates deterministic rule logic, contradiction detection, and gate safety. It is **NOT** a retrospective study of live merchant outcomes.
2. **Heuristic Win Probability**: The default estimator is an expert heuristic baseline. Empirical probability calibration machinery exists (`fit_platt_scaling_model`, Brier score, ECE), but requires $\ge 50$ real merchant dispute adjudications before activation.
3. **Queue Architecture Scope**:
   - Local / CI: `InMemoryBackgroundQueue` (in-process thread pool, zero infrastructure dependencies).
   - Production-shaped: `RedisDisputeQueue` (LPUSH/RPOP FIFO queue, state persistence, DLQ).
   - Enterprise production: Requires managed Redis + independently orchestrated worker processes (e.g. Celery / BullMQ on Kubernetes).
4. **No Blockchain or Legal Non-Repudiation**: The audit ledger is an append-only SHA-256 cryptographic hash chain providing tamper-evidence; it is not a decentralized blockchain.
5. **Database Fail-Closed**: In production, if PostgreSQL is missing or unreachable, the system strictly fails closed rather than silently falling back to ephemeral local SQLite.

---

## 🚀 Quickstart & Verification

### 1. Installation
```bash
git clone https://github.com/Vignesh-Murugeshkumar/RazorPay-Buildathon.git
cd RazorPay-Buildathon
pip install -r requirements.txt
```

### 2. Run Test Suite (125 Tests)
```bash
pytest -v
```

### 3. Run Benchmark Suite (115 Held-Out Scenarios)
```bash
# Run Sentinel full pipeline benchmark
python tests/run_benchmark.py --mode=sentinel

# Run 3-mode comparative evaluation (RULES_ONLY vs AI_ONLY vs SENTINEL)
python tests/run_benchmark.py --mode=all
```

### 4. Start Dashboard Server
```bash
uvicorn app.main:app --reload --port 8000
```
Open **[http://localhost:8000](http://localhost:8000)** for the interactive dashboard or **[http://localhost:8000/docs](http://localhost:8000/docs)** for OpenAPI Swagger documentation.

---

## 🔌 API Surface Directory

| Group | Method | Endpoint | Description |
|---|---|---|---|
| **Webhooks** | `POST` | `/api/v1/webhook/dispute` | Primary Razorpay webhook ingress with HMAC-SHA256 & replay guard |
| | `POST` | `/api/v1/webhook?async=true` | Asynchronous Fast-ACK ingress (returns HTTP 202 with `task_id`) |
| **Queue** | `GET` | `/api/v1/queue/tasks/{task_id}`| Poll async background task lifecycle status |
| **Disputes** | `GET` | `/api/v1/disputes` | List evaluated dispute dossiers, scores, and decisions |
| | `GET` | `/api/v1/disputes/{id}` | Deep-dive evidence dossier, AI report, and cryptographic seal |
| | `POST` | `/api/v1/disputes/{id}/remediate`| Human-in-the-Loop evidence remediation endpoint |
| | `GET` | `/api/v1/disputes/{id}/timeline` | Chronological audit timeline of all dispute state transitions |
| | `GET` | `/api/v1/disputes/{id}/provenance`| Structured evidence provenance graph (Source $\to$ EV $\to$ Rule $\to$ Decision) |
| | `GET` | `/api/v1/disputes/{id}/representment-package` | Structured representment package JSON |
| | `GET` | `/api/v1/disputes/{id}/representment-pdf` | Bank-ready legal PDF representment packet |
| **Outcomes & Calibration**| `POST` | `/api/v1/disputes/outcome` | Ingest gateway dispute resolution outcome (`won` / `lost`) |
| | `POST` | `/api/v1/disputes/outcomes/batch` | Batch ingest gateway settlement dispute outcomes |
| | `GET` | `/api/v1/disputes/calibration/status`| Empirical win probability calibration status and Brier/ECE metrics |
| | `POST` | `/api/v1/disputes/calibration/train` | Train empirical Platt Scaling calibrator on historical outcomes |
| **Rules & Pre-Dispute** | `GET` | `/api/v1/rules` | Card brand regulatory framework registry (Visa CE 3.0 / MC FPT) |
| | `POST` | `/api/v1/pre-dispute/inquiry` | Pre-dispute inquiry deflection handler ($\le 2s$ SLA) |
| **Audit** | `GET` | `/api/v1/audit/integrity` | Verify complete SHA-256 hash chain continuity from genesis |
| | `GET` | `/api/v1/audit/blocks` | Inspect raw tamper-evident audit ledger blocks |
| **System** | `GET` | `/api/v1/health` | Deep health check (Application, Database Ping, Audit Ledger) |
| | `GET` | `/api/v1/dashboard/summary` | Enterprise dispute portfolio dashboard summary |
| | `POST` | `/api/v1/benchmark/run` | Execute 115-scenario held-out benchmark on demand |

---

## 🛡️ License
Distributed under the MIT License. Built for the Razorpay AI Buildathon 2026.