"""Schema migrations with Alembic, applied automatically at startup.

Rules:
- A database with no tables is created by running every migration from the start.
- A database created before migrations existed (tables present, no `alembic_version`) is stamped at
  the baseline revision, then upgraded.
- Before any migration touches a database that already holds tables, a copy is written to
  `<data dir>/backups/pre-migrate-<from>-to-<to>-<timestamp>.db`.
- A database whose revision is unknown to this code (written by a newer version of Boursy) stops
  the start-up instead of being changed.
- All pending migrations run in one transaction with foreign keys off (see `migration_connection`):
  they commit together or not at all.
"""

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import Connection, Engine, inspect

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
BASELINE_REVISION = "0001"
VERSION_TABLE = "alembic_version"
# Tables created by `create_all` before migrations existed; their presence means "at baseline".
BASELINE_TABLES = {"stocks", "daily_bars", "job_runs"}


class MigrationError(RuntimeError):
    pass


def alembic_config(connection: Connection | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["connection"] = connection
    cfg.attributes["configure_logger"] = False
    return cfg


def head_revision() -> str:
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    assert head is not None
    return head


def current_revision(connection: Connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


def _user_tables(connection: Connection) -> list[str]:
    return [t for t in inspect(connection).get_table_names() if t != VERSION_TABLE]


def backup_before_migration(engine: Engine, current: str | None, head: str) -> Path | None:
    db_file = engine.url.database
    if not db_file or db_file == ":memory:":
        return None
    db_path = Path(db_file)
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"pre-migrate-{current or 'none'}-to-{head}-{stamp}.db"
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


@contextmanager
def migration_connection(engine: Engine) -> Iterator[Connection]:
    """A connection in one transaction, with foreign key enforcement off.

    SQLite cannot alter most column properties, so Alembic batch mode rebuilds the table: create a
    copy, move the rows, drop the old table, rename. With foreign keys on, dropping `stocks` would
    run an implicit DELETE that cascades to `daily_bars` and wipes the price history. The SQLite
    docs prescribe this procedure for schema changes: foreign keys off, change, then
    `PRAGMA foreign_key_check` before commit. The pragma has no effect inside a transaction, so it is
    set on the raw driver connection first, and set back before the connection returns to the pool.
    """
    with engine.connect() as conn:
        raw = conn.connection.driver_connection
        raw.execute("PRAGMA foreign_keys=OFF")
        try:
            with conn.begin():
                yield conn
                broken = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
                if broken:
                    raise MigrationError(f"Migration left broken foreign keys, rolled back: {broken[:5]}")
        finally:
            raw.execute("PRAGMA foreign_keys=ON")


def upgrade_to_head(engine: Engine) -> None:
    head = head_revision()
    script = ScriptDirectory.from_config(alembic_config())

    with engine.connect() as conn:
        current = current_revision(conn)
        tables = _user_tables(conn)

    if current is not None:
        try:
            script.get_revision(current)
        except CommandError as exc:
            raise MigrationError(
                f"Database is at schema revision {current!r}, which this version of Boursy does not know "
                f"(latest known: {head!r}). It was probably written by a newer version. Run that version "
                f"again, or restore a backup from the data directory."
            ) from exc

    if current is None and BASELINE_TABLES <= set(tables):
        log.warning("Database has tables but no migration history: stamping baseline %s", BASELINE_REVISION)
        with migration_connection(engine) as conn:
            command.stamp(alembic_config(conn), BASELINE_REVISION)
        current = BASELINE_REVISION

    if current == head:
        log.info("Database schema up to date (revision %s)", head)
        return

    if tables:
        backup = backup_before_migration(engine, current, head)
        if backup is not None:
            log.info("Database backed up to %s before migration", backup)

    log.info("Migrating database schema from %s to %s", current or "empty", head)
    with migration_connection(engine) as conn:
        command.upgrade(alembic_config(conn), "head")
    log.info("Database schema migrated to %s", head)
