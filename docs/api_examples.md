# API Usage Examples — Colaberry Nexus AI Alumni Intelligence Platform

---

## 1. Health Check

### Request
```bash
curl -X GET "http://localhost:8000/v1/health"
```

### Response
```json
{
  "status": "ok"
}
```

---

## 2. Basic Match Request

### Request
```bash
curl -X POST "http://localhost:8000/v1/match" \
  -H "Content-Type: application/json" \
  -H "x-api-key: dev-secret-key" \
  -d '{
    "skills": ["python"],
    "interests": ["mentorship"],
    "location": "NY"
  }'
```

### Response
```json
{
  "count": 6,
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

## 3. Paginated Match Request

### Request
```bash
curl -X POST "http://localhost:8000/v1/match" \
  -H "Content-Type: application/json" \
  -H "x-api-key: dev-secret-key" \
  -d '{
    "skills": ["python"],
    "interests": ["mentorship"],
    "location": "NY",
    "limit": 2,
    "offset": 1
  }'
```

### Response
```json
{
  "count": 2,
  "limit": 2,
  "offset": 1,
  "results": [
    {
      "alumni_id": "A004",
      "full_name": "David Lee",
      "email": "david@example.com",
      "skills": ["python"],
      "interests": ["ai"],
      "location": "NY",
      "engagement_score": 0.9,
      "availability": "mentor",
      "total_score": 0.505,
      "confidence_score": 0.505,
      "matched_on": ["skills", "location"]
    },
    {
      "alumni_id": "A005",
      "full_name": "Eve Martinez",
      "email": "eve@example.com",
      "skills": ["sql"],
      "interests": ["mentorship"],
      "location": "FL",
      "engagement_score": 0.65,
      "availability": "available",
      "total_score": 0.255,
      "confidence_score": 0.255,
      "matched_on": ["interests"]
    }
  ]
}
```

---

## 4. Alumni Listing Endpoint

Returns alumni profiles without ranking scores.

### Request
```bash
curl -X GET "http://localhost:8000/v1/alumni?limit=2&offset=0" \
  -H "x-api-key: dev-secret-key"
```

### Response
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

## 5. Get Alumni by ID

### Request
```bash
curl -X GET "http://localhost:8000/v1/alumni/A001" \
  -H "x-api-key: dev-secret-key"
```

### Response
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

## 6. Unauthorized Request Example

### Request
```bash
curl -X POST "http://localhost:8000/v1/match" \
  -H "Content-Type: application/json" \
  -d '{
    "skills": ["python"]
  }'
```

### Response
```json
{
  "detail": "Invalid or missing API key"
}
```

---

## 7. Version Endpoint

Returns the service name, version, and optionally the environment. No API key required.

### Request
```bash
curl -X GET "http://localhost:8000/v1/version"
```

### Response (default, no ENVIRONMENT set)
```json
{
  "service": "Colaberry Nexus AI Alumni Intelligence Platform",
  "version": "0.1.0"
}
```

### Response (with ENVIRONMENT=production)
```json
{
  "service": "Colaberry Nexus AI Alumni Intelligence Platform",
  "version": "0.1.0",
  "environment": "production"
}
```

---

## 8. Metrics Endpoint

Returns cumulative in-process counters since the last process start. No API key required.

### Request
```bash
curl -X GET "http://localhost:8000/v1/metrics"
```

### Response
```json
{
  "requests_total": 142,
  "requests_by_status": {"200": 138, "401": 3, "429": 1},
  "errors_total": 4,
  "rate_limited_total": 1
}
```

---

## 9. Create Alumni (DB mode only)

Creates a new alumni profile. Requires `DATABASE_PATH` to point to a seeded SQLite database.

### Request
```bash
curl -X POST "http://localhost:8000/v1/alumni" \
  -H "Content-Type: application/json" \
  -H "x-api-key: dev-secret-key" \
  -d '{
    "alumni_id": "A007",
    "full_name": "Grace Hopper",
    "email": "grace.hopper@example.com",
    "skills": ["python", "fortran"],
    "interests": ["education"],
    "location": "NY",
    "engagement_score": 0.85,
    "availability": "available"
  }'
```

### Response (201 Created)
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

### Response — duplicate alumni_id (409 Conflict)
```json
{"error": {"code": 409, "message": "Conflict: alumni_id already exists", "request_id": "..."}}
```

### Response — CSV mode (503 Service Unavailable)
```json
{"error": {"code": 503, "message": "CsvAlumniRepository is read-only. Set DATABASE_PATH to a seeded SQLite database to enable writes.", "request_id": "..."}}
```

---

## 10. Update Alumni (DB mode only)

Fully replaces the mutable fields of an existing alumni profile. `alumni_id` comes from the URL — do not include it in the request body.

### Request
```bash
curl -X PUT "http://localhost:8000/v1/alumni/A001" \
  -H "Content-Type: application/json" \
  -H "x-api-key: dev-secret-key" \
  -d '{
    "full_name": "Alice Smith-Jones",
    "email": "alice.updated@example.com",
    "skills": ["python", "sql", "machine learning"],
    "interests": ["mentorship", "coaching"],
    "location": "NY",
    "engagement_score": 0.90,
    "availability": "limited"
  }'
```

### Response (200 OK)
```json
{
  "alumni_id": "A001",
  "full_name": "Alice Smith-Jones",
  "email": "alice.updated@example.com",
  "skills": ["python", "sql", "machine learning"],
  "interests": ["mentorship", "coaching"],
  "location": "NY",
  "engagement_score": 0.9,
  "availability": "limited"
}
```

### Response — not found (404)
```json
{"error": {"code": 404, "message": "Alumni not found", "request_id": "..."}}
```

### Response — email conflict (409)
```json
{"error": {"code": 409, "message": "Conflict: email already exists", "request_id": "..."}}
```

### Response — alumni_id in body (422)
```json
{"error": {"code": 422, "message": "Validation error", "request_id": "..."}}
```

### Response — CSV mode (503)
```json
{"error": {"code": 503, "message": "CsvAlumniRepository is read-only. Set DATABASE_PATH to a seeded SQLite database to enable writes.", "request_id": "..."}}
```

---

## Interactive API Documentation

Open in your browser:

```
http://localhost:8000/docs
```