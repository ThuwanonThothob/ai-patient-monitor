"""Recording-disjoint forecasting comparison and unsupervised anomaly training."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import joblib
import numpy as np
import sklearn
from sklearn.ensemble import RandomForestRegressor, IsolationForest
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import GroupShuffleSplit
from ml_pipeline.bidmc import DATA, ROOT, KEYS, WINDOW, HORIZON, examples, load_recordings
from ai_models.anomaly import evaluate_forecast_error_bounds


def train(output_dir=None):
    records = load_recordings()
    x, y, last, groups = examples(records)
    development, test = next(GroupShuffleSplit(n_splits=1, test_size=.2, random_state=42).split(x, y, groups))
    train_i, val_i = next(GroupShuffleSplit(n_splits=1, test_size=.25, random_state=43).split(x[development], y[development], groups[development]))
    train_i, val_i = development[train_i], development[val_i]
    # Predict change from last value, so predictions remain near measured values
    # for patients with unseen baseline HR/SpO2/RR.
    regressor = RandomForestRegressor(n_estimators=160, min_samples_leaf=15, max_depth=10, random_state=42, n_jobs=2)
    regressor.fit(x[train_i], y[train_i] - last[train_i])
    val_rf = last[val_i] + regressor.predict(x[val_i])
    val_mae = mean_absolute_error(y[val_i], val_rf, multioutput='raw_values')
    baseline_mae = mean_absolute_error(y[val_i], last[val_i], multioutput='raw_values')
    use_rf = val_mae < baseline_mae
    rf_test = last[test] + regressor.predict(x[test])
    selected_test = np.where(use_rf, rf_test, last[test])

    # 60-second Moving-Average Baseline (feature columns 3:6 are values.mean(axis=0))
    ma_val = x[val_i, 3:6]
    val_ma_mae = mean_absolute_error(y[val_i], ma_val, multioutput='raw_values')
    ma_test = x[test, 3:6]

    anomaly = IsolationForest(n_estimators=160, contamination=.05, random_state=42, n_jobs=2).fit(x[train_i])
    splits = {name: sorted(set(groups[index].tolist())) for name, index in [('train', train_i), ('validation', val_i), ('test', test)]}
    metric = lambda predicted: dict(zip(KEYS, np.round(mean_absolute_error(y[test], predicted, multioutput='raw_values'), 4).tolist()))

    # Stratified Forecast Error Bounds (MAE, RMSE, P95, Exceedance Rate)
    clinical_tolerances = {'heart_rate': 5.0, 'spo2': 2.0, 'respiratory_rate': 3.0}
    pred_map = {
        'random_forest': rf_test,
        'persistence_baseline': last[test],
        'moving_average_baseline': ma_test,
        'selected_forecast': selected_test,
    }
    test_error_bounds = {}
    for pred_name, preds in pred_map.items():
        test_error_bounds[pred_name] = {}
        for idx, key in enumerate(KEYS):
            bounds = evaluate_forecast_error_bounds(y[test, idx], preds[:, idx], clinical_tolerance=clinical_tolerances[key])
            if not bounds.get('abstain'):
                test_error_bounds[pred_name][key] = {
                    'mae': round(float(bounds['mae']), 4),
                    'rmse': round(float(bounds['rmse']), 4),
                    'p95_abs_error': round(float(bounds['p95_abs_error']), 4),
                    'exceed_tolerance_rate': round(float(bounds['exceed_tolerance_rate']), 4),
                    'clinical_tolerance': float(bounds['clinical_tolerance']),
                    'sample_count': int(bounds['sample_count']),
                }

    # Held-Out Alert & Anomaly Burden
    test_hours = round((len(test) * 5.0) / 3600.0, 4)
    anomaly_scores = anomaly.decision_function(x[test])
    anomaly_flags = (anomaly_scores < 0).astype(bool)
    anomaly_windows = int(np.sum(anomaly_flags))
    anomaly_window_rate = round(float(np.mean(anomaly_flags)), 4)

    test_groups = groups[test]
    anomaly_episodes_count = 0
    for record_id in set(test_groups):
        rec_indices = np.where(test_groups == record_id)[0]
        rec_flags = anomaly_flags[rec_indices]
        in_episode = False
        cooldown = 0
        for flag in rec_flags:
            if flag:
                if not in_episode and cooldown == 0:
                    anomaly_episodes_count += 1
                    in_episode = True
                cooldown = 12 # 60s cooldown (12 x 5s steps)
            else:
                if cooldown > 0:
                    cooldown -= 1
                else:
                    in_episode = False

    anomaly_episodes_per_patient_hour = round(float(anomaly_episodes_count / max(test_hours, 1e-6)), 2)

    test_alert_burden = {
        'test_recordings_count': len(splits['test']),
        'test_windows': int(len(test)),
        'evaluated_patient_hours': test_hours,
        'anomaly_flagged_windows': anomaly_windows,
        'anomaly_window_rate': anomaly_window_rate,
        'anomaly_episodes_count': anomaly_episodes_count,
        'anomaly_episodes_per_patient_hour': anomaly_episodes_per_patient_hour,
        'limitation_note': 'IsolationForest is trained unsupervised across population recordings (contamination=0.05) without disease ground-truth labels; clinician-approved per-patient baselines (care_profiles) must be used to contextualize individual alerts.',
    }

    metadata = {
        'model_version': 'bidmc-monitor-v1', 'dataset': 'BIDMC PPG and Respiration Dataset v1.0.0',
        'source': 'https://physionet.org/content/bidmc/1.0.0/',
        'license': 'Open Data Commons Attribution License v1.0',
        'trained_at': datetime.now(timezone.utc).isoformat(), 'sklearn_version': sklearn.__version__,
        'recordings': len(records), 'usable_windows': len(x), 'splits': splits,
        'split_note': 'Recording-disjoint split; subject identities unavailable in numeric files. No external validation.',
        'window_seconds': WINDOW, 'horizon_seconds': HORIZON, 'feature_count': x.shape[1],
        'models': ['RandomForestRegressor (future vital change)', 'IsolationForest (unlabelled unusual patterns)'],
        'selected_forecast': {key: 'RandomForestRegressor' if use else 'persistence baseline' for key, use in zip(KEYS, use_rf)},
        'validation_rf_mae': dict(zip(KEYS, val_mae.tolist())),
        'validation_persistence_mae': dict(zip(KEYS, baseline_mae.tolist())),
        'validation_moving_average_mae': dict(zip(KEYS, val_ma_mae.tolist())),
        'test_rf_mae': metric(rf_test), 'test_persistence_mae': metric(last[test]),
        'test_moving_average_mae': metric(ma_test),
        'test_selected_mae': metric(selected_test),
        'test_error_bounds': test_error_bounds,
        'test_alert_burden': test_alert_burden,
        'test_windows': len(test), 'anomaly_accuracy': None,
        'note': 'MAE uses bpm, percentage points and breaths/min. Anomaly has no ground-truth labels; no claimed disease accuracy. Research demonstration only.',
        'data_manifest_sha256': hashlib.sha256((DATA / 'manifest.json').read_bytes()).hexdigest(),
    }
    output = Path(output_dir or ROOT / 'models')
    output.mkdir(parents=True, exist_ok=True)
    joblib.dump({'regressor': regressor, 'anomaly': anomaly, 'use_rf': use_rf, 'metadata': metadata}, output / 'bidmc_monitor_v1.joblib')
    (output / 'bidmc_monitor_v1_metadata.json').write_text(json.dumps(metadata, indent=2))
    print(json.dumps(metadata, indent=2))
    return metadata


if __name__ == '__main__':
    train()
