# 🛡️ SentinelDispute

**Autonomous Visa CE 3.0 & Mastercard First-Party Trust (FPT) Dispute Defense Engine for Razorpay Merchants**

[![Vercel Deployment](https://img.shields.io/badge/Vercel-Serverless%20Python-black?logo=vercel)](https://vercel.com)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-Deterministic%20Workflow-orange)](https://github.com/langchain-ai/langgraph)
[![Security](https://img.shields.io/badge/HMAC--SHA256-Constant--Time-brightgreen)](#cryptographic-security)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## 📖 Executive Summary & Problem Domain

Card-Not-Present (CNP) fraud and first-party "friendly fraud" represent an escalating multi-billion-dollar challenge for e-commerce merchants. When cardholders file disputes under reason codes such as **Visa 10.4** or **Mastercard 4837/4855**, merchants face:
1. **Strict Representment Windows**: 30 days (Visa Resolve Online - VROL) and 45 days (Mastercom).
2. **Fragmented Telemetry**: Payment gateway metadata, carrier tracking proofs, session IP/device fingerprints, and 365-day transaction logs scattered across siloed systems.
3. **Low Manual Win Rates (< 30%)**: Manual evidence assembly takes over 40 minutes per dispute and often produces incomplete submissions.

**SentinelDispute** solves this by executing a deterministic, multi-agent state machine that evaluates **Visa Compelling Evidence 3.0 (CE 3.0)** and **Mastercard First-Party Trust (FPT)** compliance matrices in real time, computes a tamper-proof confidence score, seals representment dossiers with cryptographic SHA-256 proofs, and achieves **> 70% autonomous representment yield with > 90% precision**.

---

## 🏛️ System Architecture

```
+-----------------------------------------------------------------------------------+
|                            INGRESS & SECURITY LAYER                               |
|   Razorpay Webhook -> HMAC-SHA256 Constant-Time Verification -> Ingestion Agent   |
+----------------------------------------+------------------------------------------+
                                         | Ingested State Context
+----------------------------------------v------------------------------------------+
|                          EVIDENCE AGGREGATOR AGENT                                |
|   Concurrent Async Fetch: Payment Metadata, Carrier Proofs, Session Telemetry     |
+----------------------------------------+------------------------------------------+
                                         | Telemetry Context
+----------------------------------------v------------------------------------------+
|                     COMPLIANCE & FORMATION ENGINE                                 |
|   Visa CE 3.0 & Mastercard FPT Rules Matrix -> Dossier Confidence Score (Sc)     |
+----------------------------------------+------------------------------------------+
                                         | Evaluated Dossier & Score Sc
+----------------------------------------v------------------------------------------+
|                        AUDIT & GATEKEEPER AGENT                                   |
|   If Sc >= 85: Auto-Dispatch + SHA-256 Seal                                       |
|   If Sc < 85:  Route to Human-in-the-Loop Queue + Diagnostic Gap Report           |
+----------------------------------------+------------------------------------------+
                                         | Append Hash Block
+----------------------------------------v------------------------------------------+
|                     CRYPTOGRAPHIC AUDIT LEDGER                                    |
|   Append-Only SHA-256 Hash Chain: h_n = SHA256(h_n-1 || T_n || A_n || S_n || P_n)  |
+-----------------------------------------------------------------------------------+
```

---

## 📐 Deterministic Compliance & Scoring Matrices

### 1. Visa Compelling Evidence 3.0 (CE 3.0) Framework
Under Visa Reason Code 10.4, satisfying 4 mathematical conditions triggers an **automatic liability shift back to the card issuer**:
* **Transaction Quantity**: $\ge 2$ historical undisputed orders executed on the same card credential.
* **Lookback Window**: Prior qualifying orders must fall between **120 and 365 calendar days** prior to the dispute date.
* **Identifier Matching**: At least 2 of 4 core customer identifiers must match across all 3 transactions (Customer IP, Device ID/Fingerprint, Account Login/User ID, Shipping Address).
* **Mandatory Condition**: At least 1 of the matched identifiers **must** be Customer IP Address or Device ID.

### 2. Mastercard First-Party Trust (FPT) Program
Under Reason Codes 4837, 4853, and 4855:
* **Tier 1 (Device Identity)**: Matching persistent device fingerprint or IP address within 365 days.
* **Tier 2 (Delivery Factor)**: Carrier proof of physical delivery or digital fulfillment logs.
* **Tier 3 (Authentication Factor)**: 2FA/MFA/3DS or account credentials verification.

### 3. Dossier Confidence Score ($S_c$) Formula
$$S_c = w_{\text{CE30}} \cdot m_{\text{CE30}} + w_{\text{carrier}} \cdot m_{\text{carrier}} + w_{\text{mfa}} \cdot m_{\text{mfa}} + \text{GPS bonus}$$

* $w_{\text{CE30}} = 55.0$ (Full network compliance)
* $w_{\text{carrier}} = 35.0$ (Verified carrier delivery proof)
* $\text{GPS bonus} = 10.0$ (Carrier GPS within 50m radius)
* $w_{\text{mfa}} = 5.0$ (2FA/3DS authorization verification)

**Gatekeeper Decision Rules**:
* **If $S_c \ge 85.0$**: Dossier is sealed under SHA-256 and dispatched directly to card network APIs (`AUTO_DISPATCHED`).
* **If $S_c < 85.0$**: Routed to Human-in-the-Loop queue with diagnostic gap report (`ROUTE_TO_HITL_QUEUE`).

### 4. Tamper-Evident Cryptographic Hash Chain Ledger
Every state transition computes and appends a block:
$$h_n = \text{SHA256}(h_{n-1} \parallel \text{Timestamp}_n \parallel \text{AgentID}_n \parallel \text{StateTransition}_n \parallel \text{PayloadHash}_n)$$

---

## 🚀 Getting Started Locally

### Prerequisites
* Python 3.11+
* Git

### 1. Clone & Install Dependencies
```bash
git clone https://github.com/Vignesh-Murugeshkumar/RazorPay-Buildathon.git
cd RazorPay-Buildathon
pip install -r requirements.txt
```

### 2. Start Local Development Server
```bash
uvicorn app.main:app --reload --port 3000
```
Open [http://localhost:3000](http://localhost:3000) to access the interactive web dashboard or [http://localhost:3000/docs](http://localhost:3000/docs) for the Swagger API documentation.

### 3. Run the 60-Scenario Benchmark Suite
```bash
python tests/run_benchmark.py
```

### 4. Run Unit & Security Tests
```bash
pytest tests/
```

---

## ☁️ Vercel Serverless Deployment ($0 Operational Cost)

This project is built natively for **Vercel Serverless Functions** (`@vercel/python`):

1. Push your code to GitHub.
2. Go to [Vercel Dashboard](https://vercel.com) $\rightarrow$ **Add New Project** $\rightarrow$ Import this repository.
3. Add Environment Variable:
   * `WEBHOOK_SECRET` = `your_razorpay_webhook_secret_here`
4. Click **Deploy**.

Vercel automatically detects `vercel.json` and routes `/api/*` and static assets smoothly.

---

## 🐳 Production Container Deployment (Docker & Gunicorn)

For self-hosted Kubernetes, AWS ECS, GCP Cloud Run, or VPS:

### 1. Run with Docker Compose (App + PostgreSQL + Redis)
```bash
docker compose up -d
```

### 2. Standalone Container Run
```bash
docker build -t sentinel-dispute:latest .
docker run -p 3000:3000 \
  -e ENVIRONMENT=production \
  -e RAZORPAY_WEBHOOK_SECRET=your_production_secret \
  -e DATABASE_URL=postgresql://user:pass@host:5432/db \
  sentinel-dispute:latest
```

---

## 🔌 API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/webhook/dispute` | Razorpay dispute webhook ingress with HMAC-SHA256 verification |
| `GET` | `/api/v1/disputes` | List all evaluated dispute dossiers and confidence scores |
| `GET` | `/api/v1/disputes/{id}` | Deep-dive evidence dossier, telemetry breakdown, and seal |
| `GET` | `/api/v1/audit/integrity` | Cryptographic hash chain verification report |
| `GET` | `/api/v1/audit/blocks` | Paginated list of ledger blocks |
| `GET` | `/api/v1/stats` | High-level KPI metrics, yield rates, and recovered GMV |
| `POST` | `/api/v1/simulate` | Direct simulation runner endpoint |
| `POST` | `/api/v1/benchmark/run` | Execute 60-scenario synthetic benchmark on-demand |
| `GET` | `/docs` | Interactive Swagger API documentation |

---

## 📊 Benchmark Performance Results

* **Total Synthetic Scenarios**: 60
* **Autonomous Yield Rate**: 75.0% (Auto-Dispatched on qualifying evidence)
* **Precision Rate**: 100.0% (Zero false auto-dispatches on unqualified cases)
* **Average Processing Latency**: < 5 ms per dispute
* **Ledger Cryptographic Integrity**: 100% Verified (0 broken links)

---

## 🛡️ License
Distributed under the MIT License. Built for Razorpay Buildathon.