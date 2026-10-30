#!/usr/bin/env python3
"""Read-only technical gates. Private TEST is distinct from clinical deployment."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def exact_https_origin(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
        return bool(parsed.scheme == 'https' and parsed.hostname and not parsed.username
                    and not parsed.password and not parsed.path and not parsed.query
                    and not parsed.fragment and not any(c.isspace() for c in value)
                    and (port is None or 1 <= port <= 65535))
    except ValueError:
        return False


def https_origin(name):
    return exact_https_origin(os.getenv(name, ''))


def evaluate(values, profile='clinical', *, cloud_dir=None, root=ROOT):
    values = {key: '' if value is None else str(value) for key, value in values.items()}
    errors, warnings = [], []
    def require(condition, message):
        if not condition:
            errors.append(message)
    require(values.get('WARD_DEMO_ID_LOGIN', '1') == '0', 'WARD_DEMO_ID_LOGIN must be 0')
    require(values.get('WARD_COOKIE_SECURE') == '1', 'WARD_COOKIE_SECURE must be 1')
    origins = [values.get(name, '') for name in ('WARD_STAFF_ORIGIN', 'WARD_PATIENT_ORIGIN')]
    for name, value in zip(('WARD_STAFF_ORIGIN', 'WARD_PATIENT_ORIGIN'), origins):
        require(exact_https_origin(value), name + ' must be an exact HTTPS origin (no path, query or credentials)')
    require(origins[0] != origins[1], 'Staff and patient origins must be different')
    if profile == 'private-test':
        require(values.get('WARD_ENABLE_TEST_ACCOUNTS') == '1', 'Private TEST requires WARD_ENABLE_TEST_ACCOUNTS=1')
        require(values.get('WARD_INGEST_MODE') == 'replay', 'Private TEST requires WARD_INGEST_MODE=replay')
        require(values.get('WARD_BEDSIDE_MQTT_ENABLED') == '0', 'Private TEST must not subscribe to real bedside devices')
        require(values.get('WARD_DASHBOARD_LLM', '0') == '0', 'Automatic cloud LLM calls must remain disabled for free TEST')
        passwords = [values.get(name, '') for name in ('WARD_TEST_DOCTOR_PASSWORD', 'WARD_TEST_PATIENT_PASSWORD')]
        for name, value in zip(('WARD_TEST_DOCTOR_PASSWORD', 'WARD_TEST_PATIENT_PASSWORD'), passwords):
            require(len(value) >= 16, name + ' must contain at least 16 characters')
        require(passwords[0] != passwords[1], 'TEST accounts must have different passwords')
        require(len(values.get('WARD_STAFF_PASSWORD', '')) >= 32, 'Set a random WARD_STAFF_PASSWORD of at least 32 characters')
        require(values.get('WARD_WEB_PUSH_ENABLED') == '1', 'Private TEST requires Web Push enabled')
        if cloud_dir:
            for name, origin in zip(('WARD_STAFF_HOST', 'WARD_PATIENT_HOST'), origins):
                require(origin == 'https://' + values.get(name, ''), name + ' must match its HTTPS origin')
        warnings.append('Private TEST only: synthetic telemetry and research models, no live device ingest')
    else:
        require(values.get('WARD_ENABLE_TEST_ACCOUNTS', '1') == '0', 'WARD_ENABLE_TEST_ACCOUNTS must be 0 for clinical deployment')
        require(values.get('WARD_INGEST_MODE') == 'mqtt', 'WARD_INGEST_MODE must be mqtt for real devices')
    if values.get('WARD_WEB_PUSH_ENABLED') == '1':
        subject = values.get('WARD_VAPID_SUBJECT', '')
        require(bool(re.fullmatch(r'mailto:[^\s@]+@[^\s@]+\.[^\s@]+', subject)), 'VAPID requires a real mailto contact')
        path = (Path(cloud_dir) / 'secrets/webpush-private.pem') if cloud_dir else Path(values.get('WARD_VAPID_PRIVATE_KEY_FILE', '/missing-vapid-key'))
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import ec
            key = serialization.load_pem_private_key(path.read_bytes(), password=None)
            require(isinstance(key, ec.EllipticCurvePrivateKey) and isinstance(key.curve, ec.SECP256R1), 'VAPID key must be a P-256 private key')
        except (OSError, ValueError, TypeError, ImportError):
            errors.append('VAPID private key is missing, unreadable or invalid')
    else:
        warnings.append('Web Push is disabled; lock-screen notifications will not be sent')
    if profile == 'private-test':
        models = Path(cloud_dir) / 'artifacts/models' if cloud_dir else Path(root) / 'backend/models'
        data = Path(cloud_dir) / 'artifacts/bidmc' if cloud_dir else Path(root) / 'backend/data/raw/bidmc'
        require((models / 'bidmc_monitor_v1.joblib').is_file(), 'Trusted BIDMC model is missing; prepare artifacts explicitly')
        try:
            checksums = json.loads((data / 'manifest.json').read_text())['sha256']
            if not isinstance(checksums, dict) or len(checksums) != 53:
                raise ValueError('Unexpected dataset count')
            for name, digest in checksums.items():
                if not re.fullmatch(r'bidmc_\d{2}_Numerics\.csv', name):
                    raise ValueError('Unsafe dataset filename')
                if hashlib.sha256((data / name).read_bytes()).hexdigest() != digest:
                    raise ValueError('Dataset checksum mismatch')
        except (OSError, ValueError, KeyError, TypeError):
            errors.append('BIDMC artifacts are missing or fail their publisher-checksum manifest')
        try:
            metadata = json.loads((models / 'bidmc_monitor_v1_metadata.json').read_text())
            if metadata.get('model_version') != 'bidmc-monitor-v1' or not metadata.get('splits', {}).get('test'):
                raise ValueError('Missing held-out replay split')
            lock = (Path(root) / 'deploy/requirements.lock.txt').read_text()
            expected = re.search(r'^scikit-learn==(.+)$', lock, re.MULTILINE)
            if not expected or metadata.get('sklearn_version') != expected.group(1):
                raise ValueError('Model runtime version mismatch')
        except (OSError, ValueError, TypeError):
            errors.append('Model metadata/runtime mismatch; retrain in the cloud runtime before using it')
        if not values.get('GEMINI_API_KEY'):
            warnings.append('Gemini is not configured; local models, simulation, chat and Push still work')
    warnings.append('SQLite deployment is one host and one staff API worker; do not scale replicas')
    return errors, warnings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=('clinical', 'private-test'), default='clinical')
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--cloud-dir', type=Path, help='Check staged host artifacts/secrets instead of container paths')
    args = parser.parse_args(argv)
    env_file = args.cloud_dir / '.env' if args.cloud_dir else args.env_file or ROOT / 'backend/.env'
    if (args.cloud_dir or args.env_file) and not env_file.is_file():
        parser.error('Explicit environment file is missing')
    file_values = dict(dotenv_values(env_file, interpolate=False)) if env_file.is_file() else {}
    values = {**file_values, **os.environ}
    if args.cloud_dir or args.env_file:
        values = {**os.environ, **file_values}
    errors, warnings = evaluate(values, args.profile, cloud_dir=args.cloud_dir)
    print('Smart Ward deployment preflight:', args.profile)
    for item in errors:
        print('ERROR:', item)
    for item in warnings:
        print('WARN:', item)
    print('Result:', 'BLOCKED' if errors else 'technical environment checks passed')
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
