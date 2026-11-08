"""Always-on local worker. Runs once in staff backend, independent of logins."""
import asyncio
from collections import defaultdict, deque
import json
import logging
import math
from pathlib import Path
from contextlib import closing
import sqlite3
import time

from ai_models import monitor_model
from ai_models.news2 import calculate_modified_news2
from ml_pipeline.bidmc import load_recordings, KEYS

log = logging.getLogger(__name__)


def monitor_db_connect(database: str, timeout: float = 30.0) -> sqlite3.Connection:
    conn = sqlite3.connect(database, timeout=timeout)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_monitor_db(database):
    with closing(monitor_db_connect(database)) as conn, conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('CREATE TABLE IF NOT EXISTS monitor_results (patient_id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at REAL NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS monitor_worker (id INTEGER PRIMARY KEY CHECK(id=1), heartbeat REAL, status TEXT, error TEXT)')
        conn.execute('CREATE TABLE IF NOT EXISTS monitor_components (name TEXT PRIMARY KEY, heartbeat REAL, status TEXT, error TEXT)')
        conn.execute('''CREATE TABLE IF NOT EXISTS monitor_analysis_logs (
            patient_id TEXT NOT NULL, evaluated_at REAL NOT NULL, source TEXT NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(patient_id,evaluated_at))''')


def patient_state(database, patient_id):
    from patient_registry import get_patient_profile
    profile = get_patient_profile(patient_id) or {}
    with closing(monitor_db_connect(database)) as conn:
        row = conn.execute('SELECT payload FROM monitor_results WHERE patient_id=?', (patient_id,)).fetchone()
    if not row:
        return {
            'patient_id': patient_id,
            'status': 'WAITING',
            'patient_profile': profile,
            'doctor': profile.get('doctor'),
            'assigned_staff_id': profile.get('assigned_staff_id'),
            'analysis': {'status': 'INSUFFICIENT_DATA', 'abstain': True, 'modified_news2': calculate_modified_news2(None, None, None)},
        }
    try:
        result = json.loads(row[0])
        measured = result['timestamp']
        if not isinstance(measured, (int, float)) or isinstance(measured, bool) or not math.isfinite(measured):
            raise ValueError('Invalid timestamp')
        if not isinstance(result.get('analysis'), dict):
            raise ValueError('Invalid analysis')
    except (ValueError, KeyError, TypeError):
        return {
            'patient_id': patient_id,
            'status': 'INVALID_DATA',
            'patient_profile': profile,
            'doctor': profile.get('doctor'),
            'assigned_staff_id': profile.get('assigned_staff_id'),
            'analysis': {'status': 'INVALID_DATA', 'abstain': True, 'modified_news2': calculate_modified_news2(None, None, None)},
        }
    if 'patient_profile' not in result or not isinstance(result.get('patient_profile'), dict):
        result['patient_profile'] = profile
    result.setdefault('doctor', result['patient_profile'].get('doctor') or profile.get('doctor'))
    result.setdefault('assigned_staff_id', result['patient_profile'].get('assigned_staff_id') or profile.get('assigned_staff_id'))
    now = time.time()
    if not -2 <= now - measured <= 15:
        result['status'] = 'STALE_DATA'
        result['analysis'] = {**result.get('analysis', {}), 'status': 'STALE_DATA', 'abstain': True, 'modified_news2': calculate_modified_news2(None, None, None), 'forecast': None, 'summary': 'ข้อมูลเก่าแล้ว ระงับผลวิเคราะห์', 'is_anomaly': False}
        result['is_anomaly'] = False
        result['risk_percent'] = None
    elif result['analysis'].get('status') == 'READY':
        evaluated = result['analysis'].get('evaluated_at')
        fresh = (isinstance(evaluated, (int, float)) and not isinstance(evaluated, bool)
                 and math.isfinite(evaluated) and 0 <= now - evaluated <= 30)
        if not fresh:
            result['analysis'] = {**result['analysis'], 'status': 'STALE_ANALYSIS', 'abstain': True, 'forecast': None, 'summary': 'ผลวิเคราะห์เก่าแล้ว กรุณารอผลใหม่', 'is_anomaly': False}
            result['is_anomaly'] = False
            result['risk_percent'] = None
    return result


class MonitorWorker:
    def __init__(self, database, registry, ingest_mode='replay'):
        self.database = database
        self.registry = registry
        self.mode = ingest_mode
        self.histories = defaultdict(lambda: deque(maxlen=60))
        self.analysis = {}
        self.start = None
        self.last_step = -1
        self.last_inference = {}
        self.records = {}

    def setup(self):
        init_monitor_db(self.database)
        if self.mode == 'replay':
            all_records = load_recordings()
            # Presentation uses held-out recordings; 60 synthetic beds reuse
            # these traces. Neither number is presented as a patient cohort.
            ids = monitor_model.status().get('splits', {}).get('test', [])
            self.records = {key: all_records[key] for key in ids if key in all_records}
            if not self.records:
                raise ValueError('Run download_bidmc and train_bidmc first')

    def process(self, readings, current):
        outputs = []
        accepted = []
        pending = []
        for reading in readings:
            # Quarantine malformed telemetry per sample, not the whole ward batch.
            if not isinstance(reading, dict):
                continue
            timestamp = reading.get('timestamp')
            hr = reading.get('heart_rate')
            spo2 = reading.get('spo2')
            rr = reading.get('respiratory_rate')
            if not (isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool) and math.isfinite(timestamp)):
                continue
            fresh = -2 <= current - timestamp <= 15
            rr_valid = (rr is None) or (
                isinstance(rr, (int, float)) and not isinstance(rr, bool) and math.isfinite(rr) and 0 < rr <= 60
            )
            valid = (
                isinstance(hr, (int, float)) and not isinstance(hr, bool)
                and isinstance(spo2, (int, float)) and not isinstance(spo2, bool)
                and math.isfinite(hr) and math.isfinite(spo2)
                and 30 <= hr <= 240 and 50 <= spo2 <= 100 and rr_valid
            )
            if not (fresh and valid):
                continue
            if not isinstance(reading.get('patient_id'), str):
                continue
            patient_id = reading['patient_id']
            if patient_id not in self.registry:
                continue
            history = self.histories[patient_id]
            if history and reading['timestamp'] <= history[-1]['timestamp']:
                continue
            if history and (abs(reading['timestamp'] - history[-1]['timestamp'] - 1) > .2
                            or reading.get('source_segment') != history[-1].get('source_segment')):
                # Revoke the previous forecast immediately, not at the next
                # ten-second inference tick, when continuity is broken.
                self.analysis[patient_id] = {'status': 'INSUFFICIENT_DATA', 'abstain': True, 'forecast': None, 'is_anomaly': False}
                self.last_inference[patient_id] = 0
            history.append(reading)
            accepted.append(reading)
            if current - self.last_inference.get(patient_id, 0) >= 10:
                pending.append(patient_id)
        if pending:
            results = monitor_model.assess_many([list(self.histories[key]) for key in pending], now=current)
            for patient_id, result in zip(pending, results):
                self.analysis[patient_id] = result
                self.last_inference[patient_id] = current
        with closing(monitor_db_connect(self.database)) as conn, conn:
            for reading in accepted:
                patient_id = reading['patient_id']
                history = self.histories[patient_id]
                hr, spo2 = reading['heart_rate'], reading['spo2']
                rr = reading.get('respiratory_rate')
                news2 = calculate_modified_news2(hr, spo2, rr)
                raw_analysis = self.analysis.get(patient_id, {'status': 'INSUFFICIENT_DATA', 'abstain': True})
                is_ready = raw_analysis.get('status') == 'READY'
                analysis = {
                    **raw_analysis,
                    'abstain': not is_ready,
                    'modified_news2': news2,
                }
                is_anomaly = is_ready and bool(analysis.get('is_anomaly'))
                if (
                    spo2 < 90
                    or hr < 50
                    or hr > 120
                    or news2['level'] == 'HIGH'
                    or (rr is not None and (rr <= 8 or rr >= 25))
                ):
                    level = 'CRITICAL'
                elif (
                    is_anomaly
                    or spo2 < 94
                    or hr < 60
                    or hr > 100
                    or news2['level'] == 'MEDIUM'
                ):
                    level = 'WARNING'
                else:
                    level = 'NORMAL'
                alert = 'ข้อเสนอให้ตรวจสอบค่าสัญญาณชีพ' if level != 'NORMAL' else 'ได้รับข้อมูลการวัดล่าสุดแล้ว'
                if is_anomaly and level == 'WARNING' and not (spo2 < 94 or hr < 60 or hr > 100 or news2['level'] == 'MEDIUM'):
                    alert = 'โมเดลพบรูปแบบต่างจากชุดฝึก โปรดตรวจสอบการวัด'
                source = reading.get('source') or ('BIDMC_REPLAY' if self.mode == 'replay' else 'MQTT')
                output = {**reading, 'status': level, 'alert_message': alert, 'analysis': analysis,
                          'modified_news2': news2,
                          'patient_profile': self.registry[patient_id], 'risk_percent': None,
                          'is_anomaly': is_anomaly,
                          'source': source,
                          'history': list(history)[-20:]}
                if patient_id in pending:
                    conn.execute('INSERT OR IGNORE INTO monitor_analysis_logs VALUES (?,?,?,?)',
                                 (patient_id, current, output['source'], json.dumps(analysis, allow_nan=False)))
                conn.execute('INSERT INTO monitor_results VALUES (?,?,?) ON CONFLICT(patient_id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at',
                             (patient_id, json.dumps(output, allow_nan=False), current))
                # Persist snapshots every five seconds; in-memory ML still gets 1Hz.
                if int(reading['timestamp']) % 5 == 0:
                    conn.execute('INSERT INTO vital_logs (patient_id,heart_rate,spo2,status,timestamp,respiratory_rate,simulation_state,source_record,source_segment) VALUES (?,?,?,?,?,?,?,?,?)',
                                 (patient_id, hr, spo2, level, reading['timestamp'], reading['respiratory_rate'], output['source'], reading.get('source_record'), reading.get('source_segment')))
                outputs.append(output)
            conn.execute('INSERT INTO monitor_components VALUES (?,?,?,NULL) ON CONFLICT(name) DO UPDATE SET heartbeat=excluded.heartbeat,status=excluded.status,error=NULL', (self.mode, current, 'RUNNING'))
            if self.mode != 'test':
                conn.execute('INSERT INTO monitor_worker VALUES (1,?,?,NULL) ON CONFLICT(id) DO UPDATE SET heartbeat=excluded.heartbeat,status=excluded.status,error=NULL', (current, 'RUNNING'))
        return outputs

    def tick(self, current=None):
        current = time.time() if current is None else current
        if self.start is None:
            self.start = int(current)
        step = int(current) - self.start
        if step <= self.last_step:
            return []
        self.last_step = step
        readings = []
        record_ids = list(self.records)
        for index, patient_id in enumerate(self.registry):
            record_id = record_ids[index % len(record_ids)]
            series = self.records[record_id]
            absolute = step + index * 7
            position = absolute % len(series)
            values = series[position, 1:]
            from ml_pipeline.bidmc import valid_values
            if not valid_values(values[None, :]):
                continue
            readings.append({'patient_id': patient_id, 'timestamp': float(self.start + step),
                             **dict(zip(KEYS, values.tolist())), 'source_record': record_id,
                             'source_segment': record_id + ':' + str(absolute // len(series))})
        return self.process(readings, current)

    async def run(self, publish):
        try:
            await asyncio.to_thread(self.setup)
        except Exception as error:
            self.failure(error)
            return
        while True:
            started = time.monotonic()
            try:
                if self.mode == 'replay':
                    outputs = await asyncio.to_thread(self.tick)
                    await publish(outputs)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.failure(error)
            await asyncio.sleep(max(.05, 1 - (time.monotonic() - started)))

    def failure(self, error):
        log.error('Monitor worker failed: %s', type(error).__name__)
        with closing(monitor_db_connect(self.database)) as conn, conn:
            conn.execute('INSERT INTO monitor_components VALUES (?,?,?,?) ON CONFLICT(name) DO UPDATE SET heartbeat=excluded.heartbeat,status=excluded.status,error=excluded.error',
                         (self.mode, time.time(), 'ERROR', type(error).__name__))
            if self.mode != 'test':
                conn.execute('INSERT INTO monitor_worker VALUES (1,?,?,?) ON CONFLICT(id) DO UPDATE SET heartbeat=excluded.heartbeat,status=excluded.status,error=excluded.error',
                             (time.time(), 'ERROR', type(error).__name__))


def worker_status(database):
    with closing(monitor_db_connect(database)) as conn:
        row = conn.execute('SELECT heartbeat,status,error FROM monitor_worker WHERE id=1').fetchone()
        count = conn.execute("SELECT COUNT(*) FROM monitor_results WHERE updated_at>? AND patient_id NOT LIKE 'TEST_%'", (time.time() - 15,)).fetchone()[0]
        components = {name: {'heartbeat': heartbeat, 'status': status if time.time() - heartbeat < 15 else 'STOPPED', 'error': error}
                      for name, heartbeat, status, error in conn.execute('SELECT * FROM monitor_components')}
    return {'status': row[1] if row and time.time() - row[0] < 15 else 'STOPPED',
            'heartbeat': row[0] if row else None, 'error': row[2] if row else None,
            'fresh_beds': count, 'model': monitor_model.status(), 'components': components}
