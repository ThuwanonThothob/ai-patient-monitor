#!/usr/bin/env python3
"""Stage private TEST files locally; never provision or pay for a server."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

ROOT = Path(__file__).resolve().parents[1]


def hostname(value):
    value = value.lower()
    if (len(value) > 253 or '.' not in value or value.endswith(('.local', '.localhost', '.internal'))
            or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part) for part in value.split('.'))
            or re.fullmatch(r'[\d.]+', value)):
        raise argparse.ArgumentTypeError('Use a public DNS hostname without https:// or a path')
    return value


def write_private(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(content)


def stage_artifacts(source, destination):
    """Only trusted repository ML outputs and public BIDMC numerics, no DB."""
    models, data = source / 'backend/models', source / 'backend/data/raw/bidmc'
    required = (models / 'bidmc_monitor_v1.joblib', models / 'bidmc_monitor_v1_metadata.json', data / 'manifest.json')
    if not all(path.is_file() for path in required):
        raise ValueError('Prepare BIDMC numerics and train_bidmc locally first; no automatic download is performed')
    if destination.exists():
        raise FileExistsError('Existing staged artifacts preserved; choose a new deployment directory to update')
    for directory in (models, data):
        if directory.is_symlink() or any(path.is_symlink() for path in directory.rglob('*')):
            raise ValueError('Artifact symlinks are not accepted')
    destination.mkdir()
    manifest = {}
    for directory, name in ((models, 'models'), (data, 'bidmc')):
        for path in directory.rglob('*'):
            if not path.is_file() or path.name.startswith('.') or '__pycache__' in path.parts:
                continue
            if path.suffix not in {'.joblib', '.json', '.csv', '.md'} and path.name != 'LICENSE':
                continue
            relative = Path(name) / path.relative_to(directory)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            target.chmod(0o644)
            manifest[str(relative)] = hashlib.sha256(target.read_bytes()).hexdigest()
    (destination / 'manifest.json').write_text(json.dumps({
        'created_at': datetime.now(timezone.utc).isoformat(),
        'note': 'Trusted model outputs and public research replay only; no patient database',
        'sha256': manifest,
    }, indent=2) + '\n')
    return len(manifest)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staff-host', type=hostname, required=True)
    parser.add_argument('--patient-host', type=hostname, required=True)
    parser.add_argument('--email', required=True, help='Real certificate and Web Push contact')
    parser.add_argument('--output', type=Path, default=ROOT / 'deploy')
    args = parser.parse_args(argv)
    if args.staff_host == args.patient_host:
        parser.error('Use different hostnames for staff and patient')
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', args.email):
        parser.error('Enter a valid contact email')
    args.output.mkdir(parents=True, exist_ok=True)
    env_path, secret_path = args.output / '.env', args.output / 'secrets/webpush-private.pem'
    if env_path.exists() or secret_path.exists() or (args.output / 'artifacts').exists():
        parser.error('Existing config, secrets or artifacts preserved; use a new --output directory')
    count = stage_artifacts(ROOT, args.output / 'artifacts')
    secret_path.parent.mkdir(mode=0o700, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    write_private(secret_path, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    values = {
        'WARD_STAFF_HOST': args.staff_host, 'WARD_PATIENT_HOST': args.patient_host,
        'ACME_EMAIL': args.email,
        'WARD_STAFF_ORIGIN': 'https://' + args.staff_host,
        'WARD_PATIENT_ORIGIN': 'https://' + args.patient_host,
        'WARD_DEMO_ID_LOGIN': '0', 'WARD_ENABLE_TEST_ACCOUNTS': '1',
        'WARD_TEST_DOCTOR_PASSWORD': secrets.token_urlsafe(24),
        'WARD_TEST_PATIENT_PASSWORD': secrets.token_urlsafe(24),
        'WARD_STAFF_PASSWORD': secrets.token_urlsafe(48),
        'WARD_COOKIE_SECURE': '1', 'WARD_INGEST_MODE': 'replay',
        'WARD_BEDSIDE_MQTT_ENABLED': '0', 'WARD_DASHBOARD_LLM': '0',
        'WARD_DB_PATH': '/var/lib/smart-ward/ward-test.db',
        'WARD_WEB_PUSH_ENABLED': '1',
        'WARD_VAPID_PRIVATE_KEY_FILE': '/run/secrets/webpush_private',
        'WARD_VAPID_SUBJECT': 'mailto:' + args.email,
        'WARD_DATASET_EXPORT_KEY': secrets.token_urlsafe(32),
    }
    write_private(env_path, ('# Private TEST secrets: keep out of Git and screenshots.\n'
                  + '\n'.join(f'{key}={value}' for key, value in values.items()) + '\n').encode())
    print(f'Prepared {count} trusted artifact files and fresh credentials in {args.output}')
    print('Passwords are only in .env; they were not printed. TEST IDs remain test_d and test_p.')
    print('No server was provisioned, no port opened and no paid API called.')
    print('Next: python scripts/deployment_preflight.py --profile private-test --cloud-dir ' + str(args.output))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
