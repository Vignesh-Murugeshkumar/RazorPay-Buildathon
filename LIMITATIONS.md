# SentinelDispute — Known Limitations & System Boundaries

> **Engineering Honesty Disclaimer**: This document provides an unvarnished audit of current system limitations, unproven assumptions, and architectural boundaries. It exists to ensure that prototype capabilities are never mistaken for production-validated scale.

---

## 1. Data & Outcome Ingestion Limitations

- **No Real Merchant Dispute Historical Dataset**: The system does not ship with or train on a dataset of real, settled merchant chargebacks. Historical dispute resolution data across card networks is proprietary to payment processors and merchants.
- **Synthesized Outcome Demonstration**: While ingestion endpoints (`POST /api/v1/disputes/outcomes/batch`) and closed-loop feedback schemas are implemented in code, all baseline profiles and test datasets use synthetically constructed dispute scenarios.
- **Merchant Behavioral Variance**: Real merchant chargebacks exhibit complex seasonal, merchant-category (MCC), and cross-border nuances that synthetic test scenarios do not fully capture.

---

## 2. Probability Estimation & Calibration Limitations

- **Default Estimator is Heuristically Derived**: The default win probability estimator (`HeuristicBaselineEstimator`) is a deterministic piecewise linear model based on card network rules (Visa CE 3.0 / Mastercard FPT) and evidence completeness scores. It is **explicitly uncalibrated** (`is_calibrated=False`).
- **Empirical Calibration Precondition**: True statistical calibration (e.g. Platt Scaling or Isotonic Regression) requires empirical binary outcome pairs $(x_i, y_i \in \{0, 1\})$. The system's `fit_platt_scaling_model()` strictly requires at least 50 settled dispute outcomes before activating to prevent statistical overfitting on sparse data.
- **Uncalibrated Expected Value ($E[V]$)**: The mathematical expected value equation $E[V] = P(\text{win}\mid x) \cdot A - (1 - P(\text{win}\mid x)) \cdot F_{\text{fee}} - C_{\text{op}}$ is structurally sound, but until the probability estimator is fitted against empirical outcomes, $E[V]$ outputs represent risk-calibrated heuristic scores rather than true actuarial values.

---

## 3. Evaluation & Benchmark Limitations

- **115-Case Benchmark is Synthetic**: The 115-scenario test harness (`tests/data/held_out/held_out_dataset.json`) is a **synthetic adversarial regression suite**. It proves deterministic state machine behavior, edge-case coverage, and safety gate integrity. It does **not** prove real-world accuracy or merchant win rates.
- **Proxy Defended GMV vs Real Cash Recovery**: Metric outputs reporting "Defended GMV" (e.g., INR 6,000.00 in benchmark smoke tests) measure the total disputed face value of synthetic cases where the safety gate approved representment. They do not represent realized cash recovery or retrospective merchant savings.
- **Zero Real-World False Positive Rate (FPR) Claim**: The 0.0% false positive rate achieved on the synthetic benchmark demonstrates that no synthetic non-defensible case bypassed the deterministic safety gate. It does not guarantee zero false positives against unseen real-world dispute anomalies or novel adversarial tactics.

---

## 4. Asynchronous Queue & Concurrency Limitations

- **In-Memory Reference Implementation**: The default queue backend (`InMemoryBackgroundQueue`) uses Python's `concurrent.futures.ThreadPoolExecutor`. It is designed for zero-infrastructure local development, unit testing, and serverless demonstrations.
- **No Durable In-Memory State**: Tasks queued in memory disappear if the application process restarts or if a serverless cloud instance terminates.
- **No Multi-Process Synchronization**: Multiple application instances running behind a round-robin load balancer cannot inspect or poll tasks enqueued on a sibling instance when using the in-memory queue.
- **Redis Queue Boundary**: While a `RedisDisputeQueue` implementation is provided with persistent JSON task hashing and Dead Letter Queue (DLQ) support, operating it at scale requires provisioning a managed high-availability Redis cluster (e.g., AWS ElastiCache / Redis Cloud) with active consumer group orchestration (Celery / RQ / BullMQ).

---

## 5. Network Policy Knowledge Base Limitations

- **Locally Curated Corpus**: Policy documents covering Visa Compelling Evidence 3.0, Mastercard First-Party Trust, 3DS liability shift rules, and logistics proof of delivery are locally curated and version-controlled markdown/text excerpts.
- **No Real-Time Network Feed**: Card networks (Visa, Mastercard, RuPay, Amex) do not expose public real-time APIs for network dispute rule updates. Policy updates currently require manual regulatory review and versioned updates in code.

---

## 6. Infrastructure & Perimeter Security Limitations

- **Application-Layer vs Infrastructure Security**: The application implements strict HMAC-SHA256 signature verification, constant-time comparison, timestamp replay protection (5-minute tolerance), event ID deduplication, and payload size bounds.
- **Missing Perimeter Defenses**:
  - No Web Application Firewall (WAF) or Layer 7 DDoS mitigation.
  - No network-layer IP allowlisting for Razorpay webhook origin IPs (must be configured at the CDN / Cloudflare / AWS ALB layer).
  - No automated secret rotation mechanism (secrets are loaded via environment variables).
  - No distributed rate limiting (e.g., sliding-window Redis token bucket across multiple pods).

---

## 7. AI Provider & LLM Validation Limitations

- **Limited Live LLM Validation**: The full 115-case regression benchmark executes deterministically using `MockAIProvider` to ensure zero API cost, repeatability, and CI determinism. Live OpenAI LLM validation has been verified on 10 representative cohorts, which confirms prompt formatting and structured output conformance, but does not constitute a large-scale statistical validation of LLM reasoning quality.
- **Single-Provider Dependency**: The active implementation integrates with OpenAI GPT-4o-mini. Automated multi-vendor failover (e.g., to Anthropic Claude or Google Gemini) is not implemented.
- **Advisory Veto Only**: The system's safety depends on the verifier and safety gate catching AI hallucinations; the AI itself is untrusted and advisory-only.

---

## 8. Audit Chain Limitations

- **Tamper-Evident, Not Tamper-Proof**: The SHA-256 hash chain provides mathematical tamper-evidence: any modification, deletion, reordering, or insertion of a block invalidates all downstream block hashes and fails `verify_integrity()`.
- **Database Co-Location**: In the current build, ledger blocks are stored in the same PostgreSQL/SQLite database as application data. An adversary with full write access to the database and application environment could theoretically re-calculate the entire hash chain from the point of tampering.
- **No External WORM / Hardware Signing**: True cryptographic non-repudiation in banking requires hardware security module (HSM) signing and co-location on Write-Once-Read-Many (WORM) cloud storage (e.g. AWS S3 Object Lock in Compliance mode).

---

## Summary Matrix

| Domain | Implemented Prototype | What Requires Production Infrastructure / Data |
| :--- | :--- | :--- |
| **Ingestion** | HMAC-SHA256, replay nonce, timestamp checks | WAF, DDoS mitigation, IP allowlists, secret rotation |
| **AI Investigation** | Structured JSON schema, 2-pass self-challenge | Multi-vendor fallback, continuous prompt drift monitoring |
| **Verification** | Deterministic verifier, contradiction detector | Live scheme rule feed integration |
| **Win Probability** | Heuristic baseline, Brier/ECE math, Platt engine | 500+ settled merchant dispute records for fitting |
| **Queue** | In-memory ThreadPoolExecutor, RedisQueue class | Managed Redis cluster, Celery worker autoscaling |
| **Database** | PostgreSQL fail-closed, connection pooling | Versioned migrations (Alembic), PITR backup testing |
| **Audit Ledger** | Append-only SHA-256 hash chain with integrity check | S3 WORM Object Lock, HSM digital signatures |
| **Observability** | Structured JSON logs, PII redaction, trace IDs | Prometheus metrics, OpenTelemetry, PagerDuty alerting |
