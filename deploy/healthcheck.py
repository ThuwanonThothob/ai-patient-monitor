"""Read-only readiness probe. Fresh TEST_P cannot mask a stopped ward replay."""
import json
import os
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path
from urllib.request import ProxyHandler, build_opener


def check(audience, *, now=None):
    port = 8001 if audience == 'patient' else 8000
    with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{port}/health', timeout=3) as response:
        payload = json.loads(response.read(4096))
    if payload.get('status') != 'ok' or payload.get('portal') != audience:
        raise RuntimeError('API_NOT_READY')
    database = Path(os.environ['WARD_DB_PATH'])
    current = time.time() if now is None else now
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=2)) as conn:
        conn.execute('SELECT 1 FROM portal_accounts LIMIT 1').fetchone()
        if audience == 'staff':
            if os.getenv('WARD_INGEST_MODE') == 'replay':
                worker = conn.execute('SELECT heartbeat,status FROM monitor_worker WHERE id=1').fetchone()
                if not worker or worker[1] != 'RUNNING' or not -5 <= current - worker[0] < 30:
                    raise RuntimeError('WARD_WORKER_NOT_RUNNING')
                row = conn.execute("SELECT MAX(updated_at) FROM monitor_results WHERE patient_id NOT LIKE 'TEST_%'").fetchone()
                if not row or row[0] is None or not -5 <= current - row[0] < 30:
                    raise RuntimeError('WARD_REPLAY_STALE')
            if os.getenv('WARD_ENABLE_TEST_ACCOUNTS') == '1':
                row = conn.execute("SELECT updated_at FROM monitor_results WHERE patient_id='TEST_P'").fetchone()
                if not row or not -5 <= current - row[0] < 30:
                    raise RuntimeError('TEST_SIMULATION_STALE')


if __name__ == '__main__':
    try:
        check(sys.argv[1])
    except Exception as error:
        # Never print request URLs, database contents or credentials.
        print('Not ready:', type(error).__name__)
        raise SystemExit(1)
