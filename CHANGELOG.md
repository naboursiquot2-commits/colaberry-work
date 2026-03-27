# Changelog

All notable changes to this project are documented here.

---

## [0.1.0] — 2026-03-27

Initial production-hardened release of the Colaberry Nexus AI Alumni Intelligence Platform.

### Added

**Core service**
- FastAPI backend with versioned routes under `/v1`
- Deterministic alumni matching engine with weighted scoring across skills, interests, location, and engagement
- Explainability field (`matched_on`) on every match result
- Pagination (`limit` / `offset`) on `/v1/match` and `/v1/alumni`
- Readiness-aware health endpoint (`GET /v1/health`) returning `profiles_loaded` count
- In-process request metrics endpoint (`GET /v1/metrics`) — no auth required

**Security and reliability**
- API key authentication (`x-api-key`) on all data endpoints
- Fail-closed startup: application refuses to start if `API_KEY` environment variable is not set
- Per-API-key in-memory rate limiting (configurable via `RATE_LIMIT_MAX` / `RATE_LIMIT_WINDOW`)
- Structured JSON error responses with `request_id` on all 4xx/5xx

**Observability**
- Structured JSON logging on every request: `method`, `path`, `status_code`, `elapsed_ms`
- Request ID tracing (`X-Request-ID`) propagated through all responses and log lines
- Match event logging: `profiles_loaded`, `ranked`, `elapsed_ms`

**Container and deployment**
- Dockerfile with non-root user (`appuser`), `HEALTHCHECK` on `/v1/health`, and 4-worker uvicorn
- Pinned transitive dependency lock file (`requirements-lock.txt`) for reproducible installs
- CI pipeline (GitHub Actions): install from lock file, dataset validation, pytest, golden run

**Testing**
- 40 automated tests covering API endpoints, matching engine, integration, and metrics
- Golden run validator (`execution/run_match_local.py`) asserting deterministic ranking output
- Dataset validator (`execution/validate_sample_dataset.py`) gating corrupt CSV from CI

**Documentation**
- Operator runbook (`docs/runbook.md`): startup failure, health check failure, log inspection, known rate limiting limitation
- API contract directive (`directives/api_contract.md`): request/response schemas for all endpoints
- API usage examples (`docs/api_examples.md`)

### Known Limitations

- Rate limiting counters are process-local; effective limit is multiplied by worker count and instance count
- Alumni data is CSV-backed and in-memory; no database, no write path, no persistent storage
- No distributed tracing or external metrics aggregation
