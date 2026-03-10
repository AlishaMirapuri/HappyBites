"""Alembic migration environment."""

import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Read alembic.ini logging config
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import all models so their tables register with Base.metadata.
# This must happen before target_metadata is read.
import happybites.db.models  # noqa: F401, E402

from happybites.db.engine import Base  # noqa: E402
from happybites.config import settings  # noqa: E402

target_metadata = Base.metadata

# Override the URL from pydantic Settings — this is the single source of truth.
config.set_main_option("sqlalchemy.url", settings.database_url)

log = logging.getLogger("alembic.env")


def run_migrations_offline() -> None:
    """
    Run migrations without a live DB connection.
    Generates SQL that can be piped to a file: `alembic upgrade head --sql > schema.sql`
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite: ALTER TABLE via table recreation
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations against a live DB connection.
    Used by `alembic upgrade head` in normal flow.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        url=settings.database_url,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite: ALTER TABLE via table recreation
            compare_type=True,     # Detect column type changes
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
