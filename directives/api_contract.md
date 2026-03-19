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
x-api-key: dev-secret-key
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
x-api-key: dev-secret-key
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