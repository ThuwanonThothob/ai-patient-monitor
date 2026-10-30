import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('backup_ward', Path(__file__).resolve().parents[1] / 'backup_ward.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BackupTests(unittest.TestCase):
    def test_backup_captures_committed_wal_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.db'
            destination = Path(directory) / 'backup.db'
            conn = sqlite3.connect(source)
            self.addCleanup(conn.close)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('CREATE TABLE observations(value INTEGER)')
            conn.execute('INSERT INTO observations VALUES (42)')
            conn.commit()
            module.backup(source, destination)
            copy = sqlite3.connect(destination)
            self.addCleanup(copy.close)
            self.assertEqual(copy.execute('SELECT value FROM observations').fetchone()[0], 42)
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                module.backup(source, destination)
            with self.assertRaises(ValueError):
                module.backup(source, source)
