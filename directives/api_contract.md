## Endpoint: GET /v1/version

### Purpose
Returns the service name, version string, and environment label. Used to confirm which build is running without inspecting container metadata.

### Authentication
None required. Public endpoint.

---

### Response Fields

| Field | Type | Present | Description |
|---|---|---|---|
| service | string | Always | Human-readable service name |
| version | string | Always | Version string from `SERVICE_VERSION` env var (default: `"0.1.0"`) |
| environment | string | Only if `ENVIRONMENT` env var is set | Deployment environment label (e.g. `"production"`, `"staging"`) |

---

### Example Request

```
GET /v1/version
```

### Example Response (without ENVIRONMENT set)

```json
{
  "service": "Colaberry Nexus AI Alumni Intelligence Platform",
  "version": "0.1.0"
}
```

### Example Response (with ENVIRONMENT=production)

```json
{
  "service": "Colaberry Nexus AI Alumni Intelligence Platform",
  "version": "0.1.0",
  "environment": "production"
}
```

---

## Endpoint: GET /v1/metrics

### Purpose
Returns cumulative in-process request counters since the last process start. Used for quick operational diagnostics.

### Authentication
None required. Public endpoint, same as `/v1/health`.

---

### Response Fields

| Field | Type | Description |
|---|---|---|
| requests_total | integer | Total requests handled by this process since start |
| requests_by_status | object | Request count keyed by HTTP status code (string keys) |
| errors_total | integer | Total requests with status code >= 400 |
| rate_limited_total | integer | Total requests rejected with 429 by this process |

---

### Example Request

```
GET /v1/metrics
```

### Example Response

```json
{
  "requests_total": 142,
  "requests_by_status": {"200": 138, "401": 3, "429": 1},
  "errors_total": 4,
  "rate_limited_total": 1
}
```

---

### Known Limitations

Counters are process-local and in-memory. With multiple uvicorn workers or multiple container instances, each process maintains its own independent counters. Counters reset to zero on process restart. See `docs/runbook.md` for details.

---

## Endpoint: POST /v1/match

### Purpose
Returns ranked alumni profiles matching the candidate's skills, interests, and location.

### Authentication
Requires API key in the request header.

```
x-api-key: <API_KEY>
```

---

### Request Body Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| skills | list[str] | No | Candidate skills to match against |
| interests | list[str] | No | Candidate interests to match against |
| location | string | No | Candidate location for location bonus |
| limit | integer | No | Maximum results returned (1–100) |
| offset | integer | No | Number of results to skip |

---

### Response Fields (per result)

| Field | Type | Description |
|-------|------|-------------|
| alumni_id | string | Unique alumni identifier |
| full_name | string | Alumni full name |
| email | string | Alumni email address |
| skills | list[str] | Alumni skills |
| interests | list[str] | Alumni interests |
| location | string | Alumni location |
| engagement_score | float | Normalized engagement score (0–1) |
| availability | string | Alumni availability status |
| total_score | float | Weighted ranking score (0–1) |
| confidence_score | float | Confidence score (equals total_score in v1) |
| matched_on | list[str] | Signals that contributed to the match: any of "skills", "interests", "location" |

---

### Example Request

```
POST /v1/match
x-api-key: <your-api-key>

{
  "skills": ["python"],
  "interests": ["mentorship"],
  "location": "NY"
}
```

---

### Example Response

```json
{
  "count": 1,
  "limit": null,
  "offset": 0,
  "results": [
    {
      "alumni_id": "A001",
      "full_name": "Alice Smith",
      "email": "alice@example.com",
      "skills": ["python", "sql"],
      "interests": ["mentorship"],
      "location": "NY",
      "engagement_score": 0.75,
      "availability": "mentor",
      "total_score": 0.65,
      "confidence_score": 0.65,
      "matched_on": ["skills", "interests", "location"]
    }
  ]
}
```

---

### Error Responses

#### 401 Unauthorized

```json
{
  "detail": "Invalid or missing API key"
}
```

---

## Endpoint: POST /v1/alumni

### Purpose
Creates a new alumni profile in the database. Requires a DB-backed deployment (`DATABASE_PATH` must be set and point to a seeded SQLite file). Returns 503 when the active data source is read-only (CSV mode).

### Authentication
Requires API key in the request header.

```
x-api-key: <API_KEY>
```

---

### Request Body Fields

| Field | Type | Required | Constraints |
|---|---|---|---|
| `alumni_id` | string | Yes | Non-empty after strip |
| `full_name` | string | Yes | Non-empty after strip |
| `email` | string | Yes | Must contain `@`; non-empty after strip |
| `skills` | list[string] | No (default `[]`) | Max 50 items; each item non-empty after strip; stored lowercase |
| `interests` | list[string] | No (default `[]`) | Max 50 items; each item non-empty after strip; stored lowercase |
| `location` | string | Yes | Non-empty after strip |
| `engagement_score` | float | Yes | `0.0 ≤ value ≤ 1.0` (pre-normalized; 0–100 scale not accepted) |
| `availability` | string | Yes | Non-empty after strip |

---

### Response (201 Created)

Returns the created `AlumniProfile` — the same shape as `GET /v1/alumni/{alumni_id}`.

```json
{
  "alumni_id": "A007",
  "full_name": "Grace Hopper",
  "email": "grace.hopper@example.com",
  "skills": ["python", "fortran"],
  "interests": ["education"],
  "location": "NY",
  "engagement_score": 0.85,
  "availability": "available"
}
```

---

### Error Responses

#### 401 Unauthorized — missing or wrong API key

#### 409 Conflict — alumni_id already exists

```json
{"error": {"code": 409, "message": "Conflict: alumni_id already exists", "request_id": "..."}}
```

#### 409 Conflict — email already exists

```json
{"error": {"code": 409, "message": "Conflict: email already exists", "request_id": "..."}}
```

#### 422 Validation Error — field constraint violated

#### 503 Service Unavailable — active repository is read-only (CSV mode)

```json
{"error": {"code": 503, "message": "CsvAlumniRepository is read-only. Set DATABASE_PATH to a seeded SQLite database to enable writes.", "request_id": "..."}}
```

---

## Endpoint: GET /v1/alumni/{alumni_id}

### Purpose
Returns a single alumni profile by ID.

### Authentication
Requires API key in the request header.

```
x-api-key: <API_KEY>
```

---

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| alumni_id | string | Yes | The unique identifier of the alumni profile |

---

### Example Request

```
GET /v1/alumni/A001
x-api-key: <your-api-key>
```

---

### Example Response

```json
{
  "alumni_id": "A001",
  "full_name": "Alice Smith",
  "email": "alice@example.com",
  "skills": ["python", "sql"],
  "interests": ["mentorship"],
  "location": "NY",
  "engagement_score": 0.75,
  "availability": "mentor"
}
```

---

### Error Responses

#### 401 Unauthorized

```json
{
  "detail": "Invalid or missing API key"
}
```

#### 404 Not Found

```json
{
  "detail": "Alumni not found"
}
```

---

## Endpoint: GET /v1/alumni

### Purpose
Returns alumni profiles from the dataset without ranking.

### Authentication
Requires API key in the request header.

```
x-api-key: <API_KEY>
```

---

### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| limit | integer | No | Maximum number of alumni profiles returned |
| offset | integer | No | Number of profiles to skip before returning results |

---

### Validation Rules

- `limit` must be between **1 and 100** when provided  
- `offset` must be **0 or greater**

---

### Example Request

```
GET /v1/alumni?limit=2&offset=0
x-api-key: <your-api-key>
```

---

### Example Response

```json
{
  "count": 2,
  "limit": 2,
  "offset": 0,
  "results": [
    {
      "alumni_id": "A001",
      "full_name": "Alice Smith",
      "email": "alice@example.com",
      "skills": ["python", "sql"],
      "interests": ["mentorship"],
      "location": "NY",
      "engagement_score": 0.75,
      "availability": "mentor"
    },
    {
      "alumni_id": "A002",
      "full_name": "Bob Johnson",
      "email": "bob@example.com",
      "skills": ["excel", "powerbi"],
      "interests": ["finance", "analytics"],
      "location": "CA",
      "engagement_score": 0.8,
      "availability": "mentor"
    }
  ]
}
```

---

### Error Responses

#### 401 Unauthorized

```json
{
  "detail": "Invalid or missing API key"
}
```

#### 422 Validation Error

Occurs when query parameters fail validation.

Example:

```json
{
  "detail": [
    {
      "loc": ["query", "offset"],
      "msg": "Input should be greater than or equal to 0",
      "type": "greater_than_equal"
    }
  ]
}
```