from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

MIGRATIONS = Path(__file__).with_name("migrations")
REQUIRED_TABLES = frozenset(
    {
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
)


def _statements(script: str) -> list[str]:
    statements: list[str] = []
    buffer = ""
    for character in script:
        buffer += character
        if character == ";" and sqlite3.complete_statement(buffer):
            statements.append(buffer)
            buffer = ""
    if buffer.strip():
        statements.append(buffer)
    return statements


class Database:
    def __init__(self, path: Path, migrations_dir: Path | None = None):
        self.path = Path(path)
        self.migrations_dir = Path(migrations_dir) if migrations_dir else MIGRATIONS

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def initialize(self) -> None:
        connection = self.connect()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
            )
            applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
            migrations = sorted(
                self.migrations_dir.glob("*.sql"),
                key=lambda path: int(path.name.split("_", 1)[0]),
            )
            versions: list[int] = []
            for migration in migrations:
                version = int(migration.name.split("_", 1)[0])
                if version <= 0:
                    raise ValueError(f"invalid migration version: {migration.name}")
                versions.append(version)
            if len(versions) != len(set(versions)):
                raise ValueError("duplicate migration version")
            for migration in migrations:
                version = int(migration.name.split("_", 1)[0])
                if version in applied:
                    continue
                statements = _statements(migration.read_text(encoding="utf-8"))
                connection.execute("BEGIN IMMEDIATE")
                try:
                    for statement in statements:
                        connection.execute(statement)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, datetime('now'))",
                        (version, migration.name),
                    )
                    connection.execute("COMMIT")
                except BaseException:
                    connection.execute("ROLLBACK")
                    raise
                applied.add(version)
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            connection.close()

    def health(self) -> bool:
        if not self.path.exists():
            return False
        try:
            with closing(self.connect()) as connection:
                version = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
                if version < 1:
                    return False
                names = {
                    row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                return REQUIRED_TABLES <= names
        except (sqlite3.Error, OSError):
            return False

    def table_names(self) -> set[str]:
        with closing(self.connect()) as connection:
            rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            return {row[0] for row in rows}

    def journal_mode(self) -> str:
        with closing(self.connect()) as connection:
            row = connection.execute("PRAGMA journal_mode").fetchone()
            return str(row[0]).lower()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
