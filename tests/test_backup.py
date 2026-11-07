from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from scripts.backup_database import backup_sqlite


class BackupTests(unittest.TestCase):
    def test_backup_keeps_committed_wal_rows_without_editing_source(self):
        with TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "source.sqlite", Path(tmp) / "backups" / "copy.sqlite"
            with closing(sqlite3.connect(source)) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("CREATE TABLE sample (value TEXT)")
                connection.execute("INSERT INTO sample VALUES ('Giữ dữ liệu cũ')")
                connection.commit()
                backup_sqlite(source, target)
                with closing(sqlite3.connect(target)) as copied:
                    self.assertEqual(copied.execute("SELECT * FROM sample").fetchall(), [("Giữ dữ liệu cũ",)])
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM sample").fetchone()[0], 1)

    def test_backup_refuses_missing_source_and_existing_destination(self):
        with TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "source.sqlite", Path(tmp) / "copy.sqlite"
            with self.assertRaises(ValueError):
                backup_sqlite(source, target)
            self.assertFalse(source.exists())
            self.assertFalse(target.exists())
            with closing(sqlite3.connect(source)) as connection:
                connection.execute("CREATE TABLE sample (value TEXT)")
                connection.commit()
            target.write_bytes(b"existing backup")
            with self.assertRaises(FileExistsError):
                backup_sqlite(source, target)
            self.assertEqual(target.read_bytes(), b"existing backup")


if __name__ == "__main__":
    unittest.main()
