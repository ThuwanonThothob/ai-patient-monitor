import importlib.util
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backup = load('cloud_backup', 'deploy/backup.py')
preflight = load('cloud_preflight', 'scripts/deployment_preflight.py')


class CloudPackageTests(unittest.TestCase):
    def test_backup_restores_committed_wal_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.db'
            with closing(sqlite3.connect(source)) as conn:
                conn.execute('PRAGMA journal_mode=WAL')
                conn.execute('CREATE TABLE observations(value INTEGER)')
                conn.execute('INSERT INTO observations VALUES (42)')
                conn.commit()
                saved = backup.snapshot(source, root / 'backups')
                backup.verify(saved)
                restored = root / 'restored.db'
                backup.restore(saved, restored)
                with closing(sqlite3.connect(restored)) as copy:
                    self.assertEqual(copy.execute('SELECT value FROM observations').fetchone()[0], 42)
                with self.assertRaises(FileExistsError):
                    backup.restore(saved, source)
                saved.write_bytes(b'corrupted test copy')
                with self.assertRaises(ValueError):
                    backup.verify(saved)

    def test_retention_only_removes_verified_generated_backups(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.db'
            with closing(sqlite3.connect(source)) as conn, conn:
                conn.execute('CREATE TABLE example(value INTEGER)')
            folder = root / 'backups'
            folder.mkdir()
            foreign = folder / 'manual.sqlite3'
            foreign.write_bytes(b'preserve')
            for _ in range(3):
                backup.snapshot(source, folder, keep=2)
            self.assertEqual(len(list(folder.glob('ward-*.sqlite3'))), 2)
            self.assertEqual(foreign.read_bytes(), b'preserve')

    def test_cloud_config_fails_closed_and_rejects_unsafe_origins(self):
        errors, _ = preflight.evaluate({}, 'private-test')
        self.assertTrue(any('WARD_TEST_DOCTOR_PASSWORD' in message for message in errors))
        self.assertTrue(any('WARD_DEMO_ID_LOGIN' in message for message in errors))
        for value in ('http://staff.example.org', 'https://user:pass@staff.example.org',
                      'https://staff.example.org/path', 'https://staff.example.org:invalid'):
            self.assertFalse(preflight.exact_https_origin(value))
        self.assertTrue(preflight.exact_https_origin('https://staff.example.org'))


if __name__ == '__main__':
    unittest.main()
