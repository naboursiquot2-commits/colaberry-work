# execution/

Deterministic scripts used for data validation, golden-run verification, and database seeding.
Each script has one responsibility and is safe to rerun.

---

## Scripts

### validate_sample_dataset.py

Validates `data/sample_alumni.csv` against schema and data quality rules.
Run in CI before tests.

```bash
python execution/validate_sample_dataset.py
```

Exit code 0 on pass, 1 on failure.

---

### run_match_local.py

Loads the sample CSV and runs the matching engine against a fixed request defined in
`execution/golden_output.json`. Validates ranking order and top score against expected
values. Run in CI after tests.

```bash
python execution/run_match_local.py
```

Exit code 0 on pass, 1 on failure.

---

### seed_database.py

Seeds a SQLite database from the alumni CSV source. Idempotent: safe to run multiple times.

```bash
# Default paths (data/sample_alumni.csv → data/alumni.db)
python execution/seed_database.py

# Custom paths
python execution/seed_database.py --csv data/sample_alumni.csv --db data/alumni.db
```

The generated `data/alumni.db` file is excluded from version control (see `.gitignore`).

**Normalization applied** (identical to the CSV data loader):
- `skills` and `interests`: comma-split, lowercased, stripped, stored as JSON arrays
- `engagement_score`: values in 0–100 range are divided by 100; `"N/A"` and blank become `0.0`

**Idempotency:** uses `INSERT OR REPLACE` keyed on `alumni_id` (primary key). Running the
script any number of times always produces the same final database state.
