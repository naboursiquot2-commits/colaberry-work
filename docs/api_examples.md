# API Usage Examples — Colaberry Nexus AI Alumni Intelligence Platform

---

## 1. Health Check

### Request

```bash
curl -X GET "http://localhost:8000/health"
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
curl -X POST "http://localhost:8000/match" \
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
      "confidence_score": 0.65
    }
  ]
}
```

---

## 3. Paginated Match Request

### Request

```bash
curl -X POST "http://localhost:8000/match" \
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
      "confidence_score": 0.505
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
      "confidence_score": 0.255
    }
  ]
}
```

---

## 4. Unauthorized Request Example

### Request

```bash
curl -X POST "http://localhost:8000/match" \
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