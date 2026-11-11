"""Alembic environment.

At app start-up `boursy.db.migrate` passes an open connection in `config.attributes["connection"]`.
From the `alembic` command line no connection is passed, so one is opened on the database named by
the Boursy settings (BOURSY_DATA_DIR), or by `-x db_url=...` when given.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection

from boursy.db import models  # noqa: F401  (registers the tables on Base.metadata)
from boursy.db.session import Base

config = context.config
target_metadata = Base.metadata

if config.config_file_name and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # SQLite cannot ALTER most things: rebuild tables instead.
        compare_type=True,
        transactional_ddl=True,  # true with the engine from create_sqlite_engine
    )
    with context.begin_transaction():
        context.run_migrations()


def _db_url() -> str:
    url = context.get_x_argument(as_dictionary=True).get("db_url")
    if url:
        return url
    from boursy.config import get_settings

    return get_settings().db_url


def run_migrations_offline() -> None:
    context.configure(
        url=_db_url(),
        target_metadata=target_metadata,
        render_as_batch=True,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    from boursy.db.migrate import migration_connection
    from boursy.db.session import create_sqlite_engine

    engine = create_sqlite_engine(_db_url())
    try:
        with migration_connection(engine) as conn:
            _run(conn)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
