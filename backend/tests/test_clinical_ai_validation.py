import json
import unittest
from pathlib import Path

from ai_models import llm_summary, forecasting, monitor_model


class ClinicalAiValidationTests(unittest.TestCase):
    def test_metadata_contains_moving_average_bounds_and_alert_burden(self):
        """P3-03, P3-04: Metadata contains moving average baseline, error bounds and alert burden."""
        meta_path = Path(__file__).resolve().parents[1] / "models/bidmc_monitor_v1_metadata.json"
        self.assertTrue(meta_path.exists())
        metadata = json.loads(meta_path.read_text())

        # Check moving average baseline
        self.assertIn("validation_moving_average_mae", metadata)
        self.assertIn("test_moving_average_mae", metadata)
        for key in ("heart_rate", "spo2", "respiratory_rate"):
            self.assertIn(key, metadata["test_moving_average_mae"])
            self.assertIsInstance(metadata["test_moving_average_mae"][key], (int, float))

        # Check stratified error bounds
        self.assertIn("test_error_bounds", metadata)
        bounds = metadata["test_error_bounds"]
        for predictor in ("random_forest", "persistence_baseline", "moving_average_baseline", "selected_forecast"):
            self.assertIn(predictor, bounds)
            for key in ("heart_rate", "spo2", "respiratory_rate"):
                self.assertIn(key, bounds[predictor])
                item = bounds[predictor][key]
                self.assertIn("mae", item)
                self.assertIn("rmse", item)
                self.assertIn("p95_abs_error", item)
                self.assertIn("exceed_tolerance_rate", item)

        # Check held-out alert burden
        self.assertIn("test_alert_burden", metadata)
        burden = metadata["test_alert_burden"]
        self.assertIn("evaluated_patient_hours", burden)
        self.assertIn("anomaly_episodes_count", burden)
        self.assertIn("anomaly_episodes_per_patient_hour", burden)
        self.assertGreater(burden["anomaly_episodes_per_patient_hour"], 0)
        self.assertIn("limitation_note", burden)

    def test_enforce_clinical_llm_guardrails_blocks_forbidden_actions(self):
        """P3-05 & Guardrail #1: Post-generation filter blocks prescription and diagnosis."""
        prescriptive = "คนไข้มีอาการหอบเหนื่อย สั่งจ่ายยา Adrenaline 1 mg และฉีดทันที"
        filtered = llm_summary.enforce_clinical_llm_guardrails(
            prescriptive,
            vitals_citation="HR 110, SpO2 91%"
        )
        self.assertNotIn("สั่งจ่ายยา", filtered)
        self.assertIn("ระบบตรวจพบข้อความที่มีลักษณะสั่งการรักษาหรือวินิจฉัยโรคโดยตรง", filtered)
        self.assertIn("HR 110, SpO2 91%", filtered)

        diagnostic = "จากการตรวจพบว่า ผู้ป่วย วินิจฉัยว่าเป็นโรค ปอดอักเสบติดเชื้อ"
        filtered2 = llm_summary.enforce_clinical_llm_guardrails(diagnostic)
        self.assertNotIn("วินิจฉัยว่าเป็นโรค", filtered2)
        self.assertIn("ระบบตรวจพบข้อความที่มีลักษณะสั่งการรักษาหรือวินิจฉัยโรคโดยตรง", filtered2)

    def test_supported_gemini_models_in_fallback_preferences(self):
        """P3-05: Model preferences only contain active, supported Gemini 2.x models."""
        for model in llm_summary.FALLBACK_MODEL_PREFERENCES:
            self.assertNotIn("gemini-1.5", model)
            self.assertNotIn("gemini-3.6", model)
            self.assertNotIn("gemini-3.7", model)
            self.assertNotIn("gemini-3.8", model)
            self.assertTrue(model.startswith("gemini-2."))

    def test_prototype_forecasting_module_has_research_only_flag(self):
        """P3-02: Legacy forecasting module is marked research only."""
        res = forecasting.predict_future_vitals([70, 72, 74, 76, 78], [98, 97, 98, 96, 97])
        self.assertTrue(res.get("research_only"))


if __name__ == "__main__":
    unittest.main()
