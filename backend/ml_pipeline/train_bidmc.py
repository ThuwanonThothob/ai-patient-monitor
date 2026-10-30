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
    anomaly = IsolationForest(n_estimators=160, contamination=.05, random_state=42, n_jobs=2).fit(x[train_i])
    splits = {name: sorted(set(groups[index].tolist())) for name, index in [('train', train_i), ('validation', val_i), ('test', test)]}
    metric = lambda predicted: dict(zip(KEYS, np.round(mean_absolute_error(y[test], predicted, multioutput='raw_values'), 4).tolist()))
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
        'test_rf_mae': metric(rf_test), 'test_persistence_mae': metric(last[test]),
        'test_selected_mae': metric(selected_test),
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
