"use client";

import { useCallback, useEffect, useState } from "react";
import styles from "./Ward.module.css";

type Expected = { decision: string; severity: string; would_alert: boolean };
type Scenario = { id: string; title: string; description: string; kind: string; expected: Expected };
type Stage = { id: string; agent_id: string; title: string; status: string; evidence: Record<string, unknown>; explanation: string };
type Result = { run_id: number; scenario_id: string; title: string; description: string; passed: boolean; dry_run: boolean; clinical_validation: boolean; training_data: boolean; expected: Expected; actual: Expected; stages: Stage[]; notice: string };

const decisionLabels: Record<string, string> = {
  CONTINUE_MONITORING: "ติดตามต่อโดยไม่สร้างงานใหม่",
  PROPOSE_HUMAN_REVIEW: "เสนอให้บุคลากรตรวจสอบ",
  ABSTAIN_DEVICE_FAULT: "หยุดแปลผลผู้ป่วยและตรวจอุปกรณ์",
  PROPOSE_POSTURE_REVIEW: "เสนอให้ตรวจท่าและแรงกด",
};
const agentLabels: Record<string, string> = {
  telemetry_agent: "Telemetry Agent", data_quality_agent: "Data Quality Agent",
  monitoring_agent: "Monitoring AI Agent", device_health_agent: "Device Health Agent",
  safety_supervisor: "Safety Supervisor", notification_agent: "Notification Agent (LINE Messaging API & Bed Isolation)",
  documentation_agent: "Documentation Agent",
};

function number(value: unknown, suffix = "") {
  return typeof value === "number" ? `${Number.isInteger(value) ? value : value.toFixed(2)}${suffix}` : "—";
}

function stageEvidence(stage: Stage) {
  const item = stage.evidence;
  if (stage.id === "input") {
    if (typeof item.posture === "string") {
      const hotspot = item.hotspot ? ` · จุดเสี่ยง: ${String(item.hotspot)}` : "";
      const braden = item.braden_score ? ` · Braden: ${String(item.braden_score)}` : "";
      return `${item.posture} · อยู่ท่าเดิม ${number(item.dwell_seconds, " วินาที")} · สัญญาณ ${number(item.signal_quality, "%")}${hotspot}${braden}`;
    }
    return `HR ${number(item.heart_rate, " bpm")} · SpO₂ ${number(item.spo2, "%")} · RR ${number(item.respiratory_rate, " ครั้ง/นาที")} · สัญญาณ ${number(item.signal_quality, "%")}`;
  }
  if (stage.id === "quality") return item.sensor_ok && item.fresh ? "เซนเซอร์พร้อม ข้อมูลใหม่ และผ่าน Quality Gate" : "ข้อมูลไม่ผ่าน Quality Gate — ไม่ส่งค่าผู้ป่วยให้โมเดล";
  if (stage.id === "model") {
    if (stage.status === "SKIPPED") return "งดเรียกโมเดล เพราะข้อมูลไม่ผ่านคุณภาพ";
    const forecast = typeof item.forecast === "object" && item.forecast ? item.forecast as Record<string, unknown> : null;
    const prediction = forecast ? ` · คาดการณ์ HR ${number(forecast.heart_rate)} / SpO₂ ${number(forecast.spo2)} / RR ${number(forecast.respiratory_rate)}` : "";
    const posturePred = item.predicted_posture ? ` · ท่าที่ตรวจพบ: ${String(item.predicted_posture)} (${number(item.confidence ? Number(item.confidence) * 100 : null, "%")}) · เสี่ยง: ${String(item.braden_risk ?? "—")}` : "";
    return `${String(item.dataset ?? "ไม่มี Dataset")} · ${String(item.version ?? "ไม่เรียกโมเดล")}${prediction}${posturePred}`;
  }
  if (stage.id === "decision") return `${decisionLabels[String(item.decision)] ?? String(item.decision)} · ระดับ ${String(item.severity)}`;
  if (stage.id === "action") return item.would_create_alert ? "การแจ้งเตือนและการจัดข้อมูลสำหรับญาติผ่าน LINE Messaging API พร้อมระบบ Bed Isolation (จำลอง — ไม่ส่งจริง)" : "บันทึกหลักฐานลง Audit Log เท่านั้น — ไม่ส่งแจ้งเตือน LINE";
  if (stage.id === "ground_truth") return stage.status === "MATCH" ? "ผลระบบตรงกับเฉลยที่กำหนดไว้" : "ผลไม่ตรงกับเฉลย ต้องตรวจ workflow";
  return stage.status;
}

export default function ScenarioLab({ openEvidence }: { openEvidence: () => void }) {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selected, setSelected] = useState("normal");
  const [result, setResult] = useState<Result | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const response = await fetch("/api/agent/scenarios", { cache: "no-store" });
      if (!response.ok) throw new Error();
      const body = await response.json() as { scenarios: Scenario[] };
      setScenarios(body.scenarios); setError("");
    } catch { setError("โหลด Scenario Test Center ไม่สำเร็จ"); }
  }, []);
  useEffect(() => { const timer = setTimeout(() => void load(), 0); return () => clearTimeout(timer); }, [load]);
  async function run() {
    setRunning(true); setResult(null);
    try {
      const response = await fetch(`/api/agent/scenarios/${selected}`, { method: "POST" });
      if (!response.ok) throw new Error();
      setResult(await response.json() as Result); setError("");
    } catch { setError("รันทดสอบไม่สำเร็จ ไม่มี Alert จริงถูกสร้างจากคำขอนี้"); }
    finally { setRunning(false); }
  }
  return <section className={styles.panel}>
    <div className={styles.cardHead}><div><p className={styles.eyebrow}>AI OPERATION CONSOLE · DRY RUN</p><h2 className={styles.h2}>Scenario Test Center</h2><p className={styles.muted}>เลือกเหตุการณ์เพื่อดูการส่งต่องานตั้งแต่ข้อมูลเข้าไปจนถึง Ground Truth โดยไม่กระทบข้อมูลสด ไม่ส่งการแจ้งเตือน LINE จริง และไม่นำไปฝึกโมเดล</p></div><button className={styles.secondary} onClick={openEvidence}>เปิดหลักฐานโมเดลจริง →</button></div>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    <div className={styles.scenarioGrid}>{scenarios.map((scenario) => <button key={scenario.id} className={scenario.id === selected ? styles.scenarioActive : ""} onClick={() => { setSelected(scenario.id); setResult(null); }}>
      <span>{scenario.kind === "vitals" ? "VITALS" : scenario.kind === "device" ? "DEVICE" : "POSTURE"}</span><b>{scenario.title}</b><small>{scenario.description}</small>
    </button>)}</div>
    <div className={styles.scenarioActions}><button className={styles.primary} disabled={running || !scenarios.length} onClick={() => void run()}>{running ? "กำลังส่งผ่านทีม Agent…" : "▶ รัน Scenario แบบไม่ส่งจริง"}</button><span>DRY RUN · แยกจาก Live Alert และ Training Dataset</span></div>
    {result && <div className={styles.scenarioResult} data-passed={result.passed}>
      <div className={styles.cardHead}><div><small>ผลการทดสอบ #{result.run_id}</small><h3>{result.title}</h3><p>{decisionLabels[result.actual.decision] ?? result.actual.decision}</p></div><strong>{result.passed ? "✓ Workflow ตรงตามที่คาด" : "! ต้องตรวจ Workflow"}</strong></div>
      <div className={styles.scenarioStages}>{result.stages.map((stage, index) => <article key={stage.id} data-status={stage.status}>
        <div><span>{index + 1}</span><small>{agentLabels[stage.agent_id] ?? stage.agent_id}</small></div><h4>{stage.title}</h4><b>{stageEvidence(stage)}</b><p>{stage.explanation}</p>
      </article>)}</div>
      <p className={styles.notice}>{result.notice}</p>
    </div>}
    <details className={styles.learnMoreDrawer}>
      <summary className={styles.learnMoreSummary}>
        <span>หลักการทดสอบ 6 ขั้นตอนของทีม AI Agent ในโหมดจำลอง (Dry-Run Pipeline · Learn More)</span>
        <span className={styles.learnMoreBadge}>6-Stage Safety Gate</span>
      </summary>
      <div className={styles.learnMoreBody}>
        <p className={styles.muted} style={{ marginTop: 0 }}>
          <b>วงจรการทำงานอัตโนมัติ 6 ขั้นตอนของทีม AI Agent 24 ชั่วโมง:</b><br />
          <b>1. Telemetry Input (รับข้อมูลเข้า):</b> เซนเซอร์ข้างเตียงส่งสัญญาณชีพ 1Hz (PhysioNet BIDMC) และแผ่นวัดแรงกด 32×64 (PhysioNet PMD)<br />
          <b>2. Data Quality Gate (คัดกรองคุณภาพ &amp; ป้องกัน AI มโน):</b> ตรวจสอบความสดใหม่ (≤15 วิ) หากสายหลุดหรือสัญญาณรบกวน ระบบสั่งงดแปลผล (Abstain) ทันที<br />
          <b>3. Trained AI Pipeline (โมเดลผ่านการเทรน):</b> Modified NEWS2 (RCP Scale 1), พยากรณ์ล่วงหน้า 30 วิ, สกัด 128 Spatial Features จำแนกท่านอน และคำนวณ Braden Risk 11/23<br />
          <b>4. Sentinel Triage Agent (เฝ้าระวัง 24 ชม.):</b> แจ้งเตือนพยาบาลเวรข้างเตียงทันทีที่พบความผิดปกติ<br />
          <b>5. Physician SBAR &amp; Human Acknowledgment (รายงานแพทย์ &amp; ส่วนกลาง):</b> สร้างรายงาน SBAR ให้แพทย์ตรวจทานและกดยืนยัน &ldquo;รับทราบ (Acknowledge)&rdquo;<br />
          <b>6. Family Care Agent (แจ้งเตือนญาติอัตโนมัติ):</b> เมื่อแพทย์รับทราบแล้ว ระบบจะให้ Family Care Agent แปลงข้อมูลเป็นภาษาไทยที่อบอุ่น ส่งเข้า LINE ของญาติเฉพาะเตียงตนเอง (Bed Isolation) อัตโนมัติ ป้องกันข้อมูลรั่วไหลตามมาตรฐาน PDPA
        </p>
      </div>
    </details>
  </section>;
}
