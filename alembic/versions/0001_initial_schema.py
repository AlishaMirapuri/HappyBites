"""Initial schema — all tables.

Revision ID: 0001
Revises:
Create Date: 2026-03-07 00:00:00.000000 UTC

Strategy: for the initial migration we create all tables via explicit
op.create_table() calls in FK-dependency order. Subsequent migrations
use incremental op.add_column() / op.create_table() / op.drop_column().

`render_as_batch=True` in env.py means SQLite ALTER TABLE operations
in future migrations are handled via table-recreation (Alembic batch mode).
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # ── cities ────────────────────────────────────────────────────────────────
    op.create_table(
        "cities",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("state", sa.String(64), nullable=True),
        sa.Column("country", sa.String(64), nullable=False, server_default="US"),
        sa.Column("slug", sa.String(128), unique=True, nullable=False),
        sa.Column("lat", sa.Float, nullable=True),
        sa.Column("lon", sa.Float, nullable=True),
        sa.Column("timezone", sa.String(64), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_cities_slug", "cities", ["slug"])
    op.create_index("ix_cities_country_state", "cities", ["country", "state"])

    # ── sources ───────────────────────────────────────────────────────────────
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(64), unique=True, nullable=False),
        sa.Column("display_name", sa.String(128), nullable=True),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("base_url", sa.String(512), nullable=True),
        sa.Column("city_id", sa.Integer, sa.ForeignKey("cities.id"), nullable=True),
        sa.Column("fetch_interval", sa.Integer, nullable=False, server_default="7200"),
        sa.Column("last_fetched_at", sa.DateTime, nullable=True),
        sa.Column("last_successful_at", sa.DateTime, nullable=True),
        sa.Column("consecutive_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("config", sa.JSON, nullable=True),
        sa.Column("confidence_weight", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    # ── crawl_jobs ────────────────────────────────────────────────────────────
    op.create_table(
        "crawl_jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("target_url", sa.String(1024), nullable=True),
        sa.Column("config", sa.JSON, nullable=True),
        sa.Column("schedule_cron", sa.String(64), nullable=True),
        sa.Column("last_run_at", sa.DateTime, nullable=True),
        sa.Column("last_success_at", sa.DateTime, nullable=True),
        sa.Column("last_failure_at", sa.DateTime, nullable=True),
        sa.Column("consecutive_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_crawl_jobs_source_id", "crawl_jobs", ["source_id"])

    # ── venues ────────────────────────────────────────────────────────────────
    op.create_table(
        "venues",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("slug", sa.String(256), unique=True, nullable=True),
        sa.Column("city_id", sa.Integer, sa.ForeignKey("cities.id"), nullable=True),
        sa.Column("address", sa.String(512), nullable=True),
        sa.Column("lat", sa.Float, nullable=True),
        sa.Column("lon", sa.Float, nullable=True),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("website", sa.String(512), nullable=True),
        sa.Column("image_url", sa.String(1024), nullable=True),
        sa.Column("confidence", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_venues_city_id", "venues", ["city_id"])
    op.create_index("ix_venues_category", "venues", ["category"])
    op.create_index("ix_venues_lat_lon", "venues", ["lat", "lon"])
    op.create_index("ix_venues_slug", "venues", ["slug"])

    # ── venue_source_mappings ─────────────────────────────────────────────────
    op.create_table(
        "venue_source_mappings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("venue_id", sa.Integer, sa.ForeignKey("venues.id"), nullable=False),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("external_id", sa.String(256), nullable=False),
        sa.Column("external_url", sa.String(1024), nullable=True),
        sa.Column("last_seen_at", sa.DateTime, nullable=True),
        sa.Column("confidence", sa.Float, nullable=False, server_default="1.0"),
        sa.UniqueConstraint("source_id", "external_id", name="uq_venue_mapping_per_source"),
    )
    op.create_index("ix_vsm_venue_id", "venue_source_mappings", ["venue_id"])
    op.create_index(
        "ix_vsm_source_external", "venue_source_mappings", ["source_id", "external_id"]
    )

    # ── deals ─────────────────────────────────────────────────────────────────
    op.create_table(
        "deals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("venue_id", sa.Integer, sa.ForeignKey("venues.id"), nullable=True),
        sa.Column("city_id", sa.Integer, sa.ForeignKey("cities.id"), nullable=True),
        sa.Column("source_deal_id", sa.String(256), nullable=False),
        sa.Column("source_url", sa.String(1024), nullable=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("url", sa.String(1024), nullable=False),
        sa.Column("image_url", sa.String(1024), nullable=True),
        sa.Column("merchant", sa.String(256), nullable=True),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("tags", sa.Text, nullable=True),
        sa.Column("original_price", sa.Float, nullable=True),
        sa.Column("deal_price", sa.Float, nullable=True),
        sa.Column("discount_pct", sa.Float, nullable=True),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("location", sa.String(128), nullable=True),
        sa.Column("lat", sa.Float, nullable=True),
        sa.Column("lon", sa.Float, nullable=True),
        sa.Column("radius_miles", sa.Float, nullable=True),
        sa.Column("is_online", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("starts_at", sa.DateTime, nullable=True),
        sa.Column("expires_at", sa.DateTime, nullable=True),
        sa.Column("fetched_at", sa.DateTime, nullable=False),
        sa.Column("first_seen_at", sa.DateTime, nullable=True),
        sa.Column("last_seen_at", sa.DateTime, nullable=True),
        sa.Column("normalized_at", sa.DateTime, nullable=True),
        sa.Column("quality_score", sa.Float, nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("freshness_score", sa.Float, nullable=True),
        sa.Column("rank_score", sa.Float, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_verified", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("source_id", "source_deal_id", name="uq_deal_per_source"),
    )
    op.create_index("ix_deals_city_id", "deals", ["city_id"])
    op.create_index("ix_deals_venue_id", "deals", ["venue_id"])
    op.create_index("ix_deals_category", "deals", ["category"])
    op.create_index("ix_deals_expires_at", "deals", ["expires_at"])
    op.create_index("ix_deals_fetched_at", "deals", ["fetched_at"])
    op.create_index("ix_deals_last_seen_at", "deals", ["last_seen_at"])
    op.create_index("ix_deals_rank_score", "deals", ["rank_score"])
    op.create_index("ix_deals_lat_lon", "deals", ["lat", "lon"])
    op.create_index("ix_deals_active_rank", "deals", ["is_active", "rank_score"])
    op.create_index("ix_deals_active_category", "deals", ["is_active", "category"])

    # ── deals_raw ─────────────────────────────────────────────────────────────
    op.create_table(
        "deals_raw",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("deal_id", sa.Integer, sa.ForeignKey("deals.id"), nullable=True),
        sa.Column("crawl_job_id", sa.Integer, sa.ForeignKey("crawl_jobs.id"), nullable=True),
        sa.Column("source_deal_id", sa.String(256), nullable=False),
        sa.Column("raw_payload", sa.JSON, nullable=False),
        sa.Column("raw_url", sa.String(1024), nullable=True),
        sa.Column("http_status", sa.Integer, nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("fetched_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_deals_raw_source_id", "deals_raw", ["source_id"])
    op.create_index("ix_deals_raw_fetched_at", "deals_raw", ["fetched_at"])
    op.create_index("ix_deals_raw_content_hash", "deals_raw", ["content_hash"])
    op.create_index("ix_deals_raw_deal_id", "deals_raw", ["deal_id"])

    # ── deal_schedules ────────────────────────────────────────────────────────
    op.create_table(
        "deal_schedules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("deal_id", sa.Integer, sa.ForeignKey("deals.id"), nullable=False),
        sa.Column("day_of_week", sa.Integer, nullable=True),
        sa.Column("start_time", sa.String(8), nullable=True),
        sa.Column("end_time", sa.String(8), nullable=True),
        sa.Column("valid_from", sa.DateTime, nullable=True),
        sa.Column("valid_until", sa.DateTime, nullable=True),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("notes", sa.Text, nullable=True),
    )
    op.create_index("ix_deal_schedules_deal_id", "deal_schedules", ["deal_id"])

    # ── ingestion_runs ────────────────────────────────────────────────────────
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("crawl_job_id", sa.Integer, sa.ForeignKey("crawl_jobs.id"), nullable=True),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("deals_fetched", sa.Integer, nullable=False, server_default="0"),
        sa.Column("deals_inserted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("deals_updated", sa.Integer, nullable=False, server_default="0"),
        sa.Column("deals_skipped", sa.Integer, nullable=False, server_default="0"),
        sa.Column("records_raw", sa.Integer, nullable=False, server_default="0"),
        sa.Column("duration_seconds", sa.Float, nullable=True),
        sa.Column("error_msg", sa.Text, nullable=True),
        sa.Column("error_trace", sa.Text, nullable=True),
    )
    op.create_index("ix_ingestion_runs_source_id", "ingestion_runs", ["source_id"])
    op.create_index("ix_ingestion_runs_started_at", "ingestion_runs", ["started_at"])

    # ── normalization_log ─────────────────────────────────────────────────────
    op.create_table(
        "normalization_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("deal_id", sa.Integer, sa.ForeignKey("deals.id"), nullable=False),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("prompt_tokens", sa.Integer, nullable=True),
        sa.Column("completion_tokens", sa.Integer, nullable=True),
        sa.Column("raw_response", sa.Text, nullable=True),
        sa.Column("normalized_at", sa.DateTime, nullable=False),
        sa.Column("fallback_used", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_norm_log_deal_id", "normalization_log", ["deal_id"])

    # ── user_preferences ─────────────────────────────────────────────────────
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_id", sa.String(64), unique=True, nullable=False),
        sa.Column("city_id", sa.Integer, sa.ForeignKey("cities.id"), nullable=True),
        sa.Column("preferred_categories", sa.JSON, nullable=True),
        sa.Column("excluded_categories", sa.JSON, nullable=True),
        sa.Column("preferred_merchants", sa.JSON, nullable=True),
        sa.Column("max_price", sa.Float, nullable=True),
        sa.Column("min_discount_pct", sa.Float, nullable=True),
        sa.Column("radius_miles", sa.Float, nullable=False, server_default="25.0"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        "ix_user_prefs_session_id", "user_preferences", ["session_id"], unique=True
    )

    # ── event_log ─────────────────────────────────────────────────────────────
    op.create_table(
        "event_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("deal_id", sa.Integer, sa.ForeignKey("deals.id"), nullable=True),
        sa.Column("venue_id", sa.Integer, sa.ForeignKey("venues.id"), nullable=True),
        sa.Column("payload", sa.JSON, nullable=True),
        sa.Column("ip_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_event_log_event_type", "event_log", ["event_type"])
    op.create_index("ix_event_log_session_id", "event_log", ["session_id"])
    op.create_index("ix_event_log_deal_id", "event_log", ["deal_id"])
    op.create_index("ix_event_log_created_at", "event_log", ["created_at"])
    op.create_index(
        "ix_event_log_deal_type_time",
        "event_log",
        ["deal_id", "event_type", "created_at"],
    )


def downgrade() -> None:
    # Drop in reverse FK-dependency order
    op.drop_table("event_log")
    op.drop_table("user_preferences")
    op.drop_table("normalization_log")
    op.drop_table("ingestion_runs")
    op.drop_table("deal_schedules")
    op.drop_table("deals_raw")
    op.drop_table("deals")
    op.drop_table("venue_source_mappings")
    op.drop_table("venues")
    op.drop_table("crawl_jobs")
    op.drop_table("sources")
    op.drop_table("cities")
