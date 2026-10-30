"""Frozen research protocol for PMD standard-posture classification.

No runtime training, no camera adapter, no pressure-injury prediction. Subjects
are separated before fitting; only validation selects the classifier.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import joblib
import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from ml_pipeline.download_pmd import DATA

OUTPUT = Path(__file__).resolve().parents[1] / 'models/posture'
CLASSES = ['left', 'right', 'supine']


def pressure_features(frame):
    frame = np.asarray(frame, dtype=float)
    # Files contain raw sensor counts exceeding the nominal range in the paper.
    # Do not discard/clamp those recordings or reinterpret counts as mmHg.
    if frame.shape != (32, 64) or not np.isfinite(frame).all() or (frame < 0).any() or not np.isfinite(frame.sum()) or frame.sum() <= 0:
        raise ValueError('Expected a valid non-empty 32x64 PMD pressure map')
    # Fixed spatial averaging and sum normalization, with no learned test statistics.
    pooled = frame.reshape(8, 4, 16, 4).mean(axis=(1, 3))
    return (pooled / pooled.sum()).ravel()


def subject_splits():
    subjects = np.random.default_rng(20261003).permutation(np.arange(1, 14)).tolist()
    return {'train': sorted(subjects[:7]), 'validation': sorted(subjects[7:10]), 'test': sorted(subjects[10:])}


def load_data():
    manifest = json.loads((DATA / 'manifest.json').read_text())
    expected = {f'experiment-i/S{subject}/{pose}.txt' for subject in range(1, 14) for pose in (1, 2, 3)}
    expected.update({'experiment-info.docx', 'experiment-i/subject-info-i.csv'})
    if set(manifest['sha256']) != expected:
        raise ValueError('Expected exactly 39 recordings and the two provenance documents')
    x, y, groups, entries, maps = [], [], [], [], []
    excluded = 0
    for name, checksum in sorted(manifest['sha256'].items()):
        content = (DATA / name).read_bytes()
        if hashlib.sha256(content).hexdigest() != checksum:
            raise ValueError('PMD checksum mismatch: ' + name)
        match = re.fullmatch(r'experiment-i/S(\d+)/(1|2|3)\.txt', name)
        if not match:
            continue
        subject, posture = map(int, match.groups())
        rows = np.loadtxt(DATA / name, ndmin=2)
        if rows.shape[1] != 2048:
            raise ValueError('Unexpected PMD column count: ' + name)
        for index in range(0, len(rows), 5):
            frame = rows[index].reshape(32, 64)
            try:
                vector = pressure_features(frame)
            except ValueError:
                excluded += 1
                continue
            x.append(vector); y.append({1: 'supine', 2: 'right', 3: 'left'}[posture]); groups.append(subject)
            entries.append({'id': f'S{subject}-P{posture}-F{index}', 'subject': subject, 'position': posture,
                            'frame': index, 'source_file': name})
            maps.append(frame)
    if set(groups) != set(range(1, 14)):
        raise ValueError('All 13 declared subjects are required')
    return np.asarray(x), np.asarray(y), np.asarray(groups), entries, maps, manifest, excluded


def evaluate(y, predicted, groups):
    return {'accuracy': float(accuracy_score(y, predicted)), 'macro_f1': float(f1_score(y, predicted, labels=CLASSES, average='macro', zero_division=0)),
            'per_class': classification_report(y, predicted, labels=CLASSES, output_dict=True, zero_division=0),
            'confusion_matrix': confusion_matrix(y, predicted, labels=CLASSES).tolist(), 'samples': len(y),
            'per_subject_accuracy': {f'S{subject}': float(accuracy_score(y[groups == subject], predicted[groups == subject])) for subject in sorted(set(groups.tolist()))}}


def train():
    x, y, groups, entries, maps, manifest, excluded = load_data()
    splits = subject_splits()
    masks = {name: np.isin(groups, subjects) for name, subjects in splits.items()}
    models = {'logistic': make_pipeline(StandardScaler(), LogisticRegression(C=1, max_iter=2000, class_weight='balanced')),
              'random_forest': RandomForestClassifier(n_estimators=120, min_samples_leaf=3, max_depth=12,
                                                      class_weight='balanced', random_state=42, n_jobs=2),
              'majority': DummyClassifier(strategy='most_frequent')}
    metrics = {}
    for name, model in models.items():
        model.fit(x[masks['train']], y[masks['train']])
        metrics[name] = {split: evaluate(y[mask], model.predict(x[mask]), groups[mask]) for split, mask in masks.items() if split != 'train'}
    selected = max(('logistic', 'random_forest'), key=lambda name: metrics[name]['validation']['macro_f1'])
    probabilities = models[selected].predict_proba(x[masks['test']])
    predictions = models[selected].predict(x[masks['test']])
    accepted = probabilities.max(axis=1) >= .6  # fixed research cutoff, not clinical confidence
    report = {'schema_version': 1, 'dataset': manifest['dataset'], 'source': manifest['source'], 'license': manifest['license'],
              'citation': manifest['citation'], 'subset': manifest['subset'], 'classes': CLASSES, 'splits': splits,
              'split_counts': {name: int(mask.sum()) for name, mask in masks.items()}, 'excluded_frames': excluded,
              'selected_model': selected, 'metrics': metrics, 'confidence_cutoff': .6,
              'coverage': float(accepted.mean()), 'accepted_accuracy': float(accuracy_score(y[masks['test']][accepted], predictions[accepted])) if accepted.any() else None,
              'live_enabled': False, 'trained_at': datetime.now(timezone.utc).isoformat(),
              'data_manifest_sha256': hashlib.sha256((DATA / 'manifest.json').read_bytes()).hexdigest(),
              'protocol': 'Subjects 7/3/3 split with seed 20261003; every fifth frame; fixed 8x16 mean pooling/sum normalization; validation macro-F1 selects logistic/RF; no test tuning.',
              'protocol_revision': 'Importer v2 accepts finite nonnegative raw counts, including >1000 seen in training subject S1; no clipping. Initial v1 result was inspected before this correction; this is exploratory, not a pristine final validation.',
              'limitations': ['Only standard positions 1–3, not all 17 positions; no bed-exit/empty-bed class.',
                              '13 adults aged 19–34, not an elderly/bedbound clinical cohort; test contains only 3 people.',
                              'Frames from a recording are correlated, not independent patients.',
                              'Model probability is uncalibrated. No pressure-injury labels or treatment recommendations.',
                              'Recorded poses are separate experiments, not a continuous real care timeline.'], 'cases': []}
    run = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + os.urandom(4).hex()
    folder = OUTPUT / run
    folder.mkdir(parents=True)
    joblib.dump({'models': models, 'selected': selected, 'splits': splits}, folder / 'models.joblib')
    test_indices = np.flatnonzero(masks['test'])
    (folder / 'cases').mkdir()
    for position, index in enumerate(test_indices):
        entry = entries[index]
        prediction = str(predictions[position])
        case = {**entry, 'label': str(y[index]), 'prediction': prediction,
                'decision': prediction if accepted[position] else 'ABSTAIN',
                'probabilities': dict(zip(models[selected].classes_.tolist(), probabilities[position].tolist())),
                'pressure_map': maps[index].tolist(), 'features': x[index].reshape(8, 16).tolist(),
                'baseline': str(models['majority'].predict(x[index:index + 1])[0])}
        content = json.dumps(case, allow_nan=False).encode()
        (folder / 'cases' / (entry['id'] + '.json')).write_bytes(content)
        report['cases'].append({**entry, 'correct': prediction == y[index], 'abstained': not bool(accepted[position]), 'sha256': hashlib.sha256(content).hexdigest()})
    report['run_id'] = run
    report['model_sha256'] = hashlib.sha256((folder / 'models.joblib').read_bytes()).hexdigest()
    content = json.dumps(report, indent=2, allow_nan=False).encode()
    (folder / 'report.json').write_bytes(content)
    temporary = OUTPUT / 'current.json.part'
    temporary.write_text(json.dumps({'run_id': run, 'report_sha256': hashlib.sha256(content).hexdigest()}))
    os.replace(temporary, OUTPUT / 'current.json')
    print(json.dumps({k: v for k, v in report.items() if k != 'cases'}, indent=2), flush=True)


if __name__ == '__main__':
    train()
