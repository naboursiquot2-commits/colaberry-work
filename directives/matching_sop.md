# Matching Engine Standard Operating Procedure (SOP)
**Colaberry Nexus — Matching Service (Deterministic Engine Contract)**

## 1. Purpose
This SOP defines the **authoritative, deterministic** matching rules used to rank alumni profiles for a given candidate request.

Per `CLAUDE.md`: **Implementation is authoritative**. This SOP documents what the current engine does. Any future scoring change must update this SOP **and** be validated by tests + the deterministic golden run.

---

## 2. Scope / Authority
This document is the behavioral contract for:
- `src/matching_engine.py` (ranking logic)
- `src/api.py` (`POST /match` request schema + response behavior)
- `execution/run_match_local.py` (deterministic “golden run” validation)

If this SOP conflicts with the code, **the code wins**, and this SOP must be updated to match.

---

## 3. Inputs (Contracts)

### 3.1 Candidate Request (API input)
The engine expects a request dictionary with:

Required:
- `skills`: `list[str]`
- `interests`: `list[str]`

Optional:
- `location`: `str`

Example:
```json
{
  "skills": ["python", "sql"],
  "interests": ["mentorship", "data"],
  "location": "NY"
}