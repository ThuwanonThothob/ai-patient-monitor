"""One Uvicorn worker per audience; exit for Docker to restart failed workers."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from healthcheck import check


def main():
    audience = sys.argv[1] if len(sys.argv) == 2 else ''
    if audience not in {'staff', 'patient'}:
        raise SystemExit('Expected staff or patient')
    root = Path(__file__).resolve().parents[1]
    verified = subprocess.run([sys.executable, str(root / 'scripts/deployment_preflight.py'),
                               '--profile', 'private-test'], check=False)
    if verified.returncode:
        return verified.returncode
    app, port = ('main:app', '8000') if audience == 'staff' else ('patient_api:app', '8001')
    child = subprocess.Popen([sys.executable, '-m', 'uvicorn', app, '--host', '0.0.0.0',
                              '--port', port, '--workers', '1', '--no-access-log'],
                             cwd=root / 'backend')
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
        if child.poll() is None:
            child.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    deadline = time.monotonic() + 120
    failures = 0
    try:
        while not stopping:
            code = child.poll()
            if code is not None:
                return code or 1
            try:
                check(audience)
                failures = 0
            except Exception as error:
                if time.monotonic() >= deadline:
                    failures += 1
                    print(f'{audience} readiness failed ({failures}/3): {type(error).__name__}', flush=True)
                    if failures >= 3:
                        return 1
            for _ in range(15):
                if stopping or child.poll() is not None:
                    break
                time.sleep(1)
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
