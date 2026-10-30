"""Create a consistent SQLite backup without overwriting an existing file."""
import argparse
from contextlib import closing
import os
from pathlib import Path
import sqlite3


def backup(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file():
        raise ValueError('Source database does not exist')
    if source == destination:
        raise ValueError('Backup must use a different path')
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src, closing(sqlite3.connect(destination)) as dst:
        src.backup(dst)
        if dst.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise RuntimeError('Backup integrity check failed; do not restore this file')
    return destination


def verify_backup_integrity(backup_db_path) -> dict:
    path = Path(backup_db_path).resolve()
    if not path.is_file():
        raise ValueError(f'Backup database does not exist: {path}')
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as conn:
            integrity_row = conn.execute('PRAGMA integrity_check').fetchone()
            integrity_status = integrity_row[0] if integrity_row else 'error'
            tables = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).fetchall()
            ]
        return {
            'integrity': integrity_status,
            'tables': tables,
        }
    except sqlite3.DatabaseError as err:
        return {
            'integrity': f'error: {err}',
            'tables': [],
        }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', help='Absolute path of the running SQLite database')
    parser.add_argument('destination', help='New backup path; parent directory must already exist')
    parser.add_argument('--verify-only', action='store_true', help='Only verify integrity of destination database')
    args = parser.parse_args()
    if args.verify_only:
        print('Integrity report:', verify_backup_integrity(args.destination))
    else:
        dest = backup(args.source, args.destination)
        report = verify_backup_integrity(dest)
        print('Verified backup:', dest, report)
