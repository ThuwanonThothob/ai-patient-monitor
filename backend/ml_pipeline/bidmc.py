"""Shared training/inference contract: 60 one-second samples → +30 seconds.

Only HR (bpm), SpO2 (%) and respiratory rate (/min) are used. No glucose,
diagnosis, age or labels are invented. Anomaly scores have no disease labels.
"""
import csv
import hashlib
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/raw/bidmc'
KEYS = ('heart_rate', 'spo2', 'respiratory_rate')
WINDOW = 60
HORIZON = 30


def load_recordings():
    manifest = json.loads((DATA / 'manifest.json').read_text())
    records = {}
    for name, digest in sorted(manifest['sha256'].items()):
        path = DATA / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('BIDMC checksum mismatch: ' + name)
        with path.open() as handle:
            reader = csv.DictReader(handle, skipinitialspace=True)
            rows = [[float(row[key]) for key in ('Time [s]', 'HR', 'SpO2', 'RESP')] for row in reader]
        records[name.removesuffix('_Numerics.csv')] = np.asarray(rows)
    return records


def valid_values(values):
    return (np.isfinite(values).all() and (values > 0).all()
            and (values[:, 0] >= 20).all() and (values[:, 0] <= 250).all()
            and (values[:, 1] >= 50).all() and (values[:, 1] <= 100).all()
            and (values[:, 2] <= 80).all()
            and (len(values) < 2 or (np.abs(np.diff(values[:, 0])) <= 50).all()))


def features(values):
    if values.shape != (WINDOW, 3) or not valid_values(values):
        raise ValueError('60 complete, valid readings required')
    time = np.arange(WINDOW, dtype=float)
    slope = ((time - time.mean())[:, None] * values).sum(axis=0) / ((time - time.mean()) ** 2).sum()
    return np.concatenate([values[-1], values.mean(axis=0), values.std(axis=0),
                           values.min(axis=0), values.max(axis=0),
                           values[-1] - values[0], slope])


def examples(recordings):
    x, y, last, groups = [], [], [], []
    for record_id, rows in recordings.items():
        for end in range(WINDOW - 1, len(rows) - HORIZON, 5):
            block = rows[end - WINDOW + 1:end + HORIZON + 1]
            if not np.allclose(np.diff(block[:, 0]), 1) or not valid_values(block[:, 1:]):
                continue
            history = block[:WINDOW, 1:]
            x.append(features(history))
            y.append(block[-1, 1:])
            last.append(history[-1])
            groups.append(record_id)
    return np.asarray(x), np.asarray(y), np.asarray(last), np.asarray(groups)
