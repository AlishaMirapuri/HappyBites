# HappyBites

AI-powered restaurant deal discovery. Find and compare **happy hours** and **lunch specials** near you — ingested from multiple sources, normalized with Claude, ranked by value + freshness, and surfaced in a clean UI.

## Architecture

```
[DealNews RSS] [Reddit API] [Seed JSON]
        |              |          |
        └──────────────┴──────────┘
                       |
              [Ingestion Pipeline]
                  Collectors
                  Normalizer (Claude)
                  Resolver (dedupe)
                  Ranker
                       |
              [SQLite / Postgres]
                       |
               [FastAPI backend]
                       |
            [Streamlit frontend]
```

## Quickstart

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
make install
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — at minimum set ANTHROPIC_API_KEY
```

### 3. Initialize DB + load seed data

```bash
make seed
```

This creates `happybites.db`, inserts all sources, and loads ~20 seed deals.

### 4. Run

**Terminal 1 — API:**
```bash
make dev
# FastAPI running at http://localhost:8000
# Docs at http://localhost:8000/docs
```

**Terminal 2 — Frontend:**
```bash
make frontend
# Streamlit running at http://localhost:8501
```

## Running ingestion manually

```bash
# Ingest all active sources
make ingest

# Ingest a specific source
make ingest-source SOURCE=dealnews
make ingest-source SOURCE=reddit

# Trigger via API (requires running server)
curl -X POST http://localhost:8000/ingest/trigger \
  -H "Content-Type: application/json" \
  -d '{"source_id": null}'
```

## Running tests

```bash
make test

# With coverage
make test-cov
```

Tests use an in-memory SQLite database and mock all external HTTP calls and the Anthropic API. No API keys required to run tests.

## Linting and formatting

```bash
make lint   # ruff check
make fmt    # ruff format
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./happybites.db` | SQLAlchemy connection string |
| `ANTHROPIC_API_KEY` | — | Required for AI normalization |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | Claude model for normalization |
| `REDDIT_CLIENT_ID` | — | Reddit app client ID |
| `REDDIT_CLIENT_SECRET` | — | Reddit app client secret |
| `INGEST_INTERVAL_SECONDS` | `7200` | Scheduler interval (2h) |
| `WEIGHT_DISCOUNT` | `0.40` | Ranking weight for discount |
| `WEIGHT_FRESHNESS` | `0.35` | Ranking weight for freshness |
| `WEIGHT_QUALITY` | `0.25` | Ranking weight for AI quality score |

## Postgres upgrade

Change one line in `.env`:

```
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/happybites
```

No other code changes needed — SQLAlchemy handles the rest.

## Project structure

```
happybites/
├── happybites/
│   ├── config.py              # Settings (pydantic-settings)
│   ├── db/
│   │   ├── engine.py          # SQLAlchemy engine + session
│   │   └── models.py          # ORM models
│   ├── ingestion/
│   │   ├── base.py            # RawDeal dataclass + BaseCollector ABC
│   │   ├── connectors/
│   │   │   ├── dealnews.py    # DealNews RSS collector
│   │   │   ├── reddit.py      # Reddit API collector
│   │   │   └── seed.py        # Static JSON seed collector
│   │   ├── normalizer.py      # Claude-powered normalization
│   │   ├── resolver.py        # Entity resolution / dedupe
│   │   ├── ranker.py          # Scoring and ranking
│   │   └── scheduler.py       # APScheduler jobs
│   ├── api/
│   │   ├── main.py            # FastAPI app + lifespan
│   │   ├── deps.py            # DB session dependency
│   │   └── routers/
│   │       ├── deals.py
│   │       ├── sources.py
│   │       ├── health.py
│   │       ├── admin.py
│   │       └── ingest.py
│   ├── schemas/
│   │   └── api.py             # Pydantic response models
│   ├── feedback/
│   │   └── events.py          # User event logging
│   └── experiments/
│       └── flags.py           # Feature flags
├── frontend/
│   └── app.py                 # Streamlit UI
├── tests/
├── data/
│   └── seed_deals.json
├── scripts/
│   └── backfill.py
├── Makefile
└── pyproject.toml
```

## API reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/deals` | List deals with filters + ranking |
| `GET` | `/deals/{id}` | Single deal with full provenance |
| `GET` | `/sources` | All ingestion sources |
| `GET` | `/sources/{id}/runs` | Ingestion run history for a source |
| `POST` | `/ingest/trigger` | Manually trigger ingestion |
| `GET` | `/health` | System health + freshness check |
| `GET` | `/admin/stats` | DB stats and deal counts |
| `POST` | `/admin/rerank` | Recompute all rank scores |
| `DELETE` | `/admin/deals/expired` | Purge expired deals |
