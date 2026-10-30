"""Local model inference; exact same window/features as offline training."""
from pathlib import Path
from functools import lru_cache
import time
import joblib
import numpy as np
from ml_pipeline.bidmc import ROOT, KEYS, WINDOW, HORIZON, features

MODEL = ROOT / 'models/bidmc_monitor_v1.joblib'


@lru_cache(maxsize=1)
def bundle():
    # Only trusted local training output; never accept a user-supplied pickle.
    model = joblib.load(MODEL)
    # Small online batches do not benefit from per-estimator thread dispatch.
    model['regressor'].n_jobs = 1
    model['anomaly'].n_jobs = 1
    return model


def status():
    if not MODEL.exists():
        return {'status': 'MODEL_NOT_TRAINED', 'available': False}
    return {'status': 'READY', 'available': True, **bundle()['metadata']}


def prepare(history, now=None):
    result = {'status': 'INSUFFICIENT_DATA', 'forecast': None, 'is_anomaly': False,
              'horizon_seconds': HORIZON, 'model_version': 'bidmc-monitor-v1',
              'research_only': True, 'history_points': len(history)}
    if not MODEL.exists():
        return {**result, 'status': 'MODEL_NOT_TRAINED'}
    if len(history) < WINDOW:
        return result
    window = history[-WINDOW:]
    times = np.asarray([row['timestamp'] for row in window])
    current = time.time() if now is None else now
    if current - times[-1] > 15 or times[-1] > current + 5:
        return {**result, 'status': 'STALE_DATA'}
    if not np.allclose(np.diff(times), 1, atol=.2):
        return {**result, 'status': 'SAMPLING_MISMATCH'}
    if len({row.get('source_segment') for row in window}) != 1:
        return {**result, 'status': 'INSUFFICIENT_DATA'}
    try:
        values = np.asarray([[row.get(key, np.nan) for key in KEYS] for row in window], dtype=float)
        vector = features(values)[None, :]
    except (ValueError, TypeError):
        return {**result, 'status': 'INVALID_DATA'}
    return {**result, 'status': 'READY', '_vector': vector[0], '_last': values[-1],
            'prediction_at': float(times[-1] + HORIZON), 'evaluated_at': current}


def assess_many(histories, now=None):
    results = [prepare(history, now) for history in histories]
    ready = [result for result in results if result['status'] == 'READY']
    if ready:
        model = bundle()
        vectors = np.asarray([result.pop('_vector') for result in ready])
        last = np.asarray([result.pop('_last') for result in ready])
        predicted = np.where(model['use_rf'], last + model['regressor'].predict(vectors), last)
        scores = model['anomaly'].decision_function(vectors)
        for result, forecast, score in zip(ready, predicted, scores):
            unusual = bool(score < 0)
            result.update(is_anomaly=unusual, anomaly_score=round(float(score), 4),
                          forecast=dict(zip(KEYS, np.round(forecast, 2).tolist())),
                          forecast_methods=model['metadata']['selected_forecast'],
                          summary=('พบรูปแบบต่างจากชุดฝึก ควรให้เจ้าหน้าที่ตรวจสอบการวัด' if unusual else 'วิเคราะห์ข้อมูลล่าสุดแล้ว ยังไม่พบรูปแบบต่างจากชุดฝึก'))
    return results


def assess(history, now=None):
    return assess_many([history], now)[0]
