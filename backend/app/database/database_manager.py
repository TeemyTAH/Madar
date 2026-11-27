"""SQLite database lifecycle manager for the Madar project.

This module uses only the Python standard library. It expects the official
Madar project layout and the schema at backend/app/database/schema.sql.
"""
from __future__ import annotations

import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


class DatabaseManager:
    """Create, connect to, back up, and restore the Madar SQLite database.

    Args:
        base_dir: Madar project root. If omitted, it is discovered from this
            file's location (backend/app/database -> project root).
        db_name: Database filename stored directly inside storage/.

    Important:
        - Foreign-key enforcement is enabled on every manager connection.
        - Existing databases are validated, never silently overwritten.
        - Restore validates the source and creates a safety backup first.
    """

    def __init__(
        self,
        base_dir: str | Path | None = None,
        db_name: str = "SmartArabicGraderDB.sqlite3",
    ) -> None:
        self.base_dir = (
            Path(base_dir).expanduser().resolve()
            if base_dir is not None
            else Path(__file__).resolve().parents[3]
        )
        self.storage_dir = self.base_dir / "storage"
        self.original_images_dir = self.storage_dir / "original_images"
        self.processed_images_dir = self.storage_dir / "processed_images"
        self.exports_dir = self.storage_dir / "exports"
        self.backups_dir = self.storage_dir / "backups"
        self.db_path = self.storage_dir / db_name
        self.schema_sql_path = (
            self.base_dir / "backend" / "app" / "database" / "schema.sql"
        )

    def ensure_directories(self) -> None:
        """Create the directories defined by the official Madar layout."""
        for directory in (
            self.storage_dir,
            self.original_images_dir,
            self.processed_images_dir,
            self.exports_dir,
            self.backups_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def get_connection(self) -> sqlite3.Connection:
        """Return a configured connection with foreign keys enabled."""
        self.ensure_directories()
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 30000;")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Commit on success, roll back on failure, and always close."""
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _schema_version(conn: sqlite3.Connection) -> int | None:
        """Return the latest recorded schema version, or None if absent."""
        exists = conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'SchemaMigrations'
            """
        ).fetchone()
        if not exists:
            return None

        row = conn.execute(
            "SELECT MAX(Version) FROM SchemaMigrations"
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    @staticmethod
    def _validate_database_file(path: Path) -> None:
        """Raise an error unless path is a structurally valid Madar database."""
        path = path.expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Database file does not exist: {path}")

        # as_uri() safely handles Windows drive letters, spaces, and Unicode.
        database_uri = f"{path.as_uri()}?mode=ro"
        conn = sqlite3.connect(database_uri, uri=True, timeout=30.0)
        try:
            DatabaseManager._validate_connection(conn)
        finally:
            conn.close()

    def initialize_database(self) -> Path:
        """Initialize a new database, or validate an existing one."""
        self.ensure_directories()

        if not self.schema_sql_path.is_file():
            raise FileNotFoundError(
                f"Madar schema file not found: {self.schema_sql_path}"
            )

        if self.db_path.exists():
            self._validate_database_file(self.db_path)
            return self.db_path

        script = self.schema_sql_path.read_text(encoding="utf-8")
        conn = self.get_connection()
        try:
            conn.executescript(script)
            # The schema script may contain its own explicit transaction.
            conn.execute("PRAGMA foreign_keys = ON;")
            self._validate_connection(conn)
        except Exception:
            conn.close()
            # Do not leave a partially initialized database behind.
            if self.db_path.exists():
                self.db_path.unlink()
            raise
        else:
            conn.close()

        return self.db_path

    @staticmethod
    def _validate_connection(conn: sqlite3.Connection) -> None:
        """Validate SQLite integrity, foreign keys, and Madar schema version."""
        integrity = conn.execute("PRAGMA integrity_check;").fetchone()
        if not integrity or integrity[0] != "ok":
            result = integrity[0] if integrity else "no result"
            raise ValueError(f"SQLite integrity_check failed: {result}")

        fk_errors = conn.execute("PRAGMA foreign_key_check;").fetchall()
        if fk_errors:
            raise ValueError(
                f"Foreign-key violations detected: {fk_errors[:5]}"
            )

        version = DatabaseManager._schema_version(conn)
        if version is None or version < 1:
            raise ValueError(
                "Invalid Madar schema version. "
                "SchemaMigrations version 1 or higher is required."
            )

    def create_backup(
        self,
        user_id: int | None = None,
        notes: str | None = None,
    ) -> Path:
        """Create and validate a consistent SQLite backup."""
        if not self.db_path.exists():
            self.initialize_database()

        self.ensure_directories()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        final_path = self.backups_dir / f"madar_backup_{stamp}.sqlite3"
        temp_path = final_path.with_suffix(final_path.suffix + ".tmp")

        source = self.get_connection()
        destination: sqlite3.Connection | None = None

        try:
            destination = sqlite3.connect(temp_path, timeout=30.0)
            source.backup(destination)
            self._validate_connection(destination)
            destination.close()
            destination = None

            temp_path.replace(final_path)
            self._insert_backup_history(
                user_id=user_id,
                file_path=final_path,
                operation="BACKUP",
                status="SUCCESS",
                notes=notes or "Automated local SQLite backup",
            )
            return final_path

        except Exception as exc:
            if destination is not None:
                destination.close()

            if temp_path.exists():
                temp_path.unlink()

            try:
                self._insert_backup_history(
                    user_id=user_id,
                    file_path=final_path,
                    operation="BACKUP",
                    status="FAILED",
                    notes=f"Backup failed: {exc}",
                )
            except Exception:
                # Preserve the original backup exception.
                pass
            raise

        finally:
            source.close()

    def _insert_backup_history(
        self,
        user_id: int | None,
        file_path: Path,
        operation: str,
        status: str,
        notes: str | None,
    ) -> None:
        """Record a backup/restore operation in BackupHistory."""
        with self.connection() as conn:
            if user_id is not None:
                exists = conn.execute(
                    "SELECT 1 FROM Users WHERE UserId = ?",
                    (user_id,),
                ).fetchone()
                if not exists:
                    raise ValueError(
                        f"UserId {user_id} does not exist; "
                        "cannot attribute backup history."
                    )

            conn.execute(
                """
                INSERT INTO BackupHistory
                    (PerformedByUserId, BackupFilePath, OperationType, Status, Notes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, str(file_path), operation, status, notes),
            )

    def restore_backup(
        self,
        backup_file_path: str | Path,
        user_id: int | None = None,
        notes: str | None = None,
    ) -> Path:
        """Restore a validated backup after creating a safety copy.

        The application must stop other database users/connections before
        calling this method. SQLite connections owned by this manager are
        closed before the database file is replaced.
        """
        backup_path = Path(backup_file_path).expanduser().resolve()
        active_path = self.db_path.resolve()

        if not backup_path.is_file():
            raise FileNotFoundError(
                f"Backup file does not exist: {backup_path}"
            )
        if backup_path == active_path:
            raise ValueError(
                "The active database cannot be restored from itself."
            )

        self._validate_database_file(backup_path)
        self.ensure_directories()

        safety_backup: Path | None = None
        if self.db_path.exists():
            self._validate_database_file(self.db_path)

            stamp = datetime.now(timezone.utc).strftime(
                "%Y%m%dT%H%M%S_%fZ"
            )
            safety_backup = (
                self.backups_dir / f"madar_pre_restore_{stamp}.sqlite3"
            )

            source = self.get_connection()
            destination = sqlite3.connect(safety_backup, timeout=30.0)
            try:
                source.backup(destination)
                self._validate_connection(destination)
            finally:
                destination.close()
                source.close()

        # Stage and validate the restore before replacing the active database.
        temp_restore = self.db_path.with_suffix(
            self.db_path.suffix + ".restore.tmp"
        )
        try:
            shutil.copy2(backup_path, temp_restore)
            self._validate_database_file(temp_restore)

            # Remove stale WAL sidecars only after manager-owned connections
            # have been closed. Other application connections must also stop.
            for sidecar in (
                Path(str(self.db_path) + "-wal"),
                Path(str(self.db_path) + "-shm"),
            ):
                if sidecar.exists():
                    sidecar.unlink()

            temp_restore.replace(self.db_path)

        except Exception:
            if temp_restore.exists():
                temp_restore.unlink()
            raise

        # Record the restore in the restored database.
        with self.connection() as conn:
            if user_id is not None:
                actor_exists = conn.execute(
                    "SELECT 1 FROM Users WHERE UserId = ?",
                    (user_id,),
                ).fetchone()
                if not actor_exists:
                    user_id = None

            conn.execute(
                """
                INSERT INTO BackupHistory
                    (PerformedByUserId, BackupFilePath, OperationType, Status, Notes)
                VALUES (?, ?, 'RESTORE', 'SUCCESS', ?)
                """,
                (
                    user_id,
                    str(backup_path),
                    notes or "Restored from a validated local backup",
                ),
            )

            if safety_backup is not None:
                conn.execute(
                    """
                    INSERT INTO BackupHistory
                        (PerformedByUserId, BackupFilePath, OperationType, Status, Notes)
                    VALUES (?, ?, 'BACKUP', 'SUCCESS', ?)
                    """,
                    (
                        user_id,
                        str(safety_backup),
                        "Automatic safety backup created before restore",
                    ),
                )

        self._validate_database_file(self.db_path)
        return self.db_path


if __name__ == "__main__":
    manager = DatabaseManager()
    path = manager.initialize_database()
    print(f"Madar database is ready: {path}")
