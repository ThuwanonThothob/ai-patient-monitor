"""Consistent SQLite snapshots and non-overwriting restore for single-host TEST."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import threading
import uuid

NAME = re.compile(r'ward-\d{8}T\d{6}Z-[a-f0-9]{8}\.sqlite3')
OWNER = 'smart-ward-sqlite-backup-v1'


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def verify(path):
    if path.is_symlink() or not NAME.fullmatch(path.name):
        raise ValueError('Not a managed backup')
    sidecar = path.with_suffix('.json')
    if sidecar.is_symlink():
        raise ValueError('Backup manifest cannot be a symlink')
    manifest = json.loads(sidecar.read_text())
    if manifest.get('created_by') != OWNER or manifest.get('file') != path.name or manifest.get('sha256') != digest(path):
        raise ValueError('Backup checksum or provenance mismatch')
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        if conn.execute('PRAGMA integrity_check').fetchone() != ('ok',):
            raise ValueError('SQLite integrity check failed')
    return manifest


def snapshot(database, directory, keep=7):
    if keep < 1:
        raise ValueError('Keep at least one backup')
    if directory.is_symlink():
        raise ValueError('Backup directory cannot be a symlink')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    name = 'ward-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8] + '.sqlite3'
    path = directory / name
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True, timeout=15)) as source:
            # Source opened read-only; sqlite backup includes committed WAL data.
            with closing(sqlite3.connect(path)) as target:
                source.backup(target, pages=256, sleep=.05)
                if target.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                    raise ValueError('SQLite integrity check failed')
        sidecar = path.with_suffix('.json')
        with sidecar.open('x') as handle:
            json.dump({'created_by': OWNER, 'file': name, 'sha256': digest(path),
                       'created_at': datetime.now(timezone.utc).isoformat()}, handle)
        sidecar.chmod(0o600)
        verify(path)
    except Exception:
        # Only files created by this invocation can be removed here.
        path.unlink(missing_ok=True)
        path.with_suffix('.json').unlink(missing_ok=True)
        raise
    managed = []
    for candidate in directory.iterdir():
        if NAME.fullmatch(candidate.name):
            try:
                verify(candidate)
                managed.append(candidate)
            except (OSError, ValueError, sqlite3.Error):
                pass  # Preserve corrupt/foreign files for manual inspection.
    for old in sorted(managed)[:-keep]:
        old.unlink()
        old.with_suffix('.json').unlink()
    return path


def restore(source, destination):
    verify(source)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('Restore destination must be a new file; existing DB is preserved')
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as original:
            with closing(sqlite3.connect(destination)) as target:
                original.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                    raise ValueError('Restored database failed integrity check')
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for action in ('once', 'loop'):
        p = sub.add_parser(action)
        p.add_argument('--database', type=Path, default=Path('/source') / Path(os.getenv('WARD_DB_PATH', 'ward-test.db')).name)
        p.add_argument('--directory', type=Path, default=Path('/var/lib/smart-ward/backups'))
        p.add_argument('--keep', type=int, default=7)
    p = sub.add_parser('restore')
    p.add_argument('source', type=Path)
    p.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == 'restore':
        restore(args.source, args.destination)
        print('Verified backup restored to a new file; original database preserved.')
        return 0
    if args.keep < 1:
        parser.error('--keep must be at least 1')
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    while not stop.is_set():
        try:
            result = snapshot(args.database, args.directory, args.keep)
            print('Verified SQLite backup:', result.name, flush=True)
        except Exception as error:
            print('Backup failed:', type(error).__name__, flush=True)
            if args.command == 'once':
                return 1
            stop.wait(300)
            continue
        if args.command == 'once':
            return 0
        stop.wait(86400)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
