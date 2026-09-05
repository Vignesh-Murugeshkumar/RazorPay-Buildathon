# SentinelDispute — Production Readiness Assessment

> **Document Status**: Internal Engineering Assessment  
> **Last Updated**: 2026-09-05  
> **Classification**: Engineering — Not for external distribution

---

## Executive Summary

SentinelDispute is a dispute/chargeback defense engine designed around a **4-layer trust architecture** where AI recommends, deterministic rules verify, and autonomous financial actions are gated by a safety gate that AI cannot override.

This document provides an honest, domain-by-domain assessment of current production readiness.

---

## Domain Assessments

### 1. API Security & Webhook Ingress

| Aspect | Current State | Production Gap | Risk | Recommendation | Priority |
|--------|--------------|----------------|------|----------------|----------|
| HMAC-SHA256 Verification | ✅ Implemented | None for Razorpay webhooks | Low | — | — |
| Timestamp Replay Guard | ✅ 5-minute tolerance window | None | Low | — | — |
| Event ID Nonce Dedup | ✅ Idempotent state machine | None | Low | — | — |
| Payload Size Limit | ✅ 512KB DDoS guard | None | Low | — | — |
| Production Signature Enforcement | ✅ Strict in `ENVIRONMENT=production` | None | Low | — | — |
| Rate Limiting | ⚠️ Not implemented | No per-IP or per-merchant throttle | Medium | Add `slowapi` or API gateway rate limiting | P1 |
| mTLS / IP Allowlisting | ⚠️ Not implemented | Relies on HMAC only | Low | Add Razorpay webhook IP allowlist at LB/CDN layer | P2 |

### 2. Database & Persistence

| Aspect | Current State | Production Gap | Risk | Recommendation | Priority |
|--------|--------------|----------------|------|----------------|----------|
| PostgreSQL via Supabase | ✅ Full CRUD | None | Low | — | — |
| Fail-Closed in Production | ✅ `RuntimeError` if Postgres unavailable | None | Low | — | — |
| SQLite Dev Fallback | ✅ Preserved for dev/CI only | None | Low | — | — |
| Connection Pooling | ✅ `psycopg-pool` when available | None | Low | — | — |
| Schema Migrations | ⚠️ In-code DDL only | No versioned migration tool | Medium | Adopt Alembic or Flyway for schema versioning | P2 |
| Backup & Recovery | ❌ Not configured | No automated backup strategy | High | Configure Supabase point-in-time recovery and daily snapshots | P1 |

### 3. AI Provider Integration

| Aspect | Current State | Production Gap | Risk | Recommendation | Priority |
|--------|--------------|----------------|------|----------------|----------|
| OpenAI GPT-4o-mini | ✅ Structured output with `response_format` | None | Low | — | — |
| Advisory-Only Architecture | ✅ AI never directly authorizes financial action | None | Low | — | — |
| Graceful Degradation | ✅ Fails to HITL on provider error (FailureProvenance) | None | Low | — | — |
| Model Versioning | ✅ `model_version` tracked in audit chain | None | Low | — | — |
| Cost Controls | ⚠️ $1.91 test budget only | No production cost alerting | Medium | Set OpenAI spend alerts and per-dispute token budgets | P1 |
| Provider Redundancy | ❌ Single provider | No failover to Anthropic/Gemini | Medium | Abstract provider interface to support multi-vendor failover | P2 |

### 4. Evidence Verification & Safety Gate

| Aspect | Current State | Production Gap | Risk | Recommendation | Priority |
|--------|--------------|----------------|------|----------------|----------|
| Deterministic Verifier | ✅ `DeterministicEvidenceVerifier` — no LLM | None | Low | — | — |
| Contradiction Detection | ✅ Blocks autonomous action on conflicts | None | Low | — | — |
| Policy Provenance | ✅ Versioned `PolicyExcerpt` with `document_version`, `source_hash` | None | Low | — | — |
| Safety Gate | ✅ 100% deterministic, blocks on verifier failure / high-severity contradictions | None | Low | — | — |
| 3DS Liability Shift | ✅ Verified as canonical evidence item `EV-003` | None | Low | — | — |

### 5. Win Probability & Expected Value

| Aspect | Current State | Production Gap | Risk | Recommendation | Priority |
|--------|--------------|----------------|------|----------------|----------|
| Probability Abstraction | ✅ `BaseWinProbabilityEstimator` with pluggable backends | None | Low | — | — |
| Heuristic Baseline | ✅ Explicitly labeled `is_calibrated=False`, `method='heuristic_baseline'` | None | Low | — | — |
| Calibration Tooling | ✅ Brier Score, ECE, Calibration Curves, Cost-Sensitive Loss | None | Low | — | — |
| Platt Scaling Engine | ✅ `fit_platt_scaling_model` via L2-regularized logistic regression | Requires $\ge 50$ real outcomes | Low | Safe guard: refuses to fit with $< 50$ records | — |
| Outcome Ingestion API | ✅ `POST /disputes/outcomes/batch` + `GET /calibration/status` | Real gateway volume accumulation | Medium | Stream live `payment.dispute.won/lost` resolution events into database | P1 |

### 6. Audit & Compliance

| Aspect | Current State | Production Gap | Risk | Recommendation | Priority |
|--------|--------------|----------------|------|----------------|----------|
| SHA-256 Hash Chain | ✅ Append-only with monotonic index, chain continuity, hash recomputation | None | Low | — | — |
| Tampering Detection | ✅ 7 tests covering mutation, deletion, insertion, reordering, broken pointers | None | Low | — | — |
| Granular Provenance | ✅ `event_id`, `dispute_id`, `correlation_id`, `actor`, `decision`, `policy_version`, `model_version` | None | Low | — | — |
| Failure Provenance | ✅ Structured `FailureProvenance` records on pipeline errors | None | Low | — | — |
| Regulatory Export | ⚠️ JSON only | No PDF/CSV compliance export | Low | Build compliance report generator for Visa/Mastercard submission | P2 |

### 7. Async Processing & Scalability

| Aspect | Current State | Production Gap | Risk | Recommendation | Priority |
|--------|--------------|----------------|------|----------------|----------|
| Fast-ACK (HTTP 202) | ✅ Via `X-Process-Async: true` header or `?async=true` | None | Low | — | — |
| Queue Abstraction | ✅ `DisputeProcessingQueue` ABC | None | Low | — | — |
| Task Polling | ✅ `GET /queue/tasks/{task_id}` endpoint | None | Low | — | — |
| Durable Redis Broker | ✅ `RedisDisputeQueue` with TTL, retry tracking, DLQ, and fail-closed prod check | Requires Redis deployment | Low | Provision AWS ElastiCache / Redis Cloud in prod | — |
| Zero-Infra Dev Queue | ✅ `InMemoryBackgroundQueue` for local dev/CI/serverless | None | Low | — | — |
| Horizontal Scaling | ⚠️ In-app thread pool worker | Distributed worker pool needed for >1000 disputes/min | Medium | Deploy standalone Celery/RQ workers on Kubernetes | P2 |

### 8. Logging & Observability

| Aspect | Current State | Production Gap | Risk | Recommendation | Priority |
|--------|--------------|----------------|------|----------------|----------|
| Structured JSON Logging | ✅ All log output is structured JSON | None | Low | — | — |
| PII Redaction | ✅ Card numbers, emails, API keys, Bearer tokens masked | None | Low | — | — |
| Correlation IDs | ✅ UUID per request, propagated through pipeline | None | Low | — | — |
| Metrics / APM | ❌ No Prometheus/Datadog integration | No latency/throughput dashboards | Medium | Add OpenTelemetry traces and Prometheus metrics exporter | P1 |
| Alerting | ❌ No automated alerting | Silent failures possible | High | Configure PagerDuty/Slack alerts on HITL fallback spikes | P1 |

### 9. Exception Handling

| Aspect | Current State | Production Gap | Risk | Recommendation | Priority |
|--------|--------------|----------------|------|----------------|----------|
| Domain Exception Hierarchy | ✅ `SentinelError` → `AIProviderError`, `WebhookValidationError`, `DatabaseUnavailableError`, `EvidenceVerificationFailure`, `ContradictionDetectedError`, `PipelineExecutionError` | None | Low | — | — |
| Fail-Safe Circuit Breaker | ✅ Any unhandled pipeline exception → HITL with structured `FailureProvenance` | None | Low | — | — |
| Sanitized Error Responses | ✅ Global exception handler strips internal details from HTTP responses | None | Low | — | — |

### 10. Testing & Quality

| Aspect | Current State | Production Gap | Risk | Recommendation | Priority |
|--------|--------------|----------------|------|----------------|----------|
| Unit & Integration Tests | ✅ 125 tests passing (100% test suite green) | None | Low | — | — |
| Synthetic Benchmark | ✅ 115-case regression suite (`tests/run_benchmark.py`) | None | Low | — | — |
| CI/CD Pipeline | ✅ GitHub Actions workflow (`.github/workflows/ci.yml`) on Py 3.11 & 3.12 | None | Low | — | — |
| Integration Tests | ⚠️ FastAPI TestClient only | No staged Razorpay sandbox integration | Medium | Build sandbox integration test against Razorpay test keys | P2 |
| Load Testing | ❌ None | No baseline throughput/latency data | Medium | Run k6 or Locust load test against staging | P2 |

### 11. Deployment & Infrastructure

| Aspect | Current State | Production Gap | Risk | Recommendation | Priority |
|--------|--------------|----------------|------|----------------|----------|
| Vercel Serverless | ✅ Deployed and health-checked | None | Low | — | — |
| Environment Config | ✅ `ENVIRONMENT`, `DATABASE_URL`, `OPENAI_API_KEY`, `QUEUE_BACKEND` via env vars | None | Low | — | — |
| CI/CD Automation | ✅ Automated GitHub Actions testing, audit check, and benchmark run | None | Low | — | — |
| Secrets Management | ⚠️ Environment variables only | No KMS/Vault rotation | Medium | Migrate to GCP Secret Manager or HashiCorp Vault | P2 |

### 12. Documentation

| Aspect | Current State | Production Gap | Risk | Recommendation | Priority |
|--------|--------------|----------------|------|----------------|----------|
| README | ✅ Architecture + usage documented | — | Low | — | — |
| EVALUATION.md | ✅ 3-tier evaluation methodology | — | Low | — | — |
| API Documentation | ✅ FastAPI auto-generated OpenAPI/Swagger | — | Low | — | — |
| Runbook | ❌ No operational runbook | No incident response procedures | Medium | Author runbook for common failure modes | P2 |

---

## Priority Summary

### Completed Hardening (Current Architecture)
- ✅ Probability abstraction with honest heuristic labeling & Brier/ECE calibration tooling
- ✅ Empirical Platt Scaling training engine (`fit_platt_scaling_model`) + batch outcome ingestion API
- ✅ Deterministic verifier naming and versioned policy provenance
- ✅ Production database fail-closed enforcement (PostgreSQL required, no silent SQLite fallback in prod)
- ✅ Tamper-evident audit hash chain integrity with full tamper detection test suite
- ✅ Structured failure provenance and circuit breaker routing pipeline crashes to HITL
- ✅ Domain exception hierarchy with provenance metadata
- ✅ PII log redaction (PAN, emails, API keys, tokens)
- ✅ Async Fast-ACK webhook with pluggable queue (`InMemoryBackgroundQueue` & `RedisDisputeQueue` with DLQ)
- ✅ GitHub Actions CI/CD matrix (Python 3.11 & 3.12, syntax compilation, pytest, audit verification, benchmark run)
- ✅ Repository cleanup: deprecated stubs removed, 125 tests passing (100% green)

### Production Operational Boundary (To Launch at Scale)
1. **Historical Data Accumulation**: Accumulate $\ge 500$ settled dispute resolution events from live Razorpay merchant traffic before switching the default estimator from `HeuristicBaselineEstimator` to `PlattScalingCalibratedEstimator`.
2. **Managed Infrastructure**: Provision managed AWS ElastiCache / Redis Cloud cluster with replication and persistence enabled (`QUEUE_BACKEND=redis`).
3. **Database Migration Tooling**: Adopt Alembic to formalize database schema revisions across staging and production Supabase environments.
4. **Monitoring & Alerting**: Configure Prometheus/Datadog APM metrics exporter and PagerDuty alerts on elevated HITL routing rates.
5. **Secrets Rotation**: Store webhook secrets and API keys in AWS Secrets Manager or HashiCorp Vault with automated 90-day rotation.

---

> **Recruiter & Architectural Note**: In SentinelDispute, "implemented" does not imply "zero-effort production-grade." The engineering design explicitly delineates local dev/CI execution from enterprise distributed topologies through fail-closed gates, pluggable broker ABCs, and honest methodological labeling.
