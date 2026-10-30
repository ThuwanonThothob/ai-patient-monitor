# Research dataset storage

This directory is intentionally empty in Git. Downloaded source files belong in
`data/raw/`, and generated feature rows belong in `data/processed/`; both are
ignored by Git.

The active monitoring pipeline uses the free BIDMC PPG and Respiration Dataset
v1.0.0: https://physionet.org/content/bidmc/1.0.0/ . Run
`python -m ml_pipeline.download_bidmc` and `python -m ml_pipeline.train_bidmc`
from backend/. Files are verified against publisher SHA256 checksums; the license
is Open Data Commons Attribution License v1.0. Only 1 Hz HR/SpO2/RESP numerics
are used. Do not infer diagnosis labels or real patient identities from them.

The retained historical offline pipeline expects the open-access
PhysioNet/Computing in Cardiology Challenge 2012 training set (`set-a`) and
`Outcomes-a.txt`. The scientific target is **in-hospital mortality from the
first 48 hours of an ICU stay**, not ward deterioration, diagnosis, or
treatment recommendation.

Use the commands in the root README to download, prepare, train, and evaluate
locally. Do not add actual patient data, credentials, or raw clinical records to
this repository.
