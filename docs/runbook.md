# Operator Runbook — Colaberry Nexus AI Alumni Intelligence Platform

Triage guide for common operational failures.
Each scenario: symptom → confirm → fix.

---

## 1. Application Fails to Start — API_KEY Missing

**Symptom:** Container exits immediately after launch. No HTTP traffic is served.

**Confirm:**
```bash
docker logs <container-name>
```

Look for:
```
ValueError: API_KEY environment variable is required and must not be empty
```

**Fix:** Pass the key at runtime:
```bash
docker run -e API_KEY=<your-key> -p 8000:8000 alumni-api
```

In a compose file or task definition, ensure `API_KEY` is injected via secrets. There is no fallback default — the application will not start without it.

---

## 2. Container HEALTHCHECK Fails

**Symptom:** `docker ps` shows `(unhealthy)`. Orchestrators stop routing traffic or restart the container.

**Confirm:**
```bash
# Full health state and last probe result
docker inspect --format='{{json .State.Health}}' <container-name>

# Manual probe
curl -s http://localhost:8000/v1/health
```

The HEALTHCHECK probes `/v1/health` every 30 seconds, times out after 5 seconds, and marks the container unhealthy after 3 consecutive failures. The start period is 15 seconds.

**Common causes:**

| Cause | Signal | Fix |
|---|---|---|
| API_KEY not set | Container exits before first probe | See Scenario 1 |
| DB or CSV missing / unreadable | `/v1/health` returns 503 | See Scenario 3 |
| Port mismatch | Connection refused during probe | Confirm `-p 8000:8000` or correct port mapping |

---

## 3. /v1/health Returns Unhealthy or profiles_loaded Is 0

**Symptom:** `GET /v1/health` returns HTTP 503, or HTTP 200 with `"profiles_loaded": 0`.

**Confirm:**
```bash
curl -s http://localhost:8000/v1/health
```

Healthy:
```json
{"status": "ok", "profiles_loaded": 6}
```

Unhealthy (503):
```json
{"status": "error", "detail": "profiles not loaded"}
```

**Container default:** The image sets `DATABASE_PATH=/app/data/alumni.db` via `ENV` and seeds that file at build time. On startup the API loads alumni from SQLite. If `DATABASE_PATH` is overridden to a path that does not exist, the API falls back to the CSV at `DATA_PATH` automatically.

**Diagnose:**
```bash
# Check what DATABASE_PATH and DATA_PATH the container sees
docker inspect --format='{{range .Config.Env}}{{println .}}{{end}}' <container-name> | grep -E 'DATABASE_PATH|DATA_PATH'

# Confirm the DB and CSV files exist inside the container
docker exec <container-name> ls -la data/

# Run the dataset validator locally
python execution/validate_sample_dataset.py
```

**Fix:** If `DATABASE_PATH` was overridden to a missing path, unset the override so the image default is used:
```bash
docker run \
  -e API_KEY=<your-key> \
  -p 8000:8000 alumni-api
```

The baked-in DB (`/app/data/alumni.db`) will load automatically. The CSV at `DATA_PATH` is also present in the image as a fallback.

---

## 4. Inspecting Logs and Verifying the Running Container

All requests, errors, and match events are emitted as structured JSON on stdout.

**Container status:**
```bash
docker ps -a
```

**Stream logs live:**
```bash
docker logs -f <container-name>
```

**Last 50 lines:**
```bash
docker logs --tail 50 <container-name>
```

**Filter for errors only:**
```bash
docker logs <container-name> 2>&1 | grep '"levelname": "ERROR"'
```

**Inspect environment variables:**
```bash
docker inspect --format='{{range .Config.Env}}{{println .}}{{end}}' <container-name>
```

**Test authentication:**
```bash
curl -s -o /dev/null -w "%{http_code}" \
  -H "x-api-key: <your-key>" \
  http://localhost:8000/v1/alumni
```

Expected: `200`. If `401`, the key supplied does not match the `API_KEY` the container was started with.

---

## Known Limitations — Rate Limiting

Rate limiting is implemented in-memory, local to each uvicorn worker process.

**How it works:** Each worker maintains its own request counter per API key. Counters are never shared between processes or containers.

**Consequences by deployment type:**

| Deployment | Effective rate limit | Notes |
|---|---|---|
| 1 container, 1 worker | `RATE_LIMIT_MAX` (60 req/min) | Fully effective |
| 1 container, 4 workers (current Dockerfile) | ~240 req/min | Each worker allows the full limit independently |
| 2+ containers, 4 workers each | ~240 × N req/min | Multiplies with every additional instance |
| Container restart | Counters reset to zero | A burst immediately after restart is not rate-limited |

**What this means in practice:** Rate limiting will reliably block accidental overuse from a single client on a single worker. It will not reliably prevent a determined client from exceeding the configured threshold across workers or instances.

**Acceptable for:** Local development, demos, and single-process deployments where rate limiting is a courtesy control, not a hard security boundary.

**Not acceptable for:** Production deployments where rate limiting is a required abuse-prevention or billing control. In that case, replace `_rate_limit_counts` with a shared Redis-backed sliding window.

---

## 5. Running Database Migrations

Schema migrations are managed by `execution/migrate_database.py`. They run automatically when `seed_database.py` is called, but can also be run explicitly.

**Apply all pending migrations (interactive / CI):**
```bash
python execution/migrate_database.py
python execution/migrate_database.py --db data/alumni.db
```

Exits 0 on success (including "already up to date"). Exits 1 on failure with a message identifying the failing migration file.

**Check the current schema version:**
```bash
sqlite3 data/alumni.db "SELECT version, description, applied_at FROM schema_version ORDER BY version;"
```

**Seed a fresh database (runs migrations automatically):**
```bash
python execution/seed_database.py
```

**Legacy database upgrade** (database created before migration support was added): run `migrate_database.py` once. It detects the pre-existing `alumni` table, creates `schema_version`, and stamps it at the current version without modifying any data.

---

## First Three Commands During Any Triage

```bash
docker ps -a                                      # is the container running or exited?
docker logs --tail 50 <container-name>            # what happened at startup or last failure?
curl -s http://localhost:8000/v1/health           # is the service responding and data loaded?
```

For a quick count of errors and rate-limited requests since the last process start:

```bash
curl -s http://localhost:8000/v1/metrics
```

Returns `requests_total`, `requests_by_status`, `errors_total`, and `rate_limited_total`. No API key required. Counters are per-process and reset on restart — see Known Limitations above.
