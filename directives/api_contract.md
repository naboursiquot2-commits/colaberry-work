# API Contract — Colaberry Nexus AI Alumni Intelligence Platform
**Authoritative Contract for `/health` and `/match`**

Per `CLAUDE.md`: **implementation is authoritative**.  
This contract documents the current behavior of `src/api.py` and `src/matching_engine.py`.

If this document conflicts with code, **the code wins**, and this document must be updated.

---

## 1. Service Overview

This service provides:

- A health check endpoint for readiness validation
- A deterministic alumni matching endpoint that ranks alumni profiles given a candidate request

Base URL (local):
