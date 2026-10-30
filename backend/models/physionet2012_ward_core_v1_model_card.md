# physionet2012-ward_core-v1 model card

## Intended use

- Endpoint: In-hospital mortality from the first 48 hours of an ICU stay
- Dataset: PhysioNet/CinC Challenge 2012 v1.0.0
- Intended use: research/education demonstration only.

## Hold-out test metrics

- ROC-AUC: 0.698074
- PR-AUC: 0.22924
- Brier score: 0.116617
- Sensitivity / specificity: 0.990991 / 0.114659
- PPV / NPV: 0.152778 / 0.9875
- Threshold: 0.073394

## Limits

Research/education prototype only. This model is not clinically validated, is not a medical device, and must not be used for diagnosis, treatment, or autonomous escalation.

This is an ICU mortality endpoint, not a diagnosis or ward-deterioration prediction. It requires external validation and clinician governance before any real-world use.
