"""
execution/validate_sample_dataset.py

Validates data/sample_alumni.csv against required schema and data quality rules.

Checks performed:
    1. All required columns are present
    2. No blank alumni_id values
    3. No duplicate alumni_id values
    4. No blank full_name values
    5. No blank skills values
    6. No blank interests values
    7. engagement_score: blank or non-numeric values are allowed (loader treats
       them as 0.0); numeric values > 100 are rejected as out-of-range

Exit code 0 on PASS, 1 on FAIL.

Run:
    python execution/validate_sample_dataset.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path


def _repo_root() -> Path:
    # execution/ is one level below repo root
    return Path(__file__).resolve().parents[1]


REQUIRED_COLUMNS = {
    "alumni_id",
    "full_name",
    "email",
    "skills",
    "interests",
    "location",
    "engagement_score",
    "availability",
}


def validate(path: Path) -> list[str]:
    """
    Run all checks against the CSV at the given path.
    Returns a list of failure messages. An empty list means PASS.
    """
    failures: list[str] = []

    if not path.exists():
        return [f"File not found: {path}"]

    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        if reader.fieldnames is None:
            return ["CSV has no header row or is empty."]

        # Check 1 — required columns
        missing_columns = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing_columns:
            failures.append(f"Missing required columns: {sorted(missing_columns)}")
            return failures  # row-level checks cannot proceed without the columns

        rows = list(reader)

    # Check 2 — no blank alumni_id
    blank_ids = [i + 2 for i, r in enumerate(rows) if not r["alumni_id"].strip()]
    if blank_ids:
        failures.append(f"Blank alumni_id on row(s): {blank_ids}")

    # Check 3 — no duplicate alumni_id
    seen: dict[str, int] = {}
    for i, row in enumerate(rows):
        aid = row["alumni_id"].strip()
        if not aid:
            continue
        if aid in seen:
            failures.append(
                f"Duplicate alumni_id '{aid}' found on rows {seen[aid]} and {i + 2}"
            )
        else:
            seen[aid] = i + 2

    # Check 4 — no blank full_name
    blank_names = [i + 2 for i, r in enumerate(rows) if not r["full_name"].strip()]
    if blank_names:
        failures.append(f"Blank full_name on row(s): {blank_names}")

    # Check 5 — no blank skills
    blank_skills = [i + 2 for i, r in enumerate(rows) if not r["skills"].strip()]
    if blank_skills:
        failures.append(f"Blank skills on row(s): {blank_skills}")

    # Check 6 — no blank interests
    blank_interests = [i + 2 for i, r in enumerate(rows) if not r["interests"].strip()]
    if blank_interests:
        failures.append(f"Blank interests on row(s): {blank_interests}")

    # Check 7 — engagement_score range
    # Blank or non-numeric (e.g., "N/A") → loader converts to 0.0, allowed here.
    # Numeric value > 100 → out of any interpretable scale, fail.
    for i, row in enumerate(rows):
        raw = row["engagement_score"].strip()
        if not raw:
            continue  # blank → 0.0 by loader, allowed
        try:
            value = float(raw)
        except ValueError:
            continue  # non-numeric → 0.0 by loader, allowed
        if value > 100:
            failures.append(
                f"Row {i + 2}: engagement_score {raw!r} is numeric and > 100"
            )

    return failures


def main() -> int:
    path = _repo_root() / "data" / "sample_alumni.csv"

    print("\n=== Colaberry Nexus — Dataset Validation ===")
    print(f"File: {path}")
    print(f"Checks: columns, alumni_id (blank/duplicate), full_name, skills, "
          f"interests, engagement_score range")

    failures = validate(path)

    if failures:
        print(f"\nVALIDATION FAIL -- {len(failures)} issue(s) found:\n")
        for msg in failures:
            print(f"  - {msg}")
        print("\nExit code: 1")
        return 1

    print("\nVALIDATION PASS -- all checks passed.")
    print("Exit code: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
