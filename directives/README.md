# Directives (Authoritative Docs)

This folder contains the **authoritative operating documents** for the Colaberry Nexus AI Alumni intelligence platform.

Per `CLAUDE.md`:
- Directives describe **intent + contract**
- Code + tests provide **deterministic verification**
- Any scoring/contract change must be reflected in:
  1) the directive docs here
  2) unit tests (`tests/`)
  3) deterministic golden run (`execution/run_match_local.py`)

## Files

### `matching_sop.md`
System-of-record for the deterministic ranking rules used by `src/matching_engine.py`.

### `api_contract.md`
System-of-record for the REST API behavior for:
- `GET /health`
- `POST /match`

Includes request/response schemas and error behavior.

## Validation (Definition of Done)
A change is considered “done” when:
- `python -m pytest -v` passes
- `python execution/run_match_local.py` returns PASS (exit code 0)
- Directive docs remain consistent with implementation