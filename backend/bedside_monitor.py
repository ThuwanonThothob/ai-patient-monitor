"""Bedside device-health, pressure-mat inference and human ground truth.

The runtime accepts normalized MQTT events, validates every field, records an
auditable observation and may *propose* a staff review alert. It never diagnoses
pressure injury, changes care, or contacts an external service by itself.
"""
from __future__ import annotations

from contextlib import closing
import base64
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Literal
import zlib

import joblib
import numpy as np
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from ml_pipeline.train_posture import pressure_features


ROOT = Path(__file__).resolve().parent / 'models' / 'posture'
POSTURES = {'left', 'right', 'supine'}
DEVICE_KINDS = {'vital', 'pressure_mat'}
DEVICE_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{2,79}$')
router = APIRouter(prefix='/api/bedside', tags=['bedside-monitor'])
_service: 'BedsideService | None' = None


def connect(database: str) -> sqlite3.Connection:
    conn = sqlite3.connect(database, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(database: str) -> None:
    with closing(connect(database)) as conn, conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS bedside_device_status (
            device_id TEXT PRIMARY KEY, patient_id TEXT NOT NULL, kind TEXT NOT NULL,
            last_seen REAL NOT NULL, battery_percent REAL NOT NULL, signal_quality REAL NOT NULL,
            sensor_attached INTEGER NOT NULL, calibration_due_at REAL, status TEXT NOT NULL,
            issues_json TEXT NOT NULL, source TEXT NOT NULL, updated_at REAL NOT NULL,
            UNIQUE(patient_id,kind));
        CREATE TABLE IF NOT EXISTS bedside_device_observations (
            id INTEGER PRIMARY KEY, device_id TEXT NOT NULL, patient_id TEXT NOT NULL,
            kind TEXT NOT NULL, observed_at REAL NOT NULL, battery_percent REAL NOT NULL,
            signal_quality REAL NOT NULL, sensor_attached INTEGER NOT NULL,
            calibration_due_at REAL, status TEXT NOT NULL, issues_json TEXT NOT NULL,
            source TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_device_observations_patient_time
            ON bedside_device_observations(patient_id,observed_at DESC);
        CREATE TABLE IF NOT EXISTS bedside_posture_observations (
            id INTEGER PRIMARY KEY, patient_id TEXT NOT NULL, device_id TEXT NOT NULL,
            observed_at REAL NOT NULL, prediction TEXT NOT NULL, confidence REAL,
            model_version TEXT NOT NULL, pressure_sha256 TEXT NOT NULL,
            features_json TEXT NOT NULL, source TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_posture_observations_patient_time
            ON bedside_posture_observations(patient_id,observed_at DESC);
        CREATE TABLE IF NOT EXISTS bedside_posture_state (
            patient_id TEXT PRIMARY KEY, posture TEXT NOT NULL, posture_since REAL NOT NULL,
            last_seen REAL NOT NULL, last_observation_id INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS bedside_ground_truth (
            id INTEGER PRIMARY KEY, request_key TEXT NOT NULL UNIQUE, patient_id TEXT NOT NULL,
            observation_id INTEGER, label_type TEXT NOT NULL, label TEXT NOT NULL,
            notes TEXT NOT NULL, recorded_by TEXT NOT NULL, observed_at REAL NOT NULL,
            created_at REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_ground_truth_patient_time
            ON bedside_ground_truth(patient_id,observed_at DESC);
        ''')


class PostureRuntime:
    """Load only the locally trained artifact after verifying both hashes."""
    def __init__(self, root: Path = ROOT) -> None:
        self.root = root
        self.model: Any | None = None
        self.model_version = 'posture-unavailable'
        self.cutoff = .6
        self.error: str | None = None

    def load(self) -> None:
        try:
            pointer = json.loads((self.root / 'current.json').read_text())
            run_id = pointer['run_id']
            if not re.fullmatch(r'[A-Za-z0-9_-]+', run_id):
                raise ValueError('invalid run id')
            folder = self.root / run_id
            report_bytes = (folder / 'report.json').read_bytes()
            if hashlib.sha256(report_bytes).hexdigest() != pointer['report_sha256']:
                raise ValueError('report checksum mismatch')
            report = json.loads(report_bytes)
            model_path = folder / 'models.joblib'
            if hashlib.sha256(model_path.read_bytes()).hexdigest() != report['model_sha256']:
                raise ValueError('model checksum mismatch')
            bundle = joblib.load(model_path)
            selected = report['selected_model']
            if selected not in bundle['models']:
                raise ValueError('selected model missing')
            self.model = bundle['models'][selected]
            self.model_version = f"posture-{run_id}-{selected}"
            self.cutoff = float(report.get('confidence_cutoff', .6))
            self.error = None
        except Exception as error:  # artifact absence/tamper => abstain, never guess
            self.model = None
            self.error = type(error).__name__

    def assess(self, pressure_map: Any) -> dict[str, Any]:
        features = pressure_features(pressure_map)
        if self.model is None:
            return {'prediction': 'ABSTAIN', 'confidence': None, 'features': features,
                    'model_version': self.model_version, 'reason': 'MODEL_UNAVAILABLE'}
        probabilities = self.model.predict_proba(features[None, :])[0]
        classes = self.model.classes_.tolist()
        index = int(np.argmax(probabilities))
        confidence = float(probabilities[index])
        prediction = str(classes[index]) if confidence >= self.cutoff else 'ABSTAIN'
        return {'prediction': prediction, 'confidence': confidence, 'features': features,
                'model_version': self.model_version,
                'reason': 'ACCEPTED' if prediction != 'ABSTAIN' else 'LOW_MODEL_CONFIDENCE'}


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _pressure_map(payload: dict[str, Any]) -> np.ndarray:
    """Decode either plain JSON or a bounded zlib+base64 JSON frame."""
    if 'pressure_map' in payload:
        return np.asarray(payload['pressure_map'], dtype=float)
    if payload.get('pressure_encoding') != 'zlib+base64+json' or payload.get('pressure_shape') != [32, 64]:
        raise ValueError('missing/unsupported pressure map encoding')
    encoded = payload.get('pressure_data')
    if not isinstance(encoded, str) or len(encoded) > 50000:
        raise ValueError('invalid compressed pressure map')
    try:
        compressed = base64.b64decode(encoded, validate=True)
        if len(compressed) > 32768:
            raise ValueError('compressed pressure map too large')
        decoder = zlib.decompressobj()
        decoded = decoder.decompress(compressed, 65537)
        if len(decoded) > 65536 or not decoder.eof or decoder.unused_data:
            raise ValueError('invalid compressed pressure stream')
        return np.asarray(json.loads(decoded), dtype=float)
    except (ValueError, TypeError, json.JSONDecodeError, zlib.error) as error:
        raise ValueError('invalid compressed pressure map') from error


def _alert(patient_id: str, severity: str, reason: str, key: str, timestamp: float, next_step: str) -> dict[str, Any]:
    return {'type': 'agent_alert', 'patient_id': patient_id, 'severity': severity,
            'reason': reason, 'episode_key': key, 'vitals': {}, 'risk_percent': None,
            'recommended_next_step': next_step, 'requires_human_review': True,
            'timestamp': timestamp}


class BedsideService:
    def __init__(self, database: str, registry: dict[str, Any], *, stale_seconds: int = 30,
                 turn_seconds: int = 7200, posture_runtime: PostureRuntime | None = None,
                 dataset_export_key: str | None = None) -> None:
        self.database = database
        self.registry = registry
        self.stale_seconds = max(5, int(stale_seconds))
        self.turn_seconds = max(30, int(turn_seconds))
        self.dataset_export_key = dataset_export_key
        self.posture = posture_runtime or PostureRuntime()
        init_db(database)
        self.posture.load()

    def _identity(self, payload: dict[str, Any], expected_kind: str | None = None) -> tuple[str, str, str, float, str]:
        patient_id = str(payload.get('patient_id', '')).upper()
        device_id = str(payload.get('device_id', ''))
        kind = str(payload.get('kind', expected_kind or ''))
        timestamp = payload.get('timestamp', time.time())
        source = str(payload.get('source', 'MQTT'))[:30]
        if patient_id not in self.registry or not DEVICE_ID.fullmatch(device_id) or kind not in DEVICE_KINDS:
            raise ValueError('invalid bedside identity')
        if expected_kind and kind != expected_kind:
            raise ValueError('unexpected device kind')
        if not _finite(timestamp) or abs(time.time() - float(timestamp)) > 60:
            raise ValueError('stale/future bedside timestamp')
        return patient_id, device_id, kind, float(timestamp), source

    def _observe_episode(self, conn: sqlite3.Connection, patient_id: str, key: str, abnormal: bool, timestamp: float) -> None:
        if 'episode_key' not in {row[1] for row in conn.execute('PRAGMA table_info(agent_alerts)')}:
            return
        if abnormal:
            conn.execute("""UPDATE agent_alerts SET last_seen_at=?,occurrences=occurrences+1,recovered_at=NULL
                WHERE patient_id=? AND episode_key=? AND merged_into IS NULL
                AND status IN ('NEW','ACKNOWLEDGED','ESCALATED') AND COALESCE(last_seen_at,0)<?""",
                         (timestamp, patient_id, key, timestamp))
        else:
            conn.execute("""UPDATE agent_alerts SET recovered_at=? WHERE patient_id=? AND episode_key=?
                AND merged_into IS NULL AND status IN ('NEW','ACKNOWLEDGED','ESCALATED')
                AND recovered_at IS NULL AND last_seen_at<?""", (timestamp, patient_id, key, timestamp))

    def process_device(self, payload: dict[str, Any]) -> dict[str, Any]:
        patient_id, device_id, kind, timestamp, source = self._identity(payload)
        battery, signal = payload.get('battery_percent'), payload.get('signal_quality')
        attached, calibration = payload.get('sensor_attached'), payload.get('calibration_due_at')
        if not _finite(battery) or not 0 <= float(battery) <= 100 or not _finite(signal) or not 0 <= float(signal) <= 1:
            raise ValueError('invalid battery/signal')
        if not isinstance(attached, bool) or (calibration is not None and not _finite(calibration)):
            raise ValueError('invalid attachment/calibration')
        issues = []
        if not attached: issues.append('SENSOR_DETACHED')
        if float(battery) < 10: issues.append('BATTERY_CRITICAL')
        elif float(battery) < 20: issues.append('BATTERY_LOW')
        if float(signal) < .25: issues.append('SIGNAL_CRITICAL')
        elif float(signal) < .5: issues.append('SIGNAL_LOW')
        if calibration is not None and float(calibration) <= timestamp: issues.append('CALIBRATION_DUE')
        critical = any(issue in {'SENSOR_DETACHED', 'BATTERY_CRITICAL', 'SIGNAL_CRITICAL'} for issue in issues)
        status = 'CRITICAL' if critical else 'WARNING' if issues else 'OK'
        key = f'device_{kind}'
        with closing(connect(self.database)) as conn, conn:
            conn.execute('''INSERT INTO bedside_device_observations
                (device_id,patient_id,kind,observed_at,battery_percent,signal_quality,sensor_attached,
                 calibration_due_at,status,issues_json,source) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (device_id, patient_id, kind, timestamp, float(battery), float(signal), int(attached),
                 calibration, status, json.dumps(issues), source))
            conn.execute('''INSERT INTO bedside_device_status
                (device_id,patient_id,kind,last_seen,battery_percent,signal_quality,sensor_attached,
                 calibration_due_at,status,issues_json,source,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                 ON CONFLICT(patient_id,kind) DO UPDATE SET device_id=excluded.device_id,last_seen=excluded.last_seen,
                 battery_percent=excluded.battery_percent,signal_quality=excluded.signal_quality,
                 sensor_attached=excluded.sensor_attached,calibration_due_at=excluded.calibration_due_at,
                 status=excluded.status,issues_json=excluded.issues_json,source=excluded.source,updated_at=excluded.updated_at''',
                (device_id, patient_id, kind, timestamp, float(battery), float(signal), int(attached),
                 calibration, status, json.dumps(issues), source, time.time()))
            self._observe_episode(conn, patient_id, key, bool(issues), timestamp)
        alert = None
        if issues:
            alert = _alert(patient_id, 'critical' if critical else 'warning',
                f"Bedside {kind} device requires review: {', '.join(issues)}.", key, timestamp,
                'Check sensor placement, power, signal and calibration; document the result before closing.')
        return {'patient_id': patient_id, 'device_id': device_id, 'kind': kind, 'status': status,
                'issues': issues, 'timestamp': timestamp, 'alert': alert}

    def process_pressure(self, payload: dict[str, Any]) -> dict[str, Any]:
        patient_id, device_id, _, timestamp, source = self._identity(payload, 'pressure_mat')
        device = self.process_device(payload)
        raw = _pressure_map(payload)
        inference = self.posture.assess(raw)
        digest = hashlib.sha256(raw.astype('<f8', copy=False).tobytes()).hexdigest()
        features_json = json.dumps(inference['features'].tolist(), allow_nan=False)
        with closing(connect(self.database)) as conn, conn:
            cursor = conn.execute('''INSERT INTO bedside_posture_observations
                (patient_id,device_id,observed_at,prediction,confidence,model_version,pressure_sha256,features_json,source)
                VALUES (?,?,?,?,?,?,?,?,?)''', (patient_id, device_id, timestamp, inference['prediction'],
                inference['confidence'], inference['model_version'], digest, features_json, source))
            observation_id = int(cursor.lastrowid)
            previous = conn.execute('SELECT posture,posture_since FROM bedside_posture_state WHERE patient_id=?', (patient_id,)).fetchone()
            dwell = None
            if inference['prediction'] in POSTURES:
                posture_since = previous['posture_since'] if previous and previous['posture'] == inference['prediction'] else timestamp
                dwell = max(0., timestamp - posture_since)
                conn.execute('''INSERT INTO bedside_posture_state VALUES (?,?,?,?,?)
                    ON CONFLICT(patient_id) DO UPDATE SET posture=excluded.posture,posture_since=excluded.posture_since,
                    last_seen=excluded.last_seen,last_observation_id=excluded.last_observation_id''',
                    (patient_id, inference['prediction'], posture_since, timestamp, observation_id))
            due = dwell is not None and dwell >= self.turn_seconds
            self._observe_episode(conn, patient_id, 'posture_turn_due', due, timestamp)
        posture_alert = _alert(patient_id, 'warning',
            f"An accepted pressure-mat posture remained unchanged for {int(dwell or 0)} seconds.",
            'posture_turn_due', timestamp,
            'Verify the patient and follow the human-reviewed repositioning plan; the model does not diagnose pressure injury.') if due else None
        return {'patient_id': patient_id, 'device': device, 'observation_id': observation_id,
                'prediction': inference['prediction'], 'confidence': inference['confidence'],
                'model_version': inference['model_version'], 'reason': inference['reason'],
                'dwell_seconds': dwell, 'timestamp': timestamp,
                'alerts': [alert for alert in (device['alert'], posture_alert) if alert]}

    def evaluate_stale(self, now: float | None = None) -> list[dict[str, Any]]:
        now = time.time() if now is None else now
        alerts = []
        with closing(connect(self.database)) as conn, conn:
            rows = conn.execute("SELECT * FROM bedside_device_status WHERE last_seen<? AND status!='STALE'", (now - self.stale_seconds,)).fetchall()
            for row in rows:
                conn.execute("UPDATE bedside_device_status SET status='STALE',issues_json='[\"HEARTBEAT_LOST\"]',updated_at=? WHERE device_id=?", (now, row['device_id']))
                key = f"device_{row['kind']}"
                self._observe_episode(conn, row['patient_id'], key, True, now)
                alerts.append(_alert(row['patient_id'], 'critical', f"Bedside {row['kind']} device heartbeat is stale.", key, now,
                    'Check the device, network and patient directly; a missing signal is not evidence of safety.'))
        return alerts

    def record_truth(self, *, request_key: str, patient_id: str, observation_id: int | None,
                     label_type: str, label: str, notes: str, actor: str,
                     observed_at: float | None = None) -> dict[str, Any]:
        if patient_id not in self.registry:
            raise ValueError('unknown patient')
        allowed = {'posture': POSTURES | {'other', 'empty_bed'},
                   'device_fault': {'none', 'detached', 'low_battery', 'poor_signal', 'calibration_due'},
                   'alert_outcome': {'true_positive', 'false_positive', 'missed_event', 'uncertain'}}
        if label_type not in allowed or label not in allowed[label_type]:
            raise ValueError('unsupported ground-truth label')
        at = time.time() if observed_at is None else observed_at
        if not _finite(at) or abs(time.time() - float(at)) > 86400 * 7:
            raise ValueError('invalid observed_at')
        with closing(connect(self.database)) as conn, conn:
            if observation_id is not None:
                row = conn.execute('SELECT patient_id FROM bedside_posture_observations WHERE id=?', (observation_id,)).fetchone()
                if not row or row['patient_id'] != patient_id:
                    raise ValueError('observation does not belong to patient')
            conn.execute('''INSERT OR IGNORE INTO bedside_ground_truth
                (request_key,patient_id,observation_id,label_type,label,notes,recorded_by,observed_at,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)''', (request_key, patient_id, observation_id, label_type,
                label, notes[:500], actor, float(at), time.time()))
            row = conn.execute('SELECT * FROM bedside_ground_truth WHERE request_key=?', (request_key,)).fetchone()
        return dict(row)

    def patient(self, patient_id: str) -> dict[str, Any]:
        if patient_id not in self.registry:
            raise KeyError(patient_id)
        with closing(connect(self.database)) as conn:
            devices = [dict(row) for row in conn.execute('SELECT * FROM bedside_device_status WHERE patient_id=? ORDER BY kind', (patient_id,))]
            posture = conn.execute('''SELECT o.*,s.posture_since FROM bedside_posture_observations o
                LEFT JOIN bedside_posture_state s ON s.patient_id=o.patient_id WHERE o.patient_id=?
                ORDER BY o.observed_at DESC LIMIT 1''', (patient_id,)).fetchone()
            labels = [dict(row) for row in conn.execute('''SELECT id,observation_id,label_type,label,notes,recorded_by,observed_at,created_at
                FROM bedside_ground_truth WHERE patient_id=? ORDER BY observed_at DESC LIMIT 20''', (patient_id,))]
        for device in devices:
            device['sensor_attached'] = bool(device['sensor_attached'])
            device['issues'] = json.loads(device.pop('issues_json'))
        latest = dict(posture) if posture else None
        if latest:
            latest.pop('features_json', None)
            latest['dwell_seconds'] = max(0., latest['observed_at'] - latest['posture_since']) if latest['prediction'] in POSTURES else None
            labelled = any(item['label_type'] == 'posture' and item['observation_id'] == latest['id'] for item in labels)
            latest['model_output_blinded'] = not labelled
            if not labelled:
                # Ground-truth collection must not leak the answer shown by AI.
                latest['prediction'] = 'HIDDEN_PENDING_GROUND_TRUTH'
                latest['confidence'] = None
        return {'patient_id': patient_id, 'devices': devices, 'posture': latest, 'ground_truth': labels,
                'posture_model': {'status': 'READY' if self.posture.model is not None else 'UNAVAILABLE',
                                  'version': self.posture.model_version, 'error': self.posture.error},
                'research_only': True}

    def summary(self) -> dict[str, Any]:
        with closing(connect(self.database)) as conn:
            rows = conn.execute('SELECT status,COUNT(*) AS count FROM bedside_device_status GROUP BY status').fetchall()
            labels = conn.execute('SELECT COUNT(*) FROM bedside_ground_truth').fetchone()[0]
            observations = conn.execute('SELECT COUNT(*) FROM bedside_posture_observations').fetchone()[0]
        return {'devices': {row['status']: row['count'] for row in rows}, 'ground_truth_labels': labels,
                'posture_observations': observations,
                'posture_model': 'READY' if self.posture.model is not None else 'UNAVAILABLE'}

    def dataset_jsonl(self) -> str:
        if not self.dataset_export_key or len(self.dataset_export_key) < 16:
            raise RuntimeError('WARD_DATASET_EXPORT_KEY is required for pseudonymous export')
        with closing(connect(self.database)) as conn:
            rows = conn.execute('''SELECT o.id,o.patient_id,o.observed_at,o.prediction,o.confidence,o.model_version,
                o.pressure_sha256,o.features_json,g.label,g.created_at
                FROM bedside_posture_observations o JOIN bedside_ground_truth g
                ON g.observation_id=o.id AND g.label_type='posture' ORDER BY o.id''').fetchall()
        records = []
        for row in rows:
            subject_key = hmac.new(self.dataset_export_key.encode(), row['patient_id'].encode(), hashlib.sha256).hexdigest()[:24]
            records.append(json.dumps({
                **{key: row[key] for key in row.keys() if key not in {'features_json', 'patient_id'}},
                'subject_key': subject_key,
                'features': json.loads(row['features_json']),
            }, ensure_ascii=False, allow_nan=False))
        return '\n'.join(records)


def configure(database: str, registry: dict[str, Any], **kwargs: Any) -> BedsideService:
    global _service
    _service = BedsideService(database, registry, **kwargs)
    return _service


def service() -> BedsideService:
    if _service is None:
        raise HTTPException(503, 'Bedside monitor is not initialized')
    return _service


class GroundTruthInput(BaseModel):
    request_key: str = Field(min_length=12, max_length=100, pattern=r'^[A-Za-z0-9._:-]+$')
    patient_id: str = Field(pattern=r'^[ABC](00[1-9]|01[0-9]|020)$')
    observation_id: int | None = Field(default=None, ge=1)
    label_type: Literal['posture', 'device_fault', 'alert_outcome']
    label: str = Field(min_length=2, max_length=50)
    notes: str = Field(default='', max_length=500)
    observed_at: float | None = None


@router.get('/status')
def api_status(): return service().summary()


@router.get('/patients/{patient_id}')
def api_patient(patient_id: str):
    try: return service().patient(patient_id.upper())
    except KeyError: raise HTTPException(404, 'Unknown Patient ID')


@router.post('/ground-truth', status_code=201)
def api_ground_truth(payload: GroundTruthInput, request: Request):
    try:
        return service().record_truth(**payload.model_dump(), actor=request.state.subject)
    except ValueError as error:
        raise HTTPException(422, str(error))


@router.get('/dataset.jsonl', response_class=PlainTextResponse)
def api_dataset():
    try:
        content = service().dataset_jsonl()
    except RuntimeError as error:
        raise HTTPException(503, str(error))
    return PlainTextResponse(content, media_type='application/x-ndjson', headers={
        'Content-Disposition': 'attachment; filename="bedside-ground-truth.jsonl"',
        'Cache-Control': 'no-store',
    })
