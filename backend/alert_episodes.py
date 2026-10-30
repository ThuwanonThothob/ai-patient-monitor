"""One open work item per patient and signal; original alerts remain auditable."""
from contextlib import closing
import sqlite3
import time
import json

OPEN = "('NEW','ACKNOWLEDGED','ESCALATED')"


def kind(reason):
    if 'SpO2' in reason:
        return 'spo2_low'
    if 'Heart rate' in reason or 'ชีพจร' in reason:
        return 'heart_rate'
    return 'model_review'


def init(database):
    with closing(sqlite3.connect(database, timeout=15)) as conn, conn:
        conn.row_factory = sqlite3.Row
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('DROP INDEX IF EXISTS idx_open_episode')
        columns = {r[1] for r in conn.execute('PRAGMA table_info(agent_alerts)')}
        for name, definition in [('episode_key', 'TEXT'), ('merged_into', 'INTEGER'),
                                 ('last_seen_at', 'REAL'), ('occurrences', 'INTEGER NOT NULL DEFAULT 1'),
                                 ('recovered_at', 'REAL'), ('version', 'INTEGER NOT NULL DEFAULT 1')]:
            if name not in columns:
                conn.execute(f'ALTER TABLE agent_alerts ADD COLUMN {name} {definition}')
        for row in conn.execute('SELECT id,reason,created_at FROM agent_alerts WHERE episode_key IS NULL').fetchall():
            conn.execute('UPDATE agent_alerts SET episode_key=?,last_seen_at=? WHERE id=?', (kind(row[1]), row[2], row[0]))
        # Link legacy duplicates, never delete or claim human resolution. Prefer
        # the most progressed human workflow as representative of the group.
        groups = conn.execute(f'''SELECT patient_id,episode_key FROM agent_alerts
            WHERE status IN {OPEN} AND merged_into IS NULL GROUP BY patient_id,episode_key HAVING COUNT(*)>1''').fetchall()
        for patient, key in groups:
            originals = [dict(r) for r in conn.execute(f"SELECT * FROM agent_alerts WHERE patient_id=? AND episode_key=? AND status IN {OPEN} AND merged_into IS NULL", (patient, key)).fetchall()]
            rows = conn.execute(f'''SELECT id,created_at,last_seen_at,occurrences,severity FROM agent_alerts
                WHERE patient_id=? AND episode_key=? AND status IN {OPEN} AND merged_into IS NULL
                ORDER BY CASE status WHEN 'ESCALATED' THEN 0 WHEN 'ACKNOWLEDGED' THEN 1 ELSE 2 END,created_at,id''', (patient, key)).fetchall()
            root = rows[0][0]
            conn.executemany('UPDATE agent_alerts SET merged_into=? WHERE id=?', [(root, row[0]) for row in rows[1:]])
            conn.execute('UPDATE agent_alerts SET created_at=?,last_seen_at=?,occurrences=?,severity=? WHERE id=?',
                         (min(r[1] for r in rows), max(r[2] for r in rows), sum(r[3] for r in rows),
                          'critical' if any(r[4] == 'critical' for r in rows) else 'warning', root))
            latest = max(originals, key=lambda r: r['last_seen_at'])
            conn.execute('UPDATE agent_alerts SET heart_rate=?,spo2=?,reason=? WHERE id=?', (latest['heart_rate'], latest['spo2'], latest['reason'], root))
            conn.execute('''INSERT INTO agent_audit_logs(alert_id,patient_id,action,actor,detail,created_at)
                VALUES (?,?,'EPISODES_GROUPED','system',?,?)''',
                         (root, patient, json.dumps({'grouped': len(rows), 'original_alerts': originals}, ensure_ascii=False), time.time()))
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='push_outbox'").fetchone():
            conn.execute("""UPDATE push_outbox SET state='CANCELLED',updated_at=? WHERE state IN ('QUEUED','RETRY')
                AND alert_id IN (SELECT id FROM agent_alerts WHERE merged_into IS NOT NULL)""", (time.time(),))
        conn.execute(f'''CREATE UNIQUE INDEX IF NOT EXISTS idx_open_episode
            ON agent_alerts(patient_id,episode_key) WHERE merged_into IS NULL AND status IN {OPEN}''')


def observe(conn, event, model_fresh):
    """Refresh existing episodes only from validated, fresh observations."""
    # Minimal stand-alone Agent test databases may not have episode migration.
    if 'episode_key' not in {r[1] for r in conn.execute('PRAGMA table_info(agent_alerts)')}:
        return
    states = {'spo2_low': event.spo2 < 90, 'heart_rate': event.heart_rate < 50 or event.heart_rate > 120,
              'model_review': bool(event.is_anomaly or event.model_requests_review or
                                   (event.risk_percent is not None and event.risk_percent >= 70)) if model_fresh else None}
    for key, abnormal in states.items():
        if abnormal is None:
            continue
        if abnormal:
            conn.execute(f'''UPDATE agent_alerts SET last_seen_at=?,heart_rate=?,spo2=?,
                occurrences=occurrences+1,recovered_at=NULL WHERE patient_id=? AND episode_key=?
                AND merged_into IS NULL AND status IN {OPEN} AND COALESCE(last_seen_at,0)<?''',
                         (event.timestamp, event.heart_rate, event.spo2, event.patient_id, key, event.timestamp))
        else:
            conn.execute(f'''UPDATE agent_alerts SET recovered_at=? WHERE patient_id=? AND episode_key=?
                AND merged_into IS NULL AND status IN {OPEN} AND recovered_at IS NULL AND last_seen_at<?''',
                         (event.timestamp, event.patient_id, key, event.timestamp))


def metadata(conn, alert_id):
    row = conn.execute('SELECT episode_key,merged_into,last_seen_at,occurrences,recovered_at,version FROM agent_alerts WHERE id=?', (alert_id,)).fetchone()
    return dict(zip(('episode_key', 'merged_into', 'last_seen_at', 'occurrences', 'recovered_at', 'version'), row)) if row else {}
