"""Staff-only read-only evidence API. No training, cloud calls or live alerts.

Mounted only on the existing authenticated staff app. The patient app does not
mount these routes. Serving precomputed artifacts keeps inference/training off
the telemetry event loop, and no clinical database is written here.
"""
import hashlib
import json
from pathlib import Path
import re
from threading import RLock

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

ROOT = Path(__file__).resolve().parent / "models/sepsis2019"
router = APIRouter(prefix="/api/research/sepsis", tags=["research-only"])


class EvidenceStore:
    def __init__(self, root=ROOT):
        self.root = root
        self.lock = RLock()
        self.pointer = None
        self.report = None

    def load(self):
        with self.lock:
            try:
                pointer = (self.root / "current.json").read_bytes()
                if pointer == self.pointer and self.report is not None:
                    return self.report
                info = json.loads(pointer)
                if not re.fullmatch(r"\d{8}T\d{6}Z-[a-f0-9]{8}", info["run_id"]):
                    raise ValueError("Invalid run ID")
                content = (self.root / info["run_id"] / "report.json").read_bytes()
                if hashlib.sha256(content).hexdigest() != info["report_sha256"]:
                    raise ValueError("Report integrity failure")
                report = json.loads(content)
                if report["schema_version"] != 1 or report["run_id"] != info["run_id"] or report["live_enabled"]:
                    raise ValueError("Unsupported research artifact")
                self.pointer, self.report = pointer, report
                return report
            except FileNotFoundError as error:
                raise HTTPException(503, "ยังไม่มีผลเทรน: รัน python -m ml_pipeline.train_sepsis2019 ใน backend") from error
            except (ValueError, KeyError, TypeError) as error:
                raise HTTPException(503, "ไฟล์ผลวิจัยไม่ผ่านการตรวจสอบ กรุณาตรวจ artifact ก่อนใช้งาน") from error

    def case(self, case_id, report):
        if not re.fullmatch(r"[AB]-p\d{6}", case_id):
            raise HTTPException(404, "Unknown research case (not a ward Patient ID)")
        entry = next((item for item in report["cases"] if item["id"] == case_id), None)
        if entry is None:
            raise HTTPException(404, "Unknown research case")
        try:
            content = (self.root / report["run_id"] / "cases" / (case_id + ".json")).read_bytes()
            if hashlib.sha256(content).hexdigest() != entry["sha256"]:
                raise ValueError("Case integrity failure")
            return json.loads(content)
        except (OSError, ValueError) as error:
            raise HTTPException(503, "ไฟล์เคสไม่ผ่านการตรวจสอบ") from error


store = EvidenceStore()


def case_summary(case, report, hour):
    """Deterministic evidence-grounded draft using only measurements <= cursor."""
    history = [row for row in case["timeline"] if row["hour"] <= hour]
    if not history or hour > case["timeline"][-1]["hour"]:
        raise HTTPException(422, "Hour outside the observed pre-onset timeline")
    latest = history[-1]
    name = report["selected_model"]
    score = latest["scores"][name]
    threshold = report["thresholds"][name]
    crossing = next((row["hour"] for row in history if row["scores"][name] is not None and row["scores"][name] >= threshold), None)
    lines = ["Smart Ward — Research review draft / ร่างสรุปเพื่อทบทวนข้อมูลวิจัย",
             report["notice"], f"Run: {report['run_id']}", f"Source: {report['source']}",
             f"Case: {case['id']} | site {case['site']} | {case['split']} | as-of ICU hour {latest['hour']:g}",
             "", "S — สถานการณ์ ณ ชั่วโมงที่เลือก",
             f"Model: {name}; score={score if score is not None else 'ABSTAIN'}; threshold={threshold:.4f}",
             "คะแนนโมเดลยังไม่ใช่ความน่าจะเป็นทางคลินิกที่ผ่านการสอบเทียบ",
             f"First proposal by this hour: {crossing if crossing is not None else 'none'}",
             "", "B — หลักฐานข้อมูลที่ใช้ (ค่าที่ถือไว้จากอดีต พร้อมอายุข้อมูล)"]
    missing = []
    for key, value in latest["input_values"].items():
        if value is None:
            missing.append(key)
        else:
            age = latest["input_age_hours"][key]
            lines.append(f"{key}: {value:g} [source ICU hour {latest['hour'] - age:g}; age {age:g} h]")
    lines += ["Missing/expired: " + (", ".join(missing) or "none"), "",
              "A — การทบทวน", "eligible" if latest["eligible"] else "ABSTAIN: มี vital ที่ยังใช้ได้ไม่ถึง 3 ตัว",
              "สรุปนี้ไม่ใช้ label หรือเหตุการณ์จากอนาคต และไม่ได้อธิบายว่าตัวแปรใดเป็นสาเหตุของคะแนน",
              "", "R — ขั้นตอนต่อไป", "ตรวจแหล่งข้อมูลและบริบทโดยบุคลากร ก่อนอนุมัติข้อเสนอใด ๆ",
              "ไม่มีการวินิจฉัย สั่งยา ติดต่อแพทย์ หรือส่งต่อรถพยาบาลจากรายงานนี้"]
    return "\n".join(lines)


@router.get("/status")
def status():
    try:
        report = store.load()
    except HTTPException as error:
        return {"status": "UNAVAILABLE", "research_only": True, "live_enabled": False, "message": error.detail}
    return {key: value for key, value in report.items() if key not in {"cases", "split_ids"}}


@router.get("/cases")
def cases(split: str = Query("test", pattern="^(test|external_B)$"),
          outcome: str = Query("all", pattern="^(all|timely_alert|early_false_alert|false_alert|missed_event|no_alert_no_event)$"),
          search: str = Query("", max_length=40), offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    report = store.load()
    items = [item for item in report["cases"] if item["split"] == split
             and (outcome == "all" or item["outcome"] == outcome) and search.lower() in item["id"].lower()]
    return {"run_id": report["run_id"], "total": len(items),
            "cases": [{key: value for key, value in item.items() if key != "sha256"} for item in items[offset:offset + limit]]}


@router.get("/cases/{case_id}")
def get_case(case_id: str):
    report = store.load()
    return {**store.case(case_id, report), "run_id": report["run_id"],
            "selected_model": report["selected_model"], "thresholds": report["thresholds"]}


@router.get("/cases/{case_id}/summary", response_class=PlainTextResponse)
def summary(case_id: str, hour: float = Query(..., ge=1, le=100000, allow_inf_nan=False)):
    report = store.load()
    case = store.case(case_id, report)
    return PlainTextResponse(case_summary(case, report, hour), headers={
        "Content-Disposition": f'attachment; filename="research-{case_id}-hour-{hour:g}.txt"', "Cache-Control": "no-store"})


@router.get("/report", response_class=PlainTextResponse)
def report_text():
    report = store.load()
    # This is benchmark evidence, not a patient handoff document.
    payload = {key: value for key, value in report.items() if key not in {"cases", "split_ids"}}
    return PlainTextResponse(json.dumps(payload, ensure_ascii=False, indent=2), headers={
        "Content-Disposition": 'attachment; filename="sepsis-research-evidence.txt"', "Cache-Control": "no-store"})
