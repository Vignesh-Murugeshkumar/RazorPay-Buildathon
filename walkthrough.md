# SentinelDispute — Architecture + Tool-Responsibility Audit & Implementation Walkthrough

## Summary of Accomplishments

SentinelDispute underwent a complete **Architecture and Tool-Responsibility Audit** to enforce the design philosophy:
> **RIGHT TOOL → RIGHT PROCESS → RIGHT DATA → TRACEABLE RESULT**

All architectural bloat, misleading terminology ("RAG" when no vector search was occurring, "calibrated win probability" without empirical calibration datasets, "LangGraph" claims on deterministic workflow code), and fabricated fallback data were eliminated.

---

## 1. Architecture Problems Found During Audit

1. **Responsibility Pollution in `dispute_graph.py`**:
   - `dispute_graph.py` contained ~260 lines of low-level evidence parsing, contradiction heuristics, and HITL priority formulas embedded directly in workflow definitions.
   - **Resolution**: Extracted into dedicated service [app/services/evidence_engine.py](file:///d:/PROJECTS/RAzorpay/RazorPay-Buildathon/app/services/evidence_engine.py).

2. **Misleading "RAG" Terminology**:
   - `rag_rebuttal.py` was claimed as "RAG" but merely performed deterministic string and clause assembly without vector retrieval or unstructured document stores.
   - **Resolution**: Replaced with [app/services/rebuttal_synthesizer.py](file:///d:/PROJECTS/RAzorpay/RazorPay-Buildathon/app/services/rebuttal_synthesizer.py) implementing a **Rule-Constrained Rebuttal Synthesizer** with strict `CL-xxx` $\to$ `EV-xxx` $\to$ `RULE-xxx` provenance. `rag_rebuttal.py` is preserved only as a backward-compatible wrapper.

3. **Fabricated Fallbacks**:
   - `document_ocr.py` defaulted missing tracking numbers to `"BLUEDART99881122"`, carrier to `"BlueDart"`, `has_sig or True`, and fixed timestamps (`"2026-01-15T10:00:00Z"`).
   - `CarrierProof` schema defaulted `carrier_name="BlueDart"`.
   - `app/main.py` remediation endpoint inserted fake tracking numbers (`TRK-...`) and forced `delivered_status=True`.
   - **Resolution**: All defaults removed. Missing values are stored strictly as `None` or marked `MISSING`/`UNVERIFIED`. Synthetic values are permitted only when explicitly tagged with `source="synthetic_simulator"` or `source="synthetic_demo_data"`.

4. **Database Silent Fallback Hazard in Production**:
   - `app/core/db.py` fell back to `/tmp` SQLite when PostgreSQL/Supabase was unreachable, even in production environments.
   - **Resolution**: `ENVIRONMENT=production` now strictly enforces PostgreSQL availability. Connection failures raise explicit `RuntimeError` and `/api/v1/health` marks database `healthy=False`.

5. **Webhook Simulator Bypass**:
   - Tests previously called `execute_dispute_workflow()` directly without exercising HTTP, HMAC verification, timestamp freshness, replay nonce guards, or webhook state machine transitions.
   - **Resolution**: Implemented [app/services/webhook_simulator.py](file:///d:/PROJECTS/RAzorpay/RazorPay-Buildathon/app/services/webhook_simulator.py) exercising `POST /webhooks/razorpay` across 5 distinct synthetic scenarios (A through E).

---

## 2. Key Components & Responsibilities

| Component | File | Primary Responsibility |
| :--- | :--- | :--- |
| **Ingress & Security** | [app/api/v1/endpoints/webhooks.py](file:///d:/PROJECTS/RAzorpay/RazorPay-Buildathon/app/api/v1/endpoints/webhooks.py) | HMAC-SHA256 verification, 300s timestamp freshness, replay nonce check |
| **Pydantic Validation** | [app/schemas/dispute.py](file:///d:/PROJECTS/RAzorpay/RazorPay-Buildathon/app/schemas/dispute.py) | Strict schema enforcement, no fabricated default strings |
| **State Machine DB** | [app/core/db.py](file:///d:/PROJECTS/RAzorpay/RazorPay-Buildathon/app/core/db.py) | Atomic webhook lifecycle: `RECEIVED` $\to$ `PROCESSING` $\to$ `COMPLETED` / `FAILED` |
| **Evidence Engine** | [app/services/evidence_engine.py](file:///d:/PROJECTS/RAzorpay/RazorPay-Buildathon/app/services/evidence_engine.py) | Canonical `EV-001` through `EV-007` extraction with statuses (`VERIFIED`, `PARTIALLY_VERIFIED`, `UNVERIFIED`, `MISSING`, `CONTRADICTED`) |
| **Contradiction Engine** | [app/services/evidence_engine.py](file:///d:/PROJECTS/RAzorpay/RazorPay-Buildathon/app/services/evidence_engine.py) | Deterministic cross-checks: delivered vs tracking, undelivered vs signature, GPS mismatch >50m, active consumption vs inactive account |
| **Network Rule Engine** | [app/rules/card_rules.py](file:///d:/PROJECTS/RAzorpay/RazorPay-Buildathon/app/rules/card_rules.py) | Visa CE 3.0 (2+ qualifying transactions, 120-365d, IP/device match) & Mastercard FPT |
| **Expected Value Engine** | [app/services/expected_value.py](file:///d:/PROJECTS/RAzorpay/RazorPay-Buildathon/app/services/expected_value.py) | Mathematical expectation: $E[V] = P(\text{win}) \cdot A - (1 - P(\text{win})) \cdot F_{\text{fee}} - C_{\text{op}}$ |
| **HITL Prioritization** | [app/services/evidence_engine.py](file:///d:/PROJECTS/RAzorpay/RazorPay-Buildathon/app/services/evidence_engine.py) | Deadline, financial exposure, ambiguity, and contradiction urgency score |
| **Rebuttal Synthesizer** | [app/services/rebuttal_synthesizer.py](file:///d:/PROJECTS/RAzorpay/RazorPay-Buildathon/app/services/rebuttal_synthesizer.py) | Rule-constrained formal letter generator linking `CL-xxx` $\to$ `EV-xxx` $\to$ `RULE-xxx` |
| **Cryptographic Ledger** | [app/services/ledger.py](file:///d:/PROJECTS/RAzorpay/RazorPay-Buildathon/app/services/ledger.py) | Append-only SHA-256 block chain: $h_n = \text{SHA256}(h_{n-1} \parallel \dots)$ |
| **Webhook Simulator** | [app/services/webhook_simulator.py](file:///d:/PROJECTS/RAzorpay/RazorPay-Buildathon/app/services/webhook_simulator.py) | Exercises full HTTP ingress for scenarios A, B, C, D, E |

---

## 3. Simulator Scenarios Verification

All 5 scenarios were executed directly against `POST /webhooks/razorpay`:

| Scenario | Description | HTTP Status | Decision | Score |
| :--- | :--- | :---: | :---: | :---: |
| **A** | **Strong Evidence** (Visa CE 3.0 Qualifying, 2 txns, IP/device matched, carrier/GPS/MFA verified) | `200 OK` | `AUTO_DISPATCHED` | 100.0% |
| **B** | **Weak/Missing Evidence** (No carrier proof, no telemetry, no historical transactions) | `200 OK` | `AUTO_ACCEPT_OR_REFUND` | 0.0% |
| **C** | **Contradictory Evidence** (Delivered=True but tracking=None, GPS > 50m mismatch) | `200 OK` | `ROUTE_TO_HITL_QUEUE` | 40.0% |
| **D** | **Digital Service Dispute** (SaaS active account access logs verified) | `200 OK` | `ROUTE_TO_HITL_QUEUE` | 75.0% |
| **E** | **Negative Expected Value** (Small amount ₹350 vs ₹1500 dispute fee) | `200 OK` | `AUTO_ACCEPT_OR_REFUND` | 0.0% |

---

## 4. Test Suite Execution

All 76 tests across 11 test modules passed in **3.36 seconds**:
```bash
python -m pytest -v
======================= 76 passed, 2 warnings in 3.36s ========================
```
New dedicated test suite:
```bash
python -m pytest -v tests/test_tool_responsibility_and_e2e.py
======================== 18 passed, 1 warning in 1.49s ========================
```
Deployment routes:
- `GET /`: `200 OK`
- `GET /api/v1/health`: `200 OK`
- `GET /api/v1/disputes`: `200 OK`
- `GET /docs`: `200 OK`
- `GET /openapi.json`: `200 OK`
- `POST /webhooks/razorpay`: `200 OK`
