"""Cloud configuration/backup tests use only temporary secrets and SQLite files."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.deployment_preflight import evaluate, exact_https_origin
from scripts.prepare_cloud_test import stage_artifacts, write_private, hostname
from scripts.backup_ward import backup as ward_backup, verify_backup_integrity
from deploy.backup import snapshot, restore, verify
from deploy.healthcheck import check


class CloudPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ward-cloud-test-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        data = self.directory / 'artifacts/bidmc'
        models = self.directory / 'artifacts/models'
        data.mkdir(parents=True)
        models.mkdir(parents=True)
        checksums = {}
        for index in range(1, 54):
            name = f'bidmc_{index:02d}_Numerics.csv'
            (data / name).write_text('test numerics')
            checksums[name] = hashlib.sha256(b'test numerics').hexdigest()
        (data / 'manifest.json').write_text(json.dumps({'sha256': checksums}))
        (models / 'bidmc_monitor_v1.joblib').write_bytes(b'never deserialized in these tests')
        (models / 'bidmc_monitor_v1_metadata.json').write_text(json.dumps({
            'model_version': 'bidmc-monitor-v1', 'splits': {'test': ['bidmc_01']}, 'sklearn_version': '1.9.0'}))
        secret = self.directory / 'secrets/webpush-private.pem'
        secret.parent.mkdir()
        key = ec.generate_private_key(ec.SECP256R1())
        secret.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        self.env = {
            'WARD_DEMO_ID_LOGIN': '0', 'WARD_ENABLE_TEST_ACCOUNTS': '1', 'WARD_COOKIE_SECURE': '1',
            'WARD_STAFF_HOST': 'staff.example.org', 'WARD_PATIENT_HOST': 'patient.example.org',
            'WARD_STAFF_ORIGIN': 'https://staff.example.org', 'WARD_PATIENT_ORIGIN': 'https://patient.example.org',
            'WARD_TEST_DOCTOR_PASSWORD': 'long-random-doctor-test-secret',
            'WARD_TEST_PATIENT_PASSWORD': 'long-random-patient-test-secret',
            'WARD_STAFF_PASSWORD': 'unused-shared-secret-with-32-characters',
            'WARD_INGEST_MODE': 'replay', 'WARD_BEDSIDE_MQTT_ENABLED': '0',
            'WARD_WEB_PUSH_ENABLED': '1', 'WARD_VAPID_SUBJECT': 'mailto:operator@example.org',
        }

    def test_private_profile_accepts_separate_password_accounts_but_clinical_blocks(self):
        errors, _ = evaluate(self.env, 'private-test', cloud_dir=self.directory)
        self.assertEqual(errors, [])
        errors, _ = evaluate(self.env, 'clinical', cloud_dir=self.directory)
        self.assertTrue(any('WARD_ENABLE_TEST_ACCOUNTS' in error for error in errors))
        self.assertTrue(any('mqtt' in error for error in errors))

    def test_known_password_and_live_ingest_are_rejected(self):
        values = {**self.env, 'WARD_TEST_DOCTOR_PASSWORD': 'admin1234', 'WARD_BEDSIDE_MQTT_ENABLED': '1'}
        errors, _ = evaluate(values, 'private-test', cloud_dir=self.directory)
        self.assertTrue(any('WARD_TEST_DOCTOR_PASSWORD' in error for error in errors))
        self.assertTrue(any('bedside' in error for error in errors))

    def test_dataset_corruption_and_wrong_runtime_block_startup(self):
        (self.directory / 'artifacts/bidmc/bidmc_01_Numerics.csv').write_text('corrupt')
        metadata = self.directory / 'artifacts/models/bidmc_monitor_v1_metadata.json'
        metadata.write_text(json.dumps({'sklearn_version': '0.1'}))
        errors, _ = evaluate(self.env, 'private-test', cloud_dir=self.directory)
        self.assertTrue(any('checksum' in error for error in errors))
        self.assertTrue(any('metadata/runtime' in error for error in errors))

    def test_exact_origin_rejects_credentials_fragments_and_paths(self):
        for value in ('https://a.test/', 'https://a.test#x', 'https://user@a.test',
                      'https://a.test?x=1', 'http://a.test', 'https://a.test:99999', None):
            self.assertFalse(exact_https_origin(value), value)
        self.assertTrue(exact_https_origin('https://a.test:8443'))

    def test_private_file_never_overwrites_existing_secret(self):
        path = self.directory / 'secret'
        write_private(path, b'first')
        with self.assertRaises(FileExistsError):
            write_private(path, b'second')
        self.assertEqual(path.read_bytes(), b'first')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ward-backup-test-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.database = self.directory / 'source.db'
        self.conn = sqlite3.connect(self.database)
        self.addCleanup(self.conn.close)
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('CREATE TABLE care_messages(id INTEGER PRIMARY KEY, body TEXT)')
        self.conn.execute("INSERT INTO care_messages VALUES (1, 'committed WAL message')")
        self.conn.commit()

    def test_online_backup_includes_wal_and_restore_never_overwrites(self):
        path = snapshot(self.database, self.directory / 'backups')
        destination = self.directory / 'recovered.db'
        restore(path, destination)
        with closing(sqlite3.connect(destination)) as conn:
            self.assertEqual(conn.execute('SELECT body FROM care_messages').fetchone()[0], 'committed WAL message')
        with self.assertRaises(FileExistsError):
            restore(path, destination)
        with self.assertRaises(FileExistsError):
            restore(path, self.database)

    def test_retention_preserves_unmanaged_and_corrupt_backups(self):
        directory = self.directory / 'backups'
        original = snapshot(self.database, directory, keep=2)
        original.write_bytes(b'corrupt')
        foreign = directory / 'keep-me.db'
        foreign.write_bytes(b'not managed')
        for _ in range(4):
            snapshot(self.database, directory, keep=2)
        verified = []
        for candidate in directory.glob('*.sqlite3'):
            try:
                verify(candidate)
                verified.append(candidate)
            except ValueError:
                pass
        self.assertEqual(len(verified), 2)
        self.assertTrue(original.exists())
        self.assertEqual(foreign.read_bytes(), b'not managed')

    def test_fresh_test_patient_cannot_mask_stopped_ward_replay(self):
        self.conn.execute('CREATE TABLE portal_accounts(id INTEGER)')
        self.conn.execute('CREATE TABLE monitor_results(patient_id TEXT, updated_at REAL)')
        self.conn.execute('CREATE TABLE monitor_worker(id INTEGER, heartbeat REAL, status TEXT)')
        self.conn.execute("INSERT INTO monitor_worker VALUES (1,1000,'RUNNING')")
        self.conn.executemany('INSERT INTO monitor_results VALUES (?,?)', [('TEST_P', 1000), ('A001', 500)])
        self.conn.commit()
        with patch.dict(os.environ, {'WARD_DB_PATH': str(self.database), 'WARD_INGEST_MODE': 'replay', 'WARD_ENABLE_TEST_ACCOUNTS': '1'}):
            with patch('deploy.healthcheck.build_opener') as opener:
                opener.return_value.open.return_value.__enter__.return_value.read.return_value = b'{"status":"ok","portal":"staff"}'
                with self.assertRaisesRegex(RuntimeError, 'WARD_REPLAY_STALE'):
                    check('staff', now=1000)

    def test_ward_backup_and_verify_backup_integrity(self):
        dest = self.directory / 'ward_backup.db'
        result_path = ward_backup(self.database, dest)
        self.assertEqual(result_path, dest.resolve())
        self.assertTrue(dest.is_file())

        report = verify_backup_integrity(dest)
        self.assertEqual(report['integrity'], 'ok')
        self.assertIn('care_messages', report['tables'])

    def test_verify_backup_integrity_errors_on_missing_and_corrupt(self):
        missing = self.directory / 'missing.db'
        with self.assertRaises(ValueError):
            verify_backup_integrity(missing)

        corrupt = self.directory / 'corrupt.db'
        corrupt.write_bytes(b'not a valid sqlite file content header')
        corrupt_report = verify_backup_integrity(corrupt)
        self.assertNotEqual(corrupt_report['integrity'], 'ok')
        self.assertEqual(corrupt_report['tables'], [])


class ContainerHardeningTests(unittest.TestCase):
    def test_dockerfile_backend_runs_as_non_root(self):
        content = (ROOT / 'deploy/Dockerfile.backend').read_text()
        self.assertIn('USER 10001:10001', content)
        self.assertIn('groupadd --gid 10001 ward', content)
        self.assertIn('useradd --uid 10001 --gid ward', content)
        self.assertIn('COPY --chown=10001:10001 backend/', content)

    def test_dockerfile_frontend_runs_as_non_root(self):
        content = (ROOT / 'deploy/Dockerfile.frontend').read_text()
        self.assertIn('USER node', content)
        self.assertIn('--chown=node:node', content)
        self.assertIn('chown node:node next.config.js', content)

    def test_compose_enforces_security_options_and_non_root(self):
        content = (ROOT / 'deploy/compose.yml').read_text()
        self.assertIn('no-new-privileges:true', content)
        self.assertIn('read_only: true', content)
        self.assertIn('cap_drop: [ALL]', content)
        self.assertIn('user: "10001:10001"', content)
        self.assertIn('user: "node"', content)

    def test_dockerignore_excludes_credentials_and_runtime_databases(self):
        content = (ROOT / '.dockerignore').read_text()
        self.assertIn('**/.env*', content)
        self.assertIn('**/.staff-password', content)
        self.assertIn('**/*.db*', content)
        self.assertIn('**/*.sqlite*', content)
        self.assertIn('backend/runtime', content)
        self.assertIn('**/*.pem', content)
        self.assertIn('**/*.key', content)

    def test_smoke_portals_verifies_dual_ports_and_isolation(self):
        content = (ROOT / 'scripts/smoke_portals.py').read_text()
        self.assertIn('/healthz', content)
        self.assertIn('/health', content)
        self.assertIn('http://localhost:8000', content)
        self.assertIn('http://localhost:8001', content)
        self.assertIn('http://localhost:3000', content)
        self.assertIn('http://localhost:3001', content)
        self.assertIn('STAFF_ONLY_ENDPOINTS', content)


if __name__ == '__main__':
    unittest.main()
