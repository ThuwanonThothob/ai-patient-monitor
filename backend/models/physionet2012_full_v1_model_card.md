# physionet2012-full-v1 model card

## Intended use

- Endpoint: In-hospital mortality from the first 48 hours of an ICU stay
- Dataset: PhysioNet/CinC Challenge 2012 v1.0.0
- Intended use: research/education demonstration only.

## Hold-out test metrics

- ROC-AUC: 0.858746
- PR-AUC: 0.454518
- Brier score: 0.090211
- Sensitivity / specificity: 0.873874 / 0.692308
- PPV / NPV: 0.313916 / 0.971487
- Threshold: 0.131148

## Limits

Research/education prototype only. This model is not clinically validated, is not a medical device, and must not be used for diagnosis, treatment, or autonomous escalation.

This is an ICU mortality endpoint, not a diagnosis or ward-deterioration prediction. It requires external validation and clinician governance before any real-world use.
