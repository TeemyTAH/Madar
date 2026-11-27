from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.database.database_manager import DatabaseManager


class DatabaseManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = Path(tempfile.mkdtemp(prefix="madar_manager_test_"))
        self.project_root = self.temp_root / "Madar"
        db_dir = self.project_root / "backend" / "app" / "database"
        db_dir.mkdir(parents=True)
        source_schema = Path(__file__).resolve().parents[1] / "app" / "database" / "schema.sql"
        (db_dir / "schema.sql").write_text(source_schema.read_text(encoding="utf-8"), encoding="utf-8")
        self.manager = DatabaseManager(base_dir=self.project_root)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_initialize_creates_database_and_directories(self) -> None:
        path = self.manager.initialize_database()
        self.assertTrue(path.exists())
        self.assertTrue(self.manager.original_images_dir.is_dir())
        self.assertTrue(self.manager.processed_images_dir.is_dir())
        self.assertTrue(self.manager.exports_dir.is_dir())
        self.assertTrue(self.manager.backups_dir.is_dir())

    def test_initialize_is_idempotent_and_does_not_overwrite(self) -> None:
        path = self.manager.initialize_database()
        with self.manager.connection() as conn:
            conn.execute("INSERT INTO Students (AcademicId, FullName) VALUES (?, ?)", ("S-001", "Student One"))
        before = path.stat().st_size
        self.manager.initialize_database()
        with self.manager.connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM Students").fetchone()[0]
        self.assertEqual(count, 1)
        self.assertGreaterEqual(path.stat().st_size, before)

    def test_foreign_keys_enabled_on_every_connection(self) -> None:
        self.manager.initialize_database()
        conn = self.manager.get_connection()
        try:
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        finally:
            conn.close()

    def test_backup_is_created_and_valid(self) -> None:
        self.manager.initialize_database()
        backup = self.manager.create_backup(notes="unit test")
        self.assertTrue(backup.is_file())
        self.manager._validate_database_file(backup)
        with self.manager.connection() as conn:
            row = conn.execute(
                "SELECT OperationType, Status FROM BackupHistory ORDER BY BackupId DESC LIMIT 1"
            ).fetchone()
        self.assertEqual(tuple(row), ("BACKUP", "SUCCESS"))

    def test_restore_creates_safety_backup_and_history(self) -> None:
        self.manager.initialize_database()
        with self.manager.connection() as conn:
            conn.execute("INSERT INTO Students (AcademicId, FullName) VALUES (?, ?)", ("S-OLD", "Old Student"))
        backup = self.manager.create_backup(notes="before change")
        with self.manager.connection() as conn:
            conn.execute("DELETE FROM Students WHERE AcademicId = ?", ("S-OLD",))
            conn.execute("INSERT INTO Students (AcademicId, FullName) VALUES (?, ?)", ("S-NEW", "New Student"))

        self.manager.restore_backup(backup, notes="restore test")
        with self.manager.connection() as conn:
            ids = {row[0] for row in conn.execute("SELECT AcademicId FROM Students")}
            operations = [tuple(row) for row in conn.execute(
                "SELECT OperationType, Status FROM BackupHistory ORDER BY BackupId"
            )]
        self.assertIn("S-OLD", ids)
        self.assertNotIn("S-NEW", ids)
        self.assertIn(("RESTORE", "SUCCESS"), operations)
        self.assertIn(("BACKUP", "SUCCESS"), operations)

    def test_restore_rejects_invalid_database(self) -> None:
        self.manager.initialize_database()
        bad_file = self.temp_root / "not_a_madar_db.sqlite3"
        bad_file.write_text("not a sqlite database", encoding="utf-8")
        with self.assertRaises(Exception):
            self.manager.restore_backup(bad_file)


if __name__ == "__main__":
    unittest.main(verbosity=2)
