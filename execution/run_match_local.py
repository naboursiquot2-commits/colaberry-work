"""
execution/run_match_local.py

Local deterministic "golden run" for the matching engine.

What it does:
- Loads a fixed request + expected outputs from execution/golden_output.json
- Loads alumni profiles from data/sample_alumni.csv
- Runs rank_alumni(request, profiles)
- Validates:
    1) ranked alumni_id order equals expected_ranking_order
    2) top total_score ~= expected_top_score (tolerance)
- Prints a readable report and exits non-zero if validation fails

Run:
    python execution/run_match_local.py

Notes (Windows):
- We add the repo root to sys.path so `import src...` works from /execution.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    # execution/ is one level below repo root
    return Path(__file__).resolve().parents[1]


def _add_repo_root_to_syspath() -> None:
    root = _repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _approx_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def main() -> int:
    _add_repo_root_to_syspath()

    # Local imports after sys.path fix
    try:
        from src.matching_engine import load_alumni_profiles_csv, rank_alumni
    except Exception as e:
        print("FAIL: Could not import matching engine from src/")
        print(f"Error: {e}")
        print("\nTip: Run this from repo root with:")
        print("  python execution/run_match_local.py")
        return 1

    root = _repo_root()
    golden_path = root / "execution" / "golden_output.json"
    csv_path = root / "data" / "sample_alumni.csv"

    if not golden_path.exists():
        print(f"FAIL: Missing golden file: {golden_path}")
        return 1

    if not csv_path.exists():
        print(f"FAIL: Missing CSV file: {csv_path}")
        return 1

    golden = _load_json(golden_path)

    # Required keys
    required_keys = {"request", "expected_ranking_order", "expected_top_score"}
    missing = required_keys - set(golden.keys())
    if missing:
        print(f"FAIL: golden_output.json missing keys: {sorted(missing)}")
        return 1

    request = golden["request"]
    expected_order = golden["expected_ranking_order"]
    expected_top_score = float(golden["expected_top_score"])

    print("\n=== Colaberry Nexus — Local Match Run (Golden Validation) ===")
    print(f"Repo root: {root}")
    print(f"Golden:    {golden_path}")
    print(f"CSV:       {csv_path}")
    print(f"Request:   {request}")

    profiles = load_alumni_profiles_csv(str(csv_path))
    results = rank_alumni(request, profiles)

    print(f"\nProfiles loaded:   {len(profiles)}")
    print(f"Results returned:  {len(results)}")

    # Print ranked results (compact)
    for i, r in enumerate(results, start=1):
        alumni_id = r.get("alumni_id", "?")
        name = r.get("full_name", r.get("name", ""))
        loc = r.get("location", "")
        total = r.get("total_score", None)
        engage = r.get("engagement_score", None)
        print(f"{i:>2}. {name} (id={alumni_id}, loc={loc}) total_score={total:.4f} engagement={engage}")

    # ---- VALIDATION ----
    failures: list[str] = []

    actual_order = [r.get("alumni_id") for r in results]
    if actual_order != expected_order:
        failures.append(
            "Ranking order mismatch.\n"
            f"  expected: {expected_order}\n"
            f"  actual:   {actual_order}"
        )

    if not results:
        failures.append("No results returned (cannot validate top score).")
    else:
        actual_top_score = float(results[0].get("total_score", 0.0))
        # Use a slightly looser tolerance for float math
        if not _approx_equal(actual_top_score, expected_top_score, tol=1e-4):
            failures.append(
                "Top score mismatch.\n"
                f"  expected_top_score: {expected_top_score:.4f}\n"
                f"  actual_top_score:   {actual_top_score:.4f}"
            )

    if failures:
        print("\n❌ GOLDEN VALIDATION: FAIL")
        for msg in failures:
            print("\n" + msg)
        print("\nExit code: 1")
        return 1

    print("\n✅ GOLDEN VALIDATION: PASS")
    print("Exit code: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())