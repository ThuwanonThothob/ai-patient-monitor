"""Synthetic fixtures test the implementation, not clinical model accuracy."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from fastapi import HTTPException
import numpy as np

from ml_pipeline.sepsis2019 import (Record, SIGNALS, FEATURES, alarm_stats, choose_threshold,
                                    evaluate, features, prepare, read_record, split_records)
from research_api import EvidenceStore, case_summary
from evidence_handoff import format_evidence_handoff


def fixture(ident="A-p000001", site="A", event=False):
    values = np.tile([80., 98, 37, 120, 85, 70, 18, 7, 1.5, .9, 100, 220], (24, 1))
    labels = np.zeros(24, dtype=int)
    if event:
        labels[12:] = 1
    return Record(ident, site, values, labels, np.arange(1., 25.), 65, 1, 19. if event else None)


class FeatureTests(unittest.TestCase):
    def test_future_changes_do_not_change_past_features(self):
        record = fixture()
        before = features(record)[0]
        record.values[12:] = 500
        record.labels[:] = 1
        after = features(record)[0]
        np.testing.assert_equal(before[:12], after[:12])
        self.assertEqual(before.shape[1], len(FEATURES))
        self.assertNotIn("SepsisLabel", FEATURES)

    def test_no_backward_fill_and_expiration(self):
        record = fixture()
        record.values[:4, 0] = np.nan
        record.values[5:, 0] = np.nan
        _, _, carried = features(record)
        self.assertTrue(np.isnan(carried[:4, 0]).all())
        self.assertEqual(carried[10, 0], 80)
        self.assertTrue(np.isnan(carried[11, 0]))

    def test_abstain_with_insufficient_recent_vitals(self):
        record = fixture()
        record.values[:, :7] = np.nan
        self.assertFalse(features(record)[1].any())

    def test_post_onset_rows_not_used(self):
        record = fixture(event=True)
        x, y, entries = prepare([record])
        self.assertEqual(len(x), 18)
        self.assertEqual(y.sum(), 6)  # Already-shifted labels, no second shift.
        self.assertLess(entries[0]["hours"].max(), record.onset)

    def test_patient_and_site_split_disjoint_reproducible(self):
        records = [fixture(f"A-p{i:06}", event=i % 4 == 0) for i in range(100)]
        records += [fixture(f"B-p{i:06}", "B", event=i % 4 == 0) for i in range(20)]
        groups = split_records(records)
        sets = [set(r.id for r in group) for group in groups.values()]
        self.assertEqual(sum(map(len, sets)), len(set.union(*sets)))
        self.assertEqual(len(groups["train"]), 70)
        self.assertTrue(all(r.site == "B" for r in groups["external_B"]))
        self.assertEqual([r.id for r in groups["test"]], [r.id for r in split_records(records)["test"]])

    def test_parser_validation_and_onset(self):
        names = [*SIGNALS, "Age", "Gender", "ICULOS", "SepsisLabel"]
        lines = ["|".join(names)]
        for hour in range(1, 25):
            lines.append("|".join(map(str, [80, 98, 37, 120, 85, 70, 18, 7, 1.5, .9, 100, 220, 65, 1, hour, int(hour >= 13)])))
        content = "\n".join(lines).encode()
        record = read_record(content, "A-p000001", "A")
        self.assertEqual(record.onset, 19)
        self.assertIsNone(record.excluded)
        with self.assertRaises(ValueError):
            read_record(content.replace(b"SepsisLabel", b"NotALabel"), "A-p000001", "A")
        first_positive = (lines[0] + "\n" + "\n".join(line.rsplit("|", 1)[0] + "|1" for line in lines[1:])).encode()
        self.assertEqual(read_record(first_positive, "x", "A").excluded, "left_censored_onset")


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        _, self.y, self.entries = prepare([fixture(event=True), fixture("A-p000002")])

    def test_first_alert_event_definition(self):
        scores = np.zeros(len(self.y))
        scores[12] = .8  # Hour 13; onset 19 -> six hours early, correct.
        scores[18] = .8  # Negative stay -> false.
        stats, outcomes = alarm_stats(self.entries, scores, .5)
        self.assertEqual(stats["event_sensitivity"], 1)
        self.assertEqual(stats["false_alerts"], 1)
        self.assertEqual(stats["alert_ppv"], .5)
        self.assertEqual(outcomes[0]["lead_hours"], 6)

    def test_very_early_alert_cannot_be_reclassified_using_future(self):
        scores = np.zeros(len(self.y))
        scores[0] = scores[12] = .8
        stats, outcomes = alarm_stats(self.entries, scores, .5)
        self.assertEqual(stats["timely_alerts"], 0)
        self.assertEqual(stats["missed_events"], 1)
        self.assertEqual(stats["false_alerts"], 1)
        self.assertEqual(outcomes[0]["outcome"], "early_false_alert")

    def test_no_alert_and_no_positive_are_defined(self):
        _, y, entries = prepare([fixture()])
        metric, _ = evaluate(y, np.zeros(len(y)), entries, .5)
        self.assertIsNone(metric["event_sensitivity"])
        self.assertIsNone(metric["alert_ppv"])
        self.assertIsNone(metric["hourly_auroc"])
        json.dumps(metric, allow_nan=False)

    def test_zero_coverage_event_is_counted_as_missed(self):
        record = fixture(event=True)
        record.values[:] = np.nan
        _, y, entries = prepare([record, fixture("A-p000002")])
        stats, _ = alarm_stats(entries, np.zeros(len(y)), .5)
        self.assertEqual(stats["missed_events"], 1)
        self.assertLess(stats["coverage"], 1)

    def test_threshold_selection_budget_and_alignment(self):
        scores = np.linspace(.01, .9, len(self.y))
        threshold = choose_threshold(self.entries, scores, budget=.01)
        stats, _ = alarm_stats(self.entries, scores, threshold)
        self.assertLessEqual(stats["false_alerts_per_100_patient_hours"], .01)
        with self.assertRaises(ValueError):
            alarm_stats(self.entries, scores[:-1], threshold)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ward-research-test-")
        self.root = Path(self.temp.name)
        self.store = EvidenceStore(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_and_invalid_artifacts_fail_closed(self):
        with self.assertRaises(HTTPException) as error:
            self.store.load()
        self.assertEqual(error.exception.status_code, 503)
        (self.root / "current.json").write_text(json.dumps({"run_id": "../../secrets", "report_sha256": "x"}))
        with self.assertRaises(HTTPException):
            self.store.load()

    def test_case_hash_and_identifier_validation(self):
        run_id = "20260929T000000Z-01234567"
        folder = self.root / run_id / "cases"
        folder.mkdir(parents=True)
        content = b'{"id": "A-p000001"}'
        path = folder / "A-p000001.json"
        path.write_bytes(content)
        report = {"run_id": run_id, "cases": [{"id": "A-p000001", "sha256": hashlib.sha256(content).hexdigest()}]}
        self.assertEqual(self.store.case("A-p000001", report)["id"], "A-p000001")
        for invalid in ("../current", "A001", "A-p999999"):
            with self.assertRaises(HTTPException):
                self.store.case(invalid, report)
        path.write_bytes(b"tampered")
        with self.assertRaises(HTTPException):
            self.store.case("A-p000001", report)

    def test_summary_never_uses_future_or_labels(self):
        point = {"hour": 1, "eligible": True, "scores": {"logistic": .01},
                 "input_values": {"HR": 80, "Temp": None}, "input_age_hours": {"HR": 0, "Temp": 168}}
        case = {"id": "A-p000001", "site": "A", "split": "test", "onset_hour": 19,
                "timeline": [point, {**copy.deepcopy(point), "hour": 2, "input_values": {"HR": 250}}]}
        report = {"run_id": "fixture", "selected_model": "logistic", "thresholds": {"logistic": .5},
                  "source": "fixture", "notice": "research only"}
        first = case_summary(case, report, 1)
        self.assertIn("HR: 80", first)
        self.assertNotIn("250", first)
        self.assertIn("Temp", first)
        altered = copy.deepcopy(case)
        altered["onset_hour"] = 7
        altered["timeline"][1]["scores"]["logistic"] = .99
        self.assertEqual(first, case_summary(altered, report, 1))
        with self.assertRaises(HTTPException):
            case_summary(case, report, 3)

    def test_ward_draft_does_not_invent_missing_values_or_show_stale_forecast(self):
        profile = {"zone": "A", "room_number": "A-01", "blood_glucose_mg_dl": 999, "heart_rate": 999}
        monitor = {"status": "STALE_DATA", "heart_rate": 80, "timestamp": 1700000000,
                   "source": "BIDMC_REPLAY", "source_record": "bidmc_04",
                   "analysis": {"status": "READY", "forecast": {"heart_rate": 555}}}
        text = format_evidence_handoff("A001", profile, monitor)
        self.assertIn("HR: 80", text)
        self.assertIn("bidmc_04", text)
        self.assertNotIn("999", text)
        self.assertNotIn("555", text)
        self.assertIn("SpO2: ไม่มีข้อมูล", text)


class PublishedArtifactTests(unittest.TestCase):
    def test_saved_scores_match_first_alert_metrics_and_stay_namespaces(self):
        store = EvidenceStore()
        try:
            report = store.load()
        except HTTPException:
            self.skipTest("Optional research training has not been run")
        for item in report["cases"]:
            case = store.case(item["id"], report)
            for name, result in case["outcomes"].items():
                first = next((row["hour"] for row in case["timeline"]
                              if row["scores"][name] is not None and row["scores"][name] >= report["thresholds"][name]), None)
                self.assertEqual(first, result["first_alert_hour"], (item["id"], name))
            self.assertIn(case["id"], report["split_ids"][case["split"]])
            self.assertNotIn(case["id"], report["split_ids"]["train"])


if __name__ == "__main__":
    unittest.main()
