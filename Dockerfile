FROM python:3.12-slim

WORKDIR /app

COPY requirements-lock.txt .
RUN pip install --no-cache-dir -r requirements-lock.txt

COPY src/ ./src/
COPY data/ ./data/
COPY execution/ ./execution/

# Phase 1: apply all pending schema migrations.
# Creates the alumni and schema_version tables on a fresh build; upgrades
# existing databases on a rebuild.  Runs before seeding so the schema is
# always current before any data is written.
RUN python execution/migrate_database.py

# Phase 2: upsert alumni data from the CSV source.
# migrate_database.py already ran above, so the migrate() call inside seed()
# is a no-op here — it just confirms the schema is current.
RUN python execution/seed_database.py

RUN adduser --disabled-password --gecos "" appuser && \
    chown -R appuser:appuser /app

USER appuser

ENV DATABASE_PATH=/app/data/alumni.db

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/v1/health')" || exit 1

CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--log-level", "info"]
