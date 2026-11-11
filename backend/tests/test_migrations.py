from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from boursy.db import models  # noqa: F401
from boursy.db.migrate import (
    BASELINE_REVISION,
    MigrationError,
    alembic_config,
    current_revision,
    head_revision,
    migration_connection,
    upgrade_to_head,
)
from boursy.db.session import Base, init_db


def _url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _backups(tmp_path: Path) -> list[Path]:
    return sorted((tmp_path / "backups").glob("pre-migrate-*.db")) if (tmp_path / "backups").exists() else []


def test_migrations_match_models(tmp_path: Path):
    engine = init_db(_url(tmp_path / "t.db"))
    with engine.connect() as conn:
        assert current_revision(conn) == head_revision()
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diff == [], f"models and migrations differ, write a migration: {diff}"


def test_fresh_database_gets_no_backup(tmp_path: Path):
    init_db(_url(tmp_path / "t.db"))
    assert _backups(tmp_path) == []


def test_downgrade_to_base_and_back(tmp_path: Path):
    engine = init_db(_url(tmp_path / "t.db"))
    with engine.begin() as conn:
        command.downgrade(alembic_config(conn), "base")
    with engine.connect() as conn:
        assert inspect(conn).get_table_names() == ["alembic_version"]
        assert current_revision(conn) is None
    upgrade_to_head(engine)
    with engine.connect() as conn:
        assert current_revision(conn) == head_revision()
        assert "daily_bars" in inspect(conn).get_table_names()


def test_database_without_history_is_stamped_and_keeps_data(tmp_path: Path):
    db = tmp_path / "t.db"
    legacy = create_engine(_url(db))
    Base.metadata.create_all(legacy)  # how M1 created tables before migrations existed
    with legacy.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO stocks (symbol, name, country, exchange, currency, bucket, pea_eligible, active,"
                " created_at) VALUES ('MEDCL.PA', 'Medincell', 'FR', 'XPAR', 'EUR', 'growth', 1, 1,"
                " '2026-11-01 00:00:00')"
            )
        )
    legacy.dispose()

    engine = init_db(_url(db))
    with engine.connect() as conn:
        assert current_revision(conn) == head_revision()
        assert conn.execute(text("SELECT symbol FROM stocks")).scalar_one() == "MEDCL.PA"
    if head_revision() == BASELINE_REVISION:
        assert _backups(tmp_path) == []  # stamped only, nothing migrated
    else:
        assert len(_backups(tmp_path)) == 1


def test_existing_data_is_backed_up_before_migrating(tmp_path: Path):
    db = tmp_path / "t.db"
    engine = create_engine(_url(db))
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)"))
        conn.execute(text("INSERT INTO notes (body) VALUES ('keep me')"))

    upgrade_to_head(engine)

    backups = _backups(tmp_path)
    assert len(backups) == 1
    assert backups[0].name.startswith(f"pre-migrate-none-to-{head_revision()}-")
    copy = create_engine(_url(backups[0]))
    with copy.connect() as conn:
        assert conn.execute(text("SELECT body FROM notes")).scalar_one() == "keep me"
        assert "alembic_version" not in inspect(conn).get_table_names()
    copy.dispose()


def test_unknown_revision_stops_startup(tmp_path: Path):
    engine = init_db(_url(tmp_path / "t.db"))
    with engine.begin() as conn:
        conn.execute(text("UPDATE alembic_version SET version_num = '9999'"))
    with pytest.raises(MigrationError, match="9999"):
        upgrade_to_head(engine)


def _insert_stock_with_bar(conn) -> None:  # noqa: ANN001
    conn.execute(
        text(
            "INSERT INTO stocks (id, symbol, name, country, exchange, currency, bucket, pea_eligible, active,"
            " created_at) VALUES (1, 'MEDCL.PA', 'Medincell', 'FR', 'XPAR', 'EUR', 'growth', 1, 1,"
            " '2026-11-01 00:00:00')"
        )
    )
    conn.execute(
        text(
            "INSERT INTO daily_bars (stock_id, date, open, high, low, close, adj_close, volume)"
            " VALUES (1, '2026-11-02', 10, 11, 9, 10.5, 10.5, 1000)"
        )
    )


def _rebuild_stocks_table(conn) -> None:  # noqa: ANN001
    op = Operations(MigrationContext.configure(conn))
    with op.batch_alter_table("stocks", recreate="always") as batch:
        batch.add_column(sa.Column("sector", sa.String(32), nullable=True))


def test_table_rebuild_keeps_child_rows(tmp_path: Path):
    engine = init_db(_url(tmp_path / "t.db"))
    with engine.begin() as conn:
        _insert_stock_with_bar(conn)

    with migration_connection(engine) as conn:
        _rebuild_stocks_table(conn)

    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM daily_bars")).scalar_one() == 1
        assert "sector" in {c["name"] for c in inspect(conn).get_columns("stocks")}
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1  # set back on


def test_table_rebuild_without_protection_loses_child_rows(tmp_path: Path):
    """Shows why migration_connection exists: the cascade wipes the price history."""
    engine = init_db(_url(tmp_path / "t.db"))
    with engine.begin() as conn:
        _insert_stock_with_bar(conn)
        _rebuild_stocks_table(conn)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM daily_bars")).scalar_one() == 0


def test_failed_migration_rolls_back_schema_changes(tmp_path: Path):
    engine = init_db(_url(tmp_path / "t.db"))
    with pytest.raises(RuntimeError, match="boom"), migration_connection(engine) as conn:
        _rebuild_stocks_table(conn)
        conn.execute(text("CREATE TABLE orders (id INTEGER PRIMARY KEY)"))
        raise RuntimeError("boom")
    with engine.connect() as conn:
        assert "orders" not in inspect(conn).get_table_names()
        assert "sector" not in {c["name"] for c in inspect(conn).get_columns("stocks")}


def test_broken_foreign_keys_roll_back(tmp_path: Path):
    engine = init_db(_url(tmp_path / "t.db"))
    with pytest.raises(MigrationError, match="foreign keys"), migration_connection(engine) as conn:
        conn.execute(
            text(
                "INSERT INTO daily_bars (stock_id, date, open, high, low, close, adj_close, volume)"
                " VALUES (42, '2026-11-02', 10, 11, 9, 10.5, 10.5, 1000)"
            )
        )
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM daily_bars")).scalar_one() == 0
