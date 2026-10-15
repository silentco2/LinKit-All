"""Alembic env. Runtime passes a connection via config.attributes; dev CLI uses settings."""

from alembic import context
from sqlalchemy import Connection

from linkit_all.core.models import Base


def run() -> None:
    conn = context.config.attributes.get("connection")
    if conn is None:
        from linkit_all.core.config import get_settings
        from linkit_all.core.db import make_engine

        with make_engine(get_settings().db_path).begin() as conn:
            _configure_and_run(conn)
    else:
        _configure_and_run(conn)


def _configure_and_run(conn: Connection) -> None:
    # render_as_batch: SQLite needs table rebuilds for most ALTERs.
    context.configure(connection=conn, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


run()
