# Colaberry Nexus AI Alumni Intelligence Platform

Backend matching service that ranks alumni mentors against learner requests using a deterministic scoring engine, with production-ready API architecture, observability, testing, and CI/CD.

---

## Overview

Nexus AI is a backend matching service that ranks Colaberry alumni mentors against learner requests using a deterministic scoring engine. Candidates are scored across skills, interests, location, and engagement signals — producing consistent, auditable results with no LLM involvement in the ranking logic.

The service includes production-ready backend features:

- Database-backed alumni storage with full CRUD write API (POST, PUT, DELETE)
- Per-user API key management: issuance, rotation, and revocation
- Schema migrations with version tracking and rollback safety
- API key authentication (env-var or database-backed with scrypt hashing)
- Pagination (limit / offset) on all list endpoints
- Structured JSON logging
- Request ID tracing (X-Request-ID)
- Rate limiting per API key (configurable sliding window)
- Structured error responses
- Health readiness endpoint (`/v1/health`)
- In-process metrics endpoint (`/v1/metrics`)
- Service version endpoint (`/v1/version`)
- Explainable match results (`matched_on`)
- Automated testing with pytest (280 tests across 14 test files)
- Continuous Integration with GitHub Actions
- Docker container support with pinned dependency lock file

---

## Architecture Overview

The system is structured as a layered pipeline:

**Client → API Gateway → Middleware → Matching Engine → Data Layer → Response**

### API Gateway (FastAPI)
- Routing and validation
- Versioned endpoints (`/v1`)
- API key authentication
- OpenAPI / Swagger documentation

### Middleware
- Request ID tracing
- Structured JSON logging
- Rate limiting per API key
- Structured error handling

### Matching Engine
Deterministic scoring using:
- Skills overlap
- Interests overlap
- Location match
- Engagement score

Produces fully auditable and reproducible results with no LLM involvement.

### Data Layer
- SQLite-backed alumni storage with full CRUD support (default when `DATABASE_PATH` is set)
- CSV fallback loader for local development when `DATABASE_PATH` is unset or file is absent
- Schema migrations managed by `execution/migrate_database.py` (current version: 4)

### Response Layer
Returns ranked results with:
- `confidence_score`
- `matched_on` (explainability signals)

---

## Explainability

Every match result includes a `matched_on` field that identifies which scoring signals contributed to that candidate's ranking.

Supported signals:
- skills
- interests
- location

This makes the ranking transparent and fully auditable — no black-box scoring.

### Example Result

```json
{
  "alumni_id": "A042",
  "confidence_score": 0.85,
  "matched_on": ["skills", "interests", "location"]
}
Observability and Production Features
Feature	Detail
Structured logging	JSON logs for all requests
Request ID tracing	X-Request-ID returned and logged
Rate limiting	Per API key throttling
Structured errors	Standard error response format
Health endpoint	/v1/health readiness check
CI/CD	Tests run on every push
Test coverage	Coverage enforced in CI
Runbook
Prerequisites
Python 3.11+
Git
Virtual environment support
Optional: Docker
Setup

Clone the repository:

git clone https://github.com/naboursiquot2-commits/colaberry-work.git
cd colaberry-work

Create a virtual environment:

python -m venv .venv

Activate the virtual environment:

.venv\Scripts\activate

Install dependencies (use the lock file for reproducible installs):

pip install -r requirements-lock.txt
Environment Configuration

Copy `.env.example` to `.env` and populate the values. The only required variable is `API_KEY`.

Example configuration:

API_KEY=dev-secret-key
DATA_PATH=data/sample_alumni.csv
DATABASE_PATH=data/alumni.db

Notes:

.env files should never be committed
API_KEY is required — the application will not start without it
DATABASE_PATH enables the SQLite data layer and all write endpoints (alumni CRUD, key management)
See .env.example for all available variables and their defaults
Running the API

Start the FastAPI development server:

uvicorn src.api:app --reload

The API will run at:

http://localhost:8000

Documentation:

http://localhost:8000/docs
http://localhost:8000/redoc
API Endpoints

All endpoints except `/v1/health`, `/v1/metrics`, and `/v1/version` require the `x-api-key` header. Write endpoints (POST, PUT, DELETE) require a DB-backed deployment (`DATABASE_PATH` must be set).

**System**

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| GET | `/v1/health` | Service readiness — returns `profiles_loaded` count | No |
| GET | `/v1/metrics` | In-process request counters since last start | No |
| GET | `/v1/version` | Service name, version, and environment label | No |

**Alumni**

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| GET | `/v1/alumni` | List alumni profiles (paginated) | Yes |
| GET | `/v1/alumni/{alumni_id}` | Get a single alumni profile | Yes |
| POST | `/v1/alumni` | Create a new alumni profile (DB mode) | Yes |
| PUT | `/v1/alumni/{alumni_id}` | Replace an alumni profile (DB mode) | Yes |
| DELETE | `/v1/alumni/{alumni_id}` | Remove an alumni profile (DB mode) | Yes |

**Matching**

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| POST | `/v1/match` | Rank alumni mentors for a candidate | Yes |

**Key Management** (DB mode only)

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| POST | `/v1/users` | Create a named user account | Yes |
| POST | `/v1/users/{user_id}/keys` | Issue an API key for a user | Yes |
| GET | `/v1/keys` | List active keys for the authenticated caller | Yes |
| DELETE | `/v1/keys/{key_id}` | Revoke an API key | Yes |

Example Requests
Health Check
curl -X GET http://localhost:8000/v1/health
Match Alumni Mentors
curl -X POST http://localhost:8000/v1/match \
-H "Content-Type: application/json" \
-H "x-api-key: dev-secret-key" \
-d '{
  "skills": ["python"],
  "interests": ["mentorship"],
  "location": "NY"
}'
Paginated Match Request
curl -X POST http://localhost:8000/v1/match \
-H "Content-Type: application/json" \
-H "x-api-key: dev-secret-key" \
-d '{
  "skills": ["python"],
  "interests": ["mentorship"],
  "location": "NY",
  "limit": 2,
  "offset": 1
}'
Alumni Listing
curl -X GET "http://localhost:8000/v1/alumni?limit=2&offset=0" \
-H "x-api-key: dev-secret-key"
Common Commands

Run all tests:

python -m pytest

Run tests with verbose output:

python -m pytest -v

Run only API tests:

python -m pytest tests/test_api.py

Run only matching engine tests:

python -m pytest tests/test_matching_engine.py
Docker

Build the container:

docker build -t alumni-api .

Run the container:

docker run -e API_KEY=your-secret-key -p 8000:8000 alumni-api

To enable the SQLite data layer and write endpoints:

docker run -e API_KEY=your-secret-key -e DATABASE_PATH=/app/data/alumni.db -p 8000:8000 alumni-api

Access documentation:

http://localhost:8000/docs

For troubleshooting startup failures, health check failures, and log inspection, see [docs/runbook.md](docs/runbook.md).

Continuous Integration

This repository includes a GitHub Actions CI pipeline that:

Installs dependencies from the pinned lock file
Validates the alumni CSV dataset
Validates schema migrations against both a fresh database and a legacy-upgrade path
Runs the full pytest test suite (280 tests)
Runs the deterministic golden-run validator
Runs a seeded DB-mode test pass

This ensures new changes do not break existing features, and that migrations and data integrity are verified on every push.

Project Structure
colaberry-work
│
├── src/
│   ├── api.py                     ← FastAPI app, all route handlers, Pydantic models
│   ├── api_key_repository.py      ← DB-backed API key management (users + keys)
│   ├── matching_engine.py         ← Deterministic scoring engine
│   ├── repository.py              ← Alumni data access (CSV + SQLite implementations)
│   └── db.py                      ← SQLite alumni loader
│
├── tests/                         ← 280 tests across 14 files
│   ├── test_api.py
│   ├── test_api_alumni_create.py
│   ├── test_api_alumni_update.py
│   ├── test_api_alumni_delete.py
│   ├── test_api_db_auth.py
│   ├── test_api_db_loader.py
│   ├── test_api_integration.py
│   ├── test_api_key_management.py ← Phase 2 key management tests (40 tests)
│   ├── test_api_key_repository.py
│   ├── test_db.py
│   ├── test_matching_engine.py
│   ├── test_migrations.py
│   ├── test_repository.py
│   └── test_seed_database.py
│
├── execution/
│   ├── migrate_database.py        ← Schema migration runner (CLI + library)
│   ├── seed_database.py           ← Alumni CSV → SQLite seeder
│   ├── migrations/                ← SQL migration files (0001–0004)
│   ├── run_match_local.py         ← Deterministic golden-run validator
│   └── validate_sample_dataset.py ← CSV schema and integrity validator
│
├── data/
│   └── sample_alumni.csv
│
├── docs/
│   ├── runbook.md                 ← Operator runbook (startup, health, key management)
│   └── api_examples.md
│
├── directives/
│   └── api_contract.md
│
├── .github/workflows/
│   └── ci.yml
│
├── .env.example
├── Dockerfile
├── requirements.txt
├── requirements-lock.txt
└── README.md
Future Improvements
Redis-backed rate limiting (replace in-memory per-process counters)
Prometheus metrics endpoint for external scraping
Semantic skill matching via embedding similarity
Machine learning ranking models with feedback loops
Multi-tenant alumni pools with per-tenant API key namespacing
Cloud deployment and distributed tracing (OpenTelemetry)
Notes
API authentication uses the x-api-key header
In DB-backed mode, keys are stored as scrypt hashes and never in plaintext
Pagination uses limit and offset on all list endpoints
Alumni data is SQLite-backed in production; CSV fallback is available for local development
Match results include explainability via matched_on
The ranking engine is deterministic and fully auditable — no LLM involvement in scoring
License

This project is for educational and portfolio demonstration purposes.

See [CHANGELOG.md](CHANGELOG.md) for a summary of completed milestones and known limitations.


