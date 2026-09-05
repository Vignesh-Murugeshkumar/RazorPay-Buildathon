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
| Platt Scaling | ✅ Interface defined; raises `ValueError` if unfitted (prevents fake calibration) | None | Low | — | — |
| Historical Outcome Data | ❌ No real dispute outcomes collected | Cannot calibrate without production data | High | Build outcome ingestion pipeline from Razorpay dispute resolution webhooks | P1 |

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
| Queue Abstraction | ✅ `DisputeProcessingQueue` ABC with `InMemoryBackgroundQueue` | None | Low | — | — |
| Task Polling | ✅ `GET /queue/tasks/{task_id}` endpoint | None | Low | — | — |
| Production Broker | ❌ In-memory only | Tasks lost on restart | High | Implement `RedisBullQueue` or Celery backend for durability | P1 |
| Horizontal Scaling | ⚠️ Singleton queue | Single-process only | Medium | Move to distributed task queue for multi-instance deployments | P2 |

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
| Unit Tests | ✅ 120+ tests passing | None | Low | — | — |
| Synthetic Benchmark | ✅ 115-case regression suite (`tests/run_benchmark.py`) | None | Low | — | — |
| Integration Tests | ⚠️ FastAPI TestClient only | No staged Razorpay sandbox integration | Medium | Build sandbox integration test against Razorpay test keys | P2 |
| Load Testing | ❌ None | No baseline throughput/latency data | Medium | Run k6 or Locust load test against staging | P2 |

### 11. Deployment & Infrastructure

| Aspect | Current State | Production Gap | Risk | Recommendation | Priority |
|--------|--------------|----------------|------|----------------|----------|
| Vercel Serverless | ✅ Deployed and health-checked | None | Low | — | — |
| Environment Config | ✅ `ENVIRONMENT`, `DATABASE_URL`, `OPENAI_API_KEY` via env vars | None | Low | — | — |
| Secrets Management | ⚠️ Environment variables only | No KMS/Vault rotation | Medium | Migrate to GCP Secret Manager or HashiCorp Vault | P2 |
| CI/CD | ⚠️ Manual deployment | No automated test → deploy pipeline | Medium | Add GitHub Actions CI with test gate before deploy | P1 |

### 12. Documentation

| Aspect | Current State | Production Gap | Risk | Recommendation | Priority |
|--------|--------------|----------------|------|----------------|----------|
| README | ✅ Architecture + usage documented | — | Low | — | — |
| EVALUATION.md | ✅ 3-tier evaluation methodology | — | Low | — | — |
| API Documentation | ✅ FastAPI auto-generated OpenAPI/Swagger | — | Low | — | — |
| Runbook | ❌ No operational runbook | No incident response procedures | Medium | Author runbook for common failure modes | P2 |

---

## Priority Summary

### P0 — Addressed in Current Release
- ✅ Probability abstraction with honest heuristic labeling
- ✅ Deterministic verifier naming and versioned policy provenance
- ✅ Production database fail-closed enforcement
- ✅ Tamper-evident audit hash chain integrity
- ✅ Structured failure provenance and circuit breaker
- ✅ Domain exception hierarchy
- ✅ PII log redaction
- ✅ Async queue abstraction

### P1 — Recommended for Production Launch
- Historical dispute outcome ingestion pipeline
- Production message broker (Redis/Celery)
- OpenAI cost alerting and per-dispute token budgets
- Automated backup configuration
- CI/CD pipeline with test gate
- APM / metrics integration
- Alerting on HITL fallback spikes

### P2 — Post-Launch Improvements
- Schema migration tooling (Alembic)
- Multi-provider AI failover
- IP allowlisting at infrastructure layer
- k6/Locust load testing baseline
- Compliance report PDF/CSV export
- Secrets rotation via Vault/KMS
- Operational runbook

---

> **Note**: This assessment is based on the current codebase state. All P1 items should be addressed before processing real merchant disputes at scale.
