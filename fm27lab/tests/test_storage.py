import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.repositories import SettingsRepository


def initialized(tmp_path: Path) -> Database:
    database = Database(tmp_path / "fm27lab.db")
    database.initialize()
    return database


def test_initialize_creates_schema_and_pragmas(tmp_path: Path):
    database = initialized(tmp_path)
    assert database.health() is True
    tables = database.table_names()
    required = {
        "schema_migrations",
        "settings",
        "saves",
        "save_leagues",
        "save_clubs",
        "jobs",
        "job_runs",
        "drafts",
        "pool_entries",
        "artifacts",
        "idempotency",
    }
    assert required <= tables
    assert database.journal_mode() == "wal"
    with closing(database.connect()) as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_uninitialized_database_is_not_healthy(tmp_path: Path):
    database = Database(tmp_path / "fm27lab.db")
    assert database.health() is False


def test_settings_repository_round_trip_upsert_and_note(tmp_path: Path):
    database = initialized(tmp_path)
    repository = SettingsRepository(database)
    repository.set("match_roster_size", 23, note="fixed")
    assert repository.get("match_roster_size") == 23
    repository.set("match_roster_size", 24, note="still fixed")
    assert repository.get("match_roster_size") == 24
    with closing(database.connect()) as connection:
        note = connection.execute("SELECT note FROM settings WHERE key='match_roster_size'").fetchone()[0]
    assert note == "still fixed"
    assert repository.get("missing", default={"ok": True}) == {"ok": True}


def test_transaction_rolls_back(tmp_path: Path):
    database = initialized(tmp_path)
    repository = SettingsRepository(database)
    with pytest.raises(RuntimeError):
        with database.transaction() as connection:
            repository.set("temporary", 1, connection=connection)
            raise RuntimeError("rollback")
    assert repository.get("temporary") is None


def test_failed_migration_rolls_back_and_retries(tmp_path: Path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_ok.sql").write_text("CREATE TABLE ok_table (id INTEGER);\n", encoding="utf-8")
    (migrations / "002_bad.sql").write_text(
        "CREATE TABLE partial_table (id INTEGER);\nTHIS IS NOT SQL;\n", encoding="utf-8"
    )
    database = Database(tmp_path / "fm27lab.db", migrations_dir=migrations)
    with pytest.raises(sqlite3.OperationalError):
        database.initialize()
    with closing(database.connect()) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "ok_table" in tables
    assert "partial_table" not in tables
    assert database.health() is False
    (migrations / "002_bad.sql").write_text("CREATE TABLE fixed_table (id INTEGER);\n", encoding="utf-8")
    database.initialize()
    assert "fixed_table" in database.table_names()


def test_duplicate_migration_versions_are_rejected(tmp_path: Path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_a.sql").write_text("CREATE TABLE a (id INTEGER);\n", encoding="utf-8")
    (migrations / "001_b.sql").write_text("CREATE TABLE b (id INTEGER);\n", encoding="utf-8")
    database = Database(tmp_path / "fm27lab.db", migrations_dir=migrations)
    with pytest.raises(ValueError, match="duplicate migration version"):
        database.initialize()
    assert not {"a", "b"} & database.table_names()


def test_migration_supports_multiple_statements_per_line(tmp_path: Path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_multi.sql").write_text(
        "CREATE TABLE a (id INTEGER); CREATE TABLE b (id INTEGER);\n",
        encoding="utf-8",
    )
    database = Database(tmp_path / "fm27lab.db", migrations_dir=migrations)
    database.initialize()
    assert {"a", "b"} <= database.table_names()
