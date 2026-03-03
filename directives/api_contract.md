# API Contract — Colaberry Nexus Matching Service
**Authoritative Contract for `/health` and `/match`**

Per `CLAUDE.md`: **implementation is authoritative**.  
This contract documents the current behavior of `src/api.py` + `src/matching_engine.py`.

If this document conflicts with code, **code wins** and this document must be updated.

---

## 1. Service Overview

This service provides:
- A health check endpoint for readiness validation
- A deterministic matching endpoint that ranks alumni profiles given a candidate request

Base URL (local): `http://localhost:8000`

---

## 2. Endpoint: `GET /health`

### Purpose
Used for health/readiness checks (local + Docker + CI smoke).

### Request
No body.

### Response (200)
```json
{ "status": "ok" }