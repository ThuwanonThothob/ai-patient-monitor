"""Publish deterministic bedside device-health and pressure-mat demo events.

This is a bench-test utility, not a medical device emulator. Pressure maps are
verified held-out PMD research cases; their labels are printed locally and are
not sent to the inference runtime.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import zlib

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = ROOT / 'backend' / 'models' / 'posture'
load_dotenv(ROOT / 'backend' / '.env', override=False)


def verified_case(posture: str) -> tuple[list[list[float]], str, str]:
    pointer_bytes = (MODEL_ROOT / 'current.json').read_bytes()
    pointer = json.loads(pointer_bytes)
    run_id = pointer['run_id']
    if not re.fullmatch(r'[A-Za-z0-9_-]+', run_id):
        raise RuntimeError('invalid posture run id')
    folder = MODEL_ROOT / run_id
    report_bytes = (folder / 'report.json').read_bytes()
    if hashlib.sha256(report_bytes).hexdigest() != pointer['report_sha256']:
        raise RuntimeError('posture report checksum mismatch')
    report = json.loads(report_bytes)
    for item in report['cases']:
        case_path = folder / 'cases' / (item['id'] + '.json')
        content = case_path.read_bytes()
        if hashlib.sha256(content).hexdigest() != item['sha256']:
            raise RuntimeError('posture case checksum mismatch')
        case = json.loads(content)
        if case['label'] == posture:
            return case['pressure_map'], case['label'], item['id']
    raise RuntimeError('no held-out case for posture ' + posture)


def device_payload(patient_id: str, kind: str, *, battery: float = 82,
                   signal: float = .92, attached: bool = True) -> dict:
    return {
        'message_type': 'device_health', 'patient_id': patient_id,
        'device_id': f'{patient_id}-{kind}-demo', 'kind': kind,
        'timestamp': time.time(), 'battery_percent': battery,
        'signal_quality': signal, 'sensor_attached': attached,
        'calibration_due_at': time.time() + 86400 * 30,
        'source': 'SIMULATION',
    }


def publish(client: mqtt.Client, topic: str, payload: dict) -> None:
    payload['timestamp'] = time.time()
    result = client.publish(topic, json.dumps(payload, separators=(',', ':')), qos=1)
    result.wait_for_publish(timeout=10)
    if result.rc != mqtt.MQTT_ERR_SUCCESS:
        raise RuntimeError(f'MQTT publish failed: {result.rc}')
    print(f"sent {payload['patient_id']} {payload['kind']} {payload['message_type']}")


def run(args: argparse.Namespace) -> None:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport='websockets')
    connected = threading.Event()
    failure: list[str] = []
    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            failure.append(str(reason_code))
        else:
            connected.set()
    def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
        if reason_code.is_failure:
            failure.append('disconnect: ' + str(reason_code))
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    try:
        client.connect(args.broker, args.port, 60)
    except OSError as error:
        raise SystemExit(
            f'ต่อ MQTT ไม่ได้ที่ {args.broker}:{args.port} ({type(error).__name__}). '
            'ตรวจ backend/.env, อินเทอร์เน็ต และว่า broker รองรับ WebSocket port นี้'
        ) from None
    client.loop_start()
    try:
        if not connected.wait(10):
            raise RuntimeError('MQTT CONNACK timeout' + (': ' + failure[-1] if failure else ''))
        if args.scenario == 'demo':
            publish(client, args.topic, device_payload('A001', 'vital'))
            pressure_map, label, case_id = verified_case('supine')
            pressure = device_payload('A001', 'pressure_mat')
            packed = zlib.compress(json.dumps(pressure_map, separators=(',', ':')).encode(), level=6)
            pressure.update(message_type='pressure_map', pressure_encoding='zlib+base64+json',
                            pressure_shape=[32, 64], pressure_data=base64.b64encode(packed).decode())
            publish(client, args.topic, pressure)
            publish(client, args.topic, device_payload('A002', 'vital', battery=5))
            publish(client, args.topic, device_payload('A003', 'pressure_mat', attached=False))
            publish(client, args.topic, device_payload('A004', 'vital'))
            print(f'pressure fixture {case_id}; hidden source label={label}')
            print('A004 will become STALE after WARD_DEVICE_STALE_SECONDS if no new heartbeat is sent.')
        else:
            health = device_payload(args.patient, args.kind, battery=args.battery,
                                    signal=args.signal, attached=not args.detached)
            if args.posture:
                if args.kind != 'pressure_mat':
                    raise RuntimeError('--posture requires --kind pressure_mat')
                pressure_map, label, case_id = verified_case(args.posture)
                packed = zlib.compress(json.dumps(pressure_map, separators=(',', ':')).encode(), level=6)
                health.update(message_type='pressure_map', pressure_encoding='zlib+base64+json',
                              pressure_shape=[32, 64], pressure_data=base64.b64encode(packed).decode())
                print(f'pressure fixture {case_id}; hidden source label={label}')
            publish(client, args.topic, health)
    finally:
        client.loop_stop()
        client.disconnect()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Publish bedside bench-test MQTT events.')
    parser.add_argument('--broker', default=os.getenv('MQTT_BROKER', 'localhost'))
    parser.add_argument('--port', type=int, default=int(os.getenv('MQTT_PORT', '8083')))
    parser.add_argument('--topic', default=os.getenv('WARD_BEDSIDE_TOPIC', 'my_ai_hospital/bedside'))
    parser.add_argument('--scenario', choices=('single', 'demo'), default='demo')
    parser.add_argument('--patient', default='A001')
    parser.add_argument('--kind', choices=('vital', 'pressure_mat'), default='vital')
    parser.add_argument('--battery', type=float, default=82)
    parser.add_argument('--signal', type=float, default=.92)
    parser.add_argument('--detached', action='store_true')
    parser.add_argument('--posture', choices=('left', 'right', 'supine'))
    args = parser.parse_args()
    if not re.fullmatch(r'[ABC](00[1-9]|01[0-9]|020)', args.patient):
        parser.error('--patient must be A001-A020, B001-B020, or C001-C020')
    if not 0 <= args.battery <= 100 or not 0 <= args.signal <= 1:
        parser.error('--battery must be 0-100 and --signal must be 0-1')
    return args


if __name__ == '__main__':
    run(parse_args())
