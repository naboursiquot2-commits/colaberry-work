# Architecture and Roadmap — Colaberry Nexus AI Alumni Intelligence Platform

---

## Current System Architecture

### API Layer (`src/api.py`)

FastAPI 0.131 service exposing four versioned routes under `/v1`:

| Route | Auth | Purpose |
|---|---|---|
| `GET /v1/health` | None | Readiness probe — returns `profiles_loaded` count |
| `GET /v1/metrics` | None | In-process request counters since last start |
| `POST /v1/match` | API key | Rank alumni against a candidate request |
| `GET /v1/alumni` | API key | Paginated alumni listing |
| `GET /v1/alumni/{id}` | API key | Single alumni profile |

The app object is a single FastAPI instance. Routes are grouped under an `APIRouter` with a `/v1` prefix. Startup is managed via a lifespan context manager that loads the alumni dataset before the first request is served.

---

### Middleware Stack

Two middleware layers applied to every request, in registration order:

1. **Request ID middleware** — assigns or echoes `X-Request-ID`, times the request, emits a structured JSON access log line (`method`, `path`, `status_code`, `elapsed_ms`), increments in-process counters.
2. **Rate limit middleware** — sliding window per API key, in-memory, configurable via `RATE_LIMIT_MAX` and `RATE_LIMIT_WINDOW` env vars. Returns 429 on breach.

Both middleware layers are process-local. State is not shared across workers or instances.

---

### Matching Engine (`src/matching_engine.py`)

Stateless, deterministic scoring function. No LLM involvement.

**Scoring formula (v1):**
```
total_score =
    0.45 × Jaccard(request_skills,    alumni_skills)
  + 0.25 × Jaccard(request_interests, alumni_interests)
  + 0.10 × location_bonus             (1.0 if exact match, else 0.0)
  + 0.20 × engagement_score           (normalized 0–1)
```

Output is a ranked list sorted descending by `total_score`. Each result includes `matched_on` — the subset of signals (`skills`, `interests`, `location`) that contributed a non-zero score. Fully auditable: same inputs always produce the same ranking.

---

### Data Layer

- **Source:** `data/sample_alumni.csv` — 8-column CSV (alumni_id, full_name, email, skills, interests, location, engagement_score, availability)
- **Load:** Single read at startup via `load_alumni_profiles_csv()`, parsed into a list of dicts
- **Cache:** Stored in `app.state.profiles` (in-memory, per-process)
- **Write path:** None. The service is read-only against the dataset.
- **Validation:** `execution/validate_sample_dataset.py` runs in CI and checks schema, duplicates, and value ranges before tests execute.

---

### Observability

| Signal | Mechanism | Queryable? |
|---|---|---|
| Per-request access log | JSON stdout via `python-json-logger` | Only via log aggregation |
| Match event log | JSON stdout (`profiles_loaded`, `ranked`, `elapsed_ms`) | Only via log aggregation |
| Request ID tracing | `X-Request-ID` header, propagated through `ContextVar` | Per-request correlation |
| Readiness | `GET /v1/health` | Yes — curl or orchestrator probe |
| Counters | `GET /v1/metrics` (in-process) | Yes — curl |

No external metrics backend. No distributed tracing. No alert rules.

---

### Deployment

- **Runtime:** Uvicorn with `--workers 4`, `--log-level info`
- **Container:** `python:3.12-slim`, non-root user (`appuser`), `HEALTHCHECK` on `/v1/health` every 30s
- **Configuration:** Environment variables (`API_KEY` required, `DATA_PATH`, `RATE_LIMIT_MAX`, `RATE_LIMIT_WINDOW`)
- **Startup guard:** Application raises `ValueError` and exits if `API_KEY` is unset
- **Dependencies:** Pinned via `requirements-lock.txt` (29 packages); CI installs from lock file
- **CI:** GitHub Actions — lock install → dataset validation → pytest (40 tests) → golden run

---

## Current Limitations

### CSV Data Store
Alumni data lives in a static file baked into the container image. There is no write path, no versioning, no audit trail, and no way to update records without a full redeploy. At current scale (6 profiles) this is acceptable; it becomes operationally untenable as the alumni count grows.

### In-Memory Rate Limiting
Rate limit counters are per-process. With 4 uvicorn workers, the effective limit is `RATE_LIMIT_MAX × 4`. With multiple container instances, it multiplies further. Counters reset on any restart. The feature provides courtesy throttling but not a hard abuse-prevention boundary.

### Single-Service Architecture
All concerns (routing, auth, matching logic, data access) live in one Python process. There is no separation between the API surface and the matching computation. This is appropriate for current load but limits independent scaling and deployment of components.

### API Key Authentication Only
Authentication is a single shared secret per deployment. There is no per-user identity, no token expiry, no rotation mechanism beyond redeployment, and no audit log associating requests to specific callers.

### In-Process Metrics
`/v1/metrics` counters are per-process and reset on restart. An external monitoring system cannot scrape a consistent, aggregated view of request volume or error rates across workers or instances.

---

## Short-Term Roadmap (Next 3 Improvements)

### 1. Redis-Backed Rate Limiting
Replace `_rate_limit_counts` dict with a Redis sliding window counter. This makes rate limiting consistent across all workers and container instances without changing the external API behavior. Requires adding a `redis` client dependency and a `REDIS_URL` env var. The in-memory fallback can be retained for local development when Redis is absent.

### 2. Database-Backed Alumni Storage
Replace CSV loading with a SQL read path (SQLite for dev, PostgreSQL for production). Introduces a write API for creating and updating alumni records, removes the need to redeploy for data changes, and enables filtering, indexing, and pagination at the data layer. Alembic handles schema migrations. The matching engine interface (`list[dict]`) does not change.

### 3. Prometheus Metrics Endpoint
Add `prometheus_client` and expose `GET /metrics` in Prometheus text format alongside the existing `/v1/metrics` JSON endpoint. Enables scraping by Prometheus/Grafana without log parsing. Key counters to instrument: `http_requests_total` (by method, path, status), `http_request_duration_seconds` (histogram), `match_duration_seconds`.

---

## Medium-Term Roadmap (Architecture Changes)

**Per-caller API keys with a key registry**
Move from a single shared `API_KEY` to a key-per-caller model backed by a database table. Each key carries an identity, creation date, and optional expiry. Enables request attribution, per-key rate limits, and key revocation without redeployment.

**Separate matching worker**
Extract `rank_alumni()` into a standalone service or async task queue (e.g., Celery + Redis or a simple job queue). The API tier enqueues match requests and returns a job ID; clients poll or receive a webhook. This decouples API latency from computation time and enables independent scaling of the matching layer.

**Structured alumni data model**
Replace free-text skill and interest strings with a controlled vocabulary backed by a reference table. Enables fuzzy/semantic matching, synonym resolution, and aggregation reporting (e.g., "top 10 skills across all alumni").

**Secrets management integration**
Replace env-var secret injection with a secrets manager (AWS Secrets Manager, HashiCorp Vault, or equivalent). API keys and database credentials fetched at startup, not baked into environment at deploy time.

---

## Long-Term Vision

The platform evolves from a read-only matching API into a full alumni relationship management system:

- **Alumni self-service:** Alumni maintain their own profiles via an authenticated write API; availability and skills stay current without manual CSV exports.
- **Candidate feedback loop:** Match results are rated by candidates and recruiters; scores feed back into engagement and relevance weights over time.
- **Semantic matching:** Skill and interest overlap computed via embedding similarity rather than exact Jaccard, enabling cross-domain and adjacent-skill matching.
- **Multi-tenant deployment:** Separate alumni pools and rate limits per organization, with per-tenant API key namespacing.
- **Observability platform:** Full distributed tracing (OpenTelemetry), Grafana dashboards for match latency and error rates, alerting on SLA breaches.

The deterministic scoring engine and auditable `matched_on` field are intentional design choices that remain load-bearing as the system grows — explainability should not be traded away for ML opacity.
