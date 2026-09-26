"""Alembic environment.

Migrations run synchronously through psycopg so they can be invoked from a
plain shell, from CI, and from inside the pytest event loop without juggling
async engines. The application itself uses asyncpg. The URL comes from the
``sqlalchemy.url`` option when a caller sets it programmatically (tests do),
otherwise from ``DATABASE_URL`` in the environment.
"""

from __future__ import annotations

import os

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.models import Base

config = context.config


def _sync_url() -> str:
    url = config.get_main_option("sqlalchemy.url") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set; run `set -a; source .env; set +a` first")
    return url.replace("+asyncpg", "+psycopg")


target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _sync_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
