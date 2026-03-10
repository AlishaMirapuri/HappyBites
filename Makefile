.PHONY: install dev frontend test lint fmt seed ingest migrate \
        db-init db-seed db-reset db-check \
        alembic-upgrade alembic-downgrade alembic-revision alembic-history alembic-sql \
        demo ingest-demo clean

# ── Setup ──────────────────────────────────────────────────────────────────────
install:
	pip install -e ".[dev]"

# ── Database — Alembic (recommended) ──────────────────────────────────────────

# Apply all pending migrations to head
alembic-upgrade:
	alembic upgrade head

# Roll back one migration
alembic-downgrade:
	alembic downgrade -1

# Autogenerate a new migration (requires running DB)
# Usage: make alembic-revision MSG="add venue rating column"
alembic-revision:
	@test -n "$(MSG)" || (echo "Usage: make alembic-revision MSG='description'" && exit 1)
	alembic revision --autogenerate -m "$(MSG)"

# Show migration history
alembic-history:
	alembic history --verbose

# Show current DB revision
alembic-check:
	alembic current

# Generate SQL without running it (useful for DBA review)
alembic-sql:
	alembic upgrade head --sql

# ── Database — convenience wrappers ───────────────────────────────────────────

# Initialize DB via Alembic (preferred)
db-init:
	python scripts/init_db.py

# Initialize DB directly via create_all (skips Alembic; useful for fast tests)
db-init-direct:
	python scripts/init_db.py --direct

# Seed with sample data
db-seed: db-init
	python scripts/seed_db.py

# Reset: drop all tables, re-migrate, re-seed
db-reset:
	python scripts/seed_db.py --reset

# Check migration status
db-check:
	python scripts/init_db.py --check

# Legacy alias (kept for backward compat)
migrate: db-init-direct

seed: migrate
	python scripts/backfill.py

# ── Run ────────────────────────────────────────────────────────────────────────
dev:
	uvicorn happybites.api.main:app --reload --port 8000

frontend:
	streamlit run frontend/app.py --server.port 8501

all:
	@echo "─────────────────────────────────────────────────────────"
	@echo " HappyBites — local development"
	@echo "─────────────────────────────────────────────────────────"
	@echo " Quick demo (first run):"
	@echo "   make demo           init DB + seed + ingest + start servers"
	@echo ""
	@echo " Individual commands:"
	@echo "   make db-seed        init DB and load seed data"
	@echo "   make ingest-demo    run fixture ingestion (no API keys needed)"
	@echo "   make dev            start API  → http://localhost:8000"
	@echo "   make frontend       start UI   → http://localhost:8501"
	@echo "   make dev-all        start both servers"
	@echo ""
	@echo " API docs: http://localhost:8000/docs (when API is running)"
	@echo "─────────────────────────────────────────────────────────"

# Run API + frontend concurrently (requires a terminal multiplexer or two shells)
dev-all:
	@echo "Starting API on :8000 and Streamlit on :8501 …"
	@echo "Ctrl-C stops both."
	uvicorn happybites.api.main:app --reload --port 8000 &
	streamlit run frontend/app.py --server.port 8501

# ── Ingestion ──────────────────────────────────────────────────────────────────
ingest:
	python -c "from happybites.ingestion.scheduler import run_all_sources; run_all_sources()"

ingest-source:
	@test -n "$(SOURCE)" || (echo "Usage: make ingest-source SOURCE=dealnews" && exit 1)
	python -c "from happybites.ingestion.scheduler import run_source; run_source('$(SOURCE)')"

# Run fixture ingestion demo (no external API keys required)
ingest-demo:
	python scripts/run_ingest_demo.py

# Full local demo: init DB + seed + fixture ingest, then start servers
demo: db-seed ingest-demo
	@echo ""
	@echo "Demo data loaded. Starting servers ..."
	@echo "  API:       http://localhost:8000"
	@echo "  API docs:  http://localhost:8000/docs"
	@echo "  UI:        http://localhost:8501"
	@echo ""
	@$(MAKE) dev-all

# ── Quality ────────────────────────────────────────────────────────────────────
test:
	pytest -v --tb=short

test-models:
	pytest tests/test_models.py -v --tb=short

test-api:
	pytest tests/test_api.py -v --tb=short

test-cov:
	pytest -v --tb=short --cov=happybites --cov-report=term-missing

lint:
	ruff check .

fmt:
	ruff format .

typecheck:
	mypy happybites

# ── Maintenance ────────────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -f happybites.db
	rm -rf .pytest_cache .mypy_cache .ruff_cache
