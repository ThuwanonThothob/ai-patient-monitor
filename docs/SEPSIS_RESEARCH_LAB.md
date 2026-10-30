# AI Research Lab — PhysioNet 2019

## What is implemented

- Download an outcome-blind, deterministic subset of **4,000 real ICU records** (2,000/site) from the official public data server. This is **not all 40,336 records**.
- Train **Logistic Regression** and **HistGradientBoostingClassifier** locally; compare both with an explicitly unvalidated example threshold rule.
- Staff-only **AI Research Lab** navigation: internal/external metrics, all held-out case categories, hourly replay, optional retrospective ground truth, input provenance and text review drafts.
- Download benchmark evidence as text. Existing patient Text handoff now uses current monitor evidence and timestamps, not simulated profile values as clinical findings. Existing Word export is unchanged.
- No Gemini call, external contact, live sepsis score, new background training, or patient-portal access to research cases. The existing BIDMC worker/WebSocket flow remains independent.

## Reproduce

From the project root, with the existing `.venv` activated:

```bash
cd /Users/thuwanon/ai-patient-monitor/backend
python -m ml_pipeline.download_sepsis2019 --per-site 2000
python -m ml_pipeline.train_sepsis2019
```

Then start the application as usual:

```bash
cd /Users/thuwanon/ai-patient-monitor
python scripts/run_ward.py
```

Open http://localhost:3000, log in as staff, then choose **AI Research Lab**.
The patient portal remains on port 3001. Training is offline and is not required on every startup.
The raw data and trained artifacts already exist locally after this implementation.

`--per-site 0` downloads the entire public cohort, but do **not** reuse the already inspected test cases to claim a new untouched test result after modifying the model/protocol. Freeze an additional independent evaluation cohort first.

## Source, access and integrity

- Dataset: [Early Prediction of Sepsis from Clinical Data, PhysioNet/CinC Challenge 2019 v1.0.0](https://physionet.org/content/challenge-2019/1.0.0/).
- Attribution: Reyna MA et al., *Early Prediction of Sepsis From Clinical Data: The PhysioNet/Computing in Cardiology Challenge*, Critical Care Medicine 48(2), 210–217; [DOI](https://doi.org/10.1097/CCM.0000000000004145).
- Download from the publisher's `training/training_setA/` and `training/training_setB/` directories. Old archive/ZIP links were not usable during implementation; no third-party mirror is substituted.
- **License discrepancy, checked 2026-09-29:** the source page lists CC BY 4.0, while its downloadable `LICENSE.txt` says ODC Open Database License (ODbL). Retain the actual license and citation. Clarify with the publisher before redistributing data/derived databases; do not assume this is resolved.
- Files remain local and ignored by Git. SHA256 in `manifest.json` is a **locally recorded download hash**, not an independently verified publisher checksum. Training verifies it to detect local changes.
- Select filenames by SHA256(seed:site:filename), seed 2019, **before reading outcomes**. A failed/incomplete download does not publish a new manifest.

## Frozen first protocol

1. One file represents one dataset patient record. Split site A by patient file into 70% train, 15% validation, 15% test; stratify by ever-positive label. Site B is a held-out cross-site evaluation, not used for fitting, model choice, or thresholds. No calendar-time validation is claimed.
2. The supplied `SepsisLabel` already starts six hours before the dataset-defined onset. **Do not shift it again.** Inferred onset = first positive label hour + 6.
3. Exclude 40 first-row-positive records because onset is left-censored, and 1 record whose inferred onset lies beyond observation. Report these exclusions instead of silently dropping them.
4. Train/evaluate only rows **before onset**. No post-onset recognition is counted as early prediction.
5. 39 features: last available value, age of measurement, and six-hour change for HR, O2Sat, Temp, SBP, MAP, DBP, Resp, WBC, Lactate, Creatinine, Glucose, Platelets; plus Age, Gender, ICULOS. No patient ID, outcome, site ID or ward registry fields are features. Use dataset units unchanged; no conversion between different signals/units.
6. Plausibility bounds remove invalid values. Causal carry-forward expires vitals after 6 hours and labs after 24 hours. Never backward-fill or use future averages. Abstain if fewer than three of the seven vital signs are recent enough. Report coverage.
7. Logistic pipeline: training-only median imputation, scaling, LogisticRegression(C=1, max_iter=1000). HGB: 100 iterations, 15 leaves, min_samples_leaf=30, learning_rate=.05, L2=1, **early_stopping=False** to avoid random row-level validation leakage. Two CPU threads.
8. Choose each learned model's threshold using validation only, maximizing timely event recall then PPV under a budget of <=1 false first alert /100 pre-onset patient-hours. Choose the displayed model by validation event recall, then hourly average precision. Test is not used for either choice.
9. **One first-crossing alert per stay.** It is timely only in [onset−6, onset). An earlier alert counts false and the subsequent event remains missed, even if scores rise again. This restrictive policy is for a transparent first benchmark, **not a recommended clinical alert policy**. Negative stays count as false if any first alert occurs. Event metrics include zero-coverage stays as missed events.
10. Report hourly AUROC, average precision (not trapezoidal PR-AUC), Brier score and reliability bins; event-level sensitivity, PPV, false alerts per 100 patient-hours and median lead for timely detections only. Patient-bootstrap 400 replicates gives pointwise 95% intervals for event recall/false-alert rate. No calibrated clinical probability is claimed.

## Actual first results — not deployment-ready

After exclusions: train A **1,386**, validation A **297**, test A **298**, held-out B **1,978** records. Training uses 51,555 eligible pre-onset hours.

The validation-selected model is **HistGradientBoosting**, threshold **0.055**. Do not present its score as a validated percentage risk.

| Method | Test A AUROC | Test A AP | Timely / event patients A | False first alerts A | External B AUROC | External B AP | Timely / event patients B | False first alerts B |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Logistic Regression | 0.7150 | 0.0406 | 2 / 25 | 27 | 0.7105 | 0.0549 | 4 / 88 | 150 |
| HistGradientBoosting | 0.7690 | 0.0559 | 3 / 25 | 36 | 0.7397 | 0.0478 | 3 / 88 | 113 |
| Example threshold rule | 0.5890 | 0.0201 | 3 / 25 | 134 | 0.5463 | 0.0088 | 4 / 88 | 780 |

The rule is >=2 of HR>100, RR>22, SBP<100; **not NEWS2 or a clinically validated score**.
Under this fixed first-alert policy, HGB has fewer false alerts than the example rule on A at the same 3/25 timely detections, but misses most events and performs worse than Logistic Regression on B for AP and event recall. This is not evidence of overall clinical effectiveness.

For HGB: event recall **12.0%** on A and **3.4%** on B; alert PPV **7.7%** and **2.6%**. A misses **22/25**, B misses **85/88**. Median timely lead is 2h/4h **among only three timely detections per cohort**, not among all patients. Coverage is 98.0%/96.8%. The UI keeps failures visible and does not enable live scoring.

The exact protocol was rerun to fix score rounding in exported replay files; model settings, thresholds, splits and results were unchanged. Current artifacts: `backend/models/sepsis2019/current.json` points to an immutable run directory containing `models.joblib`, `report.json`, and held-out `cases/*.json`. Old runs are preserved.

## Review drafts and boundaries

- Research IDs are `A-p######` / `B-p######`, never the ward's `A001` etc. Source site A/B is not ward zone A/B.
- Case summaries use only the selected hour and earlier readings, carry-forward ages, the model score, and the first proposal known by then. They do not use future labels/onset or invent diagnoses.
- The optional outcome reveal and case outcome filters are **retrospective evaluator information**, not part of the model inputs.
- Neither these drafts nor the existing rule-based workflow are proof of LLM reasoning or autonomous medical judgment. Database retrieval by ID is not itself AI.
- No staff-time savings, improved outcomes, subgroup fairness, prospective validation, or applicability to Thai bedridden patients have been established.

## Next research work

Keep these results as a baseline. Define a useful clinical endpoint and alarm policy with clinicians, reserve a new independent evaluation cohort, then improve training/validation only (more data, feature/missingness analysis, calibrated models, repeated-alert policy with a measured workload budget). Conduct silent prospective validation before any clinical use. Do not tune against the already-inspected A/B results to advertise better accuracy.

## Verification

```bash
cd /Users/thuwanon/ai-patient-monitor/backend
python -m unittest discover -s tests -v
cd /Users/thuwanon/ai-patient-monitor/frontend
npm run build
npm run build:patient
```

Tests cover causal features, no second label shift, split isolation, abstention, first-alert definitions, missing artifacts, checksums, path validation, summaries without future information, staff authentication and patient isolation. Synthetic unit-test fixtures are not clinical validation data.
