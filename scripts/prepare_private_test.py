"""Prepare a private TEST environment; never enables public forwarding."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def configuration(host, contact):
    host = host.strip().rstrip('.').lower()
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.[a-z0-9-]+\.ts\.net', host):
        raise ValueError('ต้องใช้ DNS name ของ Mac จาก Tailscale เช่น my-mac.tail123.ts.net')
    if not re.fullmatch(r'[^\s\x00-\x1f@\x7f\"\x27]+@[^\s\x00-\x1f@\x7f\"\x27]+\.[a-zA-Z]{2,}', contact):
        raise ValueError('กรุณาใส่อีเมลติดต่อผู้ดูแลสำหรับ VAPID')
    return {
        'WARD_DEMO_ID_LOGIN': '0', 'WARD_ENABLE_TEST_ACCOUNTS': '1',
        'WARD_COOKIE_SECURE': '1', 'WARD_INGEST_MODE': 'replay',
        'WARD_BEDSIDE_MQTT_ENABLED': '0', 'WARD_WEB_PUSH_ENABLED': '1',
        'WARD_DB_PATH': str(ROOT / 'backend/runtime/ward-private-test.db'),
        'WARD_VAPID_PRIVATE_KEY_FILE': str(ROOT / 'backend/runtime/webpush-private.pem'),
        'WARD_VAPID_SUBJECT': 'mailto:' + contact,
        'WARD_STAFF_ORIGIN': 'https://' + host,
        'WARD_PATIENT_ORIGIN': 'https://' + host + ':8443',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hostname', help='Mac DNS name from Tailscale; auto-detected if omitted')
    parser.add_argument('--contact', help='Operator email for Web Push, never an API key')
    args = parser.parse_args()
    executable = shutil.which('tailscale')
    app_cli = Path('/Applications/Tailscale.app/Contents/MacOS/Tailscale')
    executable = executable or (str(app_cli) if app_cli.exists() else None)
    host = args.hostname
    if not host:
        if not executable:
            raise SystemExit('ติดตั้ง Tailscale บน Mac และ iPhone แล้วเข้าสู่บัญชีเดียวกันก่อน: https://tailscale.com/download')
        result = subprocess.run([executable, 'status', '--json'], capture_output=True, text=True, timeout=15, check=True)
        status = json.loads(result.stdout)
        if status.get('BackendState') != 'Running':
            raise SystemExit('กรุณาเปิด Tailscale และเข้าสู่ระบบก่อน')
        host = status.get('Self', {}).get('DNSName', '')
    contact = args.contact or input('อีเมลติดต่อผู้ดูแล (ใช้กับ Web Push): ').strip()
    values = configuration(host, contact)
    path = ROOT / 'backend/runtime/private-test.env'
    path.parent.mkdir(parents=True, exist_ok=True)
    if not Path(values['WARD_VAPID_PRIVATE_KEY_FILE']).exists():
        subprocess.run([sys.executable, str(ROOT / 'scripts/generate_push_keys.py')], check=True)
    # Preserve an earlier configuration; no silent environment replacement.
    with path.open('x', encoding='utf-8') as output:
        os.chmod(path, 0o600)
        output.write('\n'.join(key + '=' + json.dumps(value) for key, value in values.items()) + '\n')
    print('พร้อม: ' + str(path))
    print('บุคลากร: ' + values['WARD_STAFF_ORIGIN'])
    print('ผู้ป่วย: ' + values['WARD_PATIENT_ORIGIN'])
    print('ขั้นต่อไป: ดู docs/PRIVATE_TEST.md — เปิด Serve เฉพาะ tailnet ห้ามใช้ Funnel')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, FileExistsError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
