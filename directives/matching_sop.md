# Matching Engine Standard Operating Procedure (SOP)

## 1. Purpose

Define deterministic rules for alumni-to-candidate matching using weighted Jaccard similarity.

This document is the authoritative behavioral contract for:

- `src/matching_engine.py`
- `/match` API endpoint
- CLI execution scripts

---

## 2. Input Contract

### Candidate Request

- `skills`: List[str]
- `industries`: List[str]
- `experience_years`: int

### Alumni Profile (CSV row)

- `name`
- `skills`
- `industry`
- `years_experience`

---

## 3. Validation Rules

- Skills must be non-empty list
- Industries must be non-empty list
- Experience must be >= 0
- CSV rows must contain required columns
- Empty or malformed rows are ignored

Invalid API input returns HTTP 422.

---

## 4. Scoring Algorithm

Weighted Jaccard Similarity:

Score =  
( SkillOverlapWeight * Jaccard(skills) )  
+ ( IndustryMatchWeight * binary_match )  
+ ( ExperienceWeight * normalized_experience_score )

### Default Weights

- Skills: 0.6
- Industry: 0.3
- Experience: 0.1

---

## 5. Determinism Guarantee

- No randomness allowed
- Identical inputs must produce identical outputs
- Ranking must be stable
- Floating point rounding consistent to 4 decimals

---

## 6. Performance Constraint

- 1,000 alumni profiles processed in < 2 seconds
- Complexity target: O(N)

---

## 7. Logging Requirements

- Log request size
- Log execution duration
- Do not log PII beyond first name

---

## 8. Error Handling

- Missing CSV file → 500
- Invalid schema → 422
- Empty dataset → return empty ranked list

---

## 9. Validation Authority

This document supersedes ad-hoc logic changes.
Any scoring modification must update this SOP.