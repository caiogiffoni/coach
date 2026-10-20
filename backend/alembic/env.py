"""Alembic environment: targets ``app.db.Base`` and the app's DATABASE_URL.

Logging is deliberately not configured here (no ``fileConfig``) so running
migrations at app startup keeps the app's JSON logging intact.
"""

from sqlalchemy import Connection, engine_from_config, pool

from alembic import context
from app.config import settings
from app.db import Base, import_all_models

import_all_models()
target_metadata = Base.metadata
config = context.config


def database_url() -> str:
    """Prefer a URL set by the caller (tests, upgrade_database) over settings."""
    return config.get_main_option("sqlalchemy.url") or settings.database_url


def configure(**kwargs: object) -> None:
    """Shared options; batch mode lets SQLite emulate ALTER TABLE."""
    context.configure(target_metadata=target_metadata, render_as_batch=True, **kwargs)


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a DB connection (``alembic upgrade --sql``)."""
    configure(url=database_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = database_url()
    connectable = engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        run_with_connection(connection)


def run_with_connection(connection: Connection) -> None:
    """Run all pending migrations inside one transaction."""
    configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
