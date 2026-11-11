"""SQLite engine and session factory."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, MetaData, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Stable constraint names, so migrations can find and alter them (SQLite batch mode needs this).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def create_sqlite_engine(db_url: str) -> Engine:
    """SQLite engine with WAL, foreign keys, and real transactions.

    The sqlite3 driver does not open a transaction before DDL statements, so a failed migration would
    leave a half-changed schema. Here the driver's own transaction handling is turned off and
    SQLAlchemy emits BEGIN itself (the recipe from the SQLAlchemy SQLite dialect docs), so schema
    changes commit or roll back as a whole.
    """
    engine = create_engine(db_url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ANN001
        dbapi_conn.isolation_level = None
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn):  # noqa: ANN001
        conn.exec_driver_sql("BEGIN")

    return engine


def init_db(db_url: str) -> Engine:
    """Create the engine, set SQLite pragmas and migrate the schema to the latest revision."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    engine = create_sqlite_engine(db_url)

    from boursy.db.migrate import upgrade_to_head

    upgrade_to_head(engine)
    _engine = engine
    _session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    return engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Database not initialised")
    return _engine


def new_session() -> Session:
    if _session_factory is None:
        raise RuntimeError("Database not initialised")
    return _session_factory()


@contextmanager
def session_scope() -> Iterator[Session]:
    session = new_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    session = new_session()
    try:
        yield session
    finally:
        session.close()
