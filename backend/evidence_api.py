"""Read-only, causal BIDMC demonstration. Never creates clinical alerts.

Predictions are frozen at anchor; observations beyond the viewer's cursor are
not returned. Test records are selectable without cherry-picking outcomes.
"""
from functools import lru_cache
import hashlib
import json
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from ai_models import monitor_model
from ml_pipeline.bidmc import DATA, KEYS, WINDOW, HORIZON, features, load_recordings, valid_values

router = APIRouter(prefix='/api/evidence', tags=['AI-evidence-replay'])


@lru_cache(maxsize=1)
def dataset():
    model = monitor_model.bundle()
    metadata = model['metadata']
    if hashlib.sha256((DATA / 'manifest.json').read_bytes()).hexdigest() != metadata['data_manifest_sha256']:
        raise ValueError('Dataset manifest differs from training')
    records = load_recordings()  # verifies publisher checksums
    test = metadata['splits']['test']
    if set(test) & (set(metadata['splits']['train']) | set(metadata['splits']['validation'])):
        raise ValueError('Overlapping splits')
    return {key: records[key] for key in test}, metadata, hashlib.sha256(monitor_model.MODEL.read_bytes()).hexdigest()


def point(row):
    return {'second': float(row[0]), **{key: float(value) if np.isfinite(value) else None for key, value in zip(KEYS, row[1:])}}


def replay(rows, record_id, anchor, observed_until):
    if not 0 <= anchor <= observed_until < len(rows) or observed_until > anchor + HORIZON:
        raise HTTPException(422, 'Cursor must be between anchor and anchor + 30, inside the record')
    history = rows[max(0, anchor - WINDOW + 1):anchor + 1]
    readings = [{'timestamp': float(row[0]), 'source_segment': record_id,
                 **dict(zip(KEYS, row[1:].tolist()))} for row in history]
    analysis = monitor_model.assess(readings, now=float(rows[anchor, 0]))
    target = anchor + HORIZON
    result = {
        'record_id': record_id, 'anchor': anchor, 'observed_until': observed_until,
        'anchor_second': float(rows[anchor, 0]), 'target_second': float(rows[anchor, 0] + HORIZON),
        'analysis': analysis, 'input': [point(row) for row in history],
        'observed_after': [point(row) for row in rows[anchor + 1:observed_until + 1]],
        'baseline': point(rows[anchor]), 'comparison': None, 'feature_evidence': [],
        'evaluation_status': 'WAITING_FOR_TARGET', 'research_only': True,
        'notice': 'ข้อมูลย้อนหลัง ไม่ใช่ผู้ป่วยในทะเบียน ไม่สร้าง alert หรือส่ง Push; anomaly ไม่มี label โรค',
    }
    if analysis['status'] != 'READY':
        result['evaluation_status'] = 'ABSTAIN'
        return result
    vector = features(history[:, 1:]).reshape(7, 3)
    for key, values in zip(('last', 'mean', 'std', 'min', 'max', 'change', 'slope_per_second'), vector):
        result['feature_evidence'].append({'statistic': key, **dict(zip(KEYS, values.tolist()))})
    if target >= len(rows):
        result['evaluation_status'] = 'TARGET_OUTSIDE_RECORD'
    elif observed_until >= target:
        block = rows[anchor:target + 1]
        if not valid_values(block[:, 1:]) or not np.allclose(np.diff(block[:, 0]), 1, atol=.2):
            result['evaluation_status'] = 'TARGET_WINDOW_INVALID'
        else:
            result['evaluation_status'] = 'EVALUATED'
            result['comparison'] = {key: {
                'actual': float(rows[target, index + 1]), 'selected': analysis['forecast'][key],
                'baseline': float(rows[anchor, index + 1]),
                'selected_absolute_error': abs(analysis['forecast'][key] - float(rows[target, index + 1])),
                'baseline_absolute_error': abs(float(rows[anchor, index + 1] - rows[target, index + 1])),
            } for index, key in enumerate(KEYS)}
    return result


def available():
    try:
        return dataset()
    except (OSError, ValueError, KeyError) as error:
        raise HTTPException(503, 'BIDMC evidence unavailable; verify downloaded data and trained model') from error


@router.get('/status')
def status():
    records, metadata, digest = available()
    return {'records': [{'id': key, 'samples': len(rows)} for key, rows in records.items()],
            'metadata': metadata, 'model_sha256': digest, 'live_alerts_enabled': False}


@router.get('/records/{record_id}')
def record(record_id: str, anchor: int = Query(59, ge=0), observed_until: int = Query(59, ge=0)):
    records, metadata, digest = available()
    if record_id not in records:
        raise HTTPException(404, 'Only held-out BIDMC recording IDs are accepted')
    return {**replay(records[record_id], record_id, anchor, observed_until), 'model_sha256': digest,
            'trained_at': metadata['trained_at'], 'methods': metadata['selected_forecast']}


@router.get('/records/{record_id}/report', response_class=PlainTextResponse)
def report(record_id: str, anchor: int = Query(59, ge=0), observed_until: int = Query(59, ge=0)):
    evidence = record(record_id, anchor, observed_until)
    return PlainTextResponse('Smart Ward — AI evidence (research only)\n'
        'Features describe inputs, not causal explanations. One case is not model accuracy.\n'
        + json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False),
        headers={'Content-Disposition': f'attachment; filename="evidence-{record_id}.txt"'})
