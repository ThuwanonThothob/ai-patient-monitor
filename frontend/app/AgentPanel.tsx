"use client";

import { useCallback, useEffect, useState } from "react";
import styles from "./Ward.module.css";
import ScenarioLab from "./ScenarioLab";

type Dataset = { id: string; name: string; role: string; access: string; source: string; fit: string };
type Model = { id: string; status: string; dataset_id: string; methods: string[]; metric: string; result: unknown; limitation: string };
type Step = { id: number; sequence: number; agent_id: string; tool_name: string; status: string; input: unknown; output: unknown };
type Run = { id: number; patient_id: string; decision: string; severity: string; summary: string; source: string; model_version: string; requires_human_review: boolean; alert_id?: number | null; created_at: number; steps: Step[] };
type AgentRole = { id: string; name: string; responsibility: string; implementation: string; automatic_actions: string[]; human_gate: string[]; event_sources: string[] };
type AgentStatus = {
  runtime: { status: string; heartbeat?: number; processed_events?: number; alert_proposals?: number; last_error?: string | null; model_version?: string };
  last_hour: { runs: number; proposals: number; abstentions: number; model_completed?: number; waiting_for_window?: number; duplicates_suppressed?: number };
  policy: { automatic_actions: string[]; human_required: string[]; cloud_llm_in_safety_loop: boolean };
  team: { version: string; orchestrator: { name: string; strategy: string; cloud_llm_required: boolean }; roles: AgentRole[]; handoff: string[]; safety_contract: { human_approval_for_clinical_action: boolean; all_actions_audited: boolean } };
  datasets: Dataset[];
  models: Model[];
};
type BedsideStatus = { devices: Record<string, number>; ground_truth_labels: number; posture_observations: number; posture_model: string };

const decisions: Record<string, string> = {
  CONTINUE_MONITORING: "ติดตามต่อ",
  WAIT_FOR_MODEL_WINDOW: "รอข้อมูลให้ครบหน้าต่างโมเดล",
  ABSTAIN_STALE_MODEL: "งดใช้ผลโมเดลเก่า",
  ABSTAIN_STALE_DATA: "งดใช้ข้อมูลเก่า",
  ABSTAIN_INVALID_DATA: "งดใช้ข้อมูลไม่ผ่านคุณภาพ",
  SUPPRESS_DUPLICATE_ALERT: "ระงับ Alert ซ้ำ",
  PROPOSE_HUMAN_REVIEW: "เสนอให้บุคลากรตรวจสอบ",
};
const severityLabels: Record<string, string> = { critical: 'เร่งด่วน', warning: 'เฝ้าระวัง', info: 'ข้อมูลระบบ' };

function when(value?: number) {
  return value ? new Date(value * 1000).toLocaleString("th-TH", { hour12: false }) : "—";
}

function compact(value: unknown) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(4);
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function objectValue(value: unknown) {
  return typeof value === 'object' && value !== null ? value as Record<string, unknown> : {};
}

const runtimeLabels: Record<string, string> = { RUNNING: 'กำลังติดตาม', STARTING: 'กำลังเริ่มระบบ', STALE: 'ข้อมูลสถานะขาดช่วง', ERROR: 'ต้องตรวจสอบระบบ', NOT_INITIALIZED: 'ยังไม่เริ่มทำงาน' };
const toolLabels: Record<string, string> = {
  observe_vitals: 'รับค่าสัญญาณชีพ', validate_data_contract: 'ตรวจคุณภาพและความใหม่ของข้อมูล',
  read_trained_model: 'อ่านผลโมเดลที่เทรนไว้', read_reviewed_care_context: 'อ่านบริบทที่บุคลากรยืนยัน',
  apply_guarded_alert_policy: 'ตรวจเงื่อนไขและเสนอให้คนทบทวน',
  document_decision: 'บันทึกหลักฐานและร่างสรุป',
};
const agentLabels: Record<string, string> = {
  telemetry_agent: 'Telemetry Agent', data_quality_agent: 'Data Quality Agent',
  monitoring_agent: 'Monitoring AI Agent', device_health_agent: 'Device Health Agent',
  care_coordinator_agent: 'Care Coordinator Agent', notification_agent: 'Notification Agent',
  documentation_agent: 'Documentation Agent', safety_supervisor: 'Safety Supervisor',
};
const capabilityLabels: Record<string, string> = {
  read_validated_vitals: 'รับค่าสัญญาณชีพ', attach_source_and_timestamp: 'ผูกแหล่งข้อมูลและเวลา',
  validate_range: 'ตรวจช่วงค่า', validate_freshness: 'ตรวจความใหม่', abstain: 'งดตัดสินใจเมื่อข้อมูลไม่พร้อม',
  read_model_result: 'อ่านผลโมเดล', compare_thresholds: 'เทียบเกณฑ์', propose_review: 'เสนอรายการให้ตรวจ',
  detect_device_fault: 'ตรวจอุปกรณ์ผิดปกติ', detect_stale_device: 'ตรวจอุปกรณ์ขาดการเชื่อมต่อ',
  materialize_approved_task: 'สร้างรอบงานจากแผนที่อนุมัติ', count_overdue_tasks: 'ตรวจงานเกินเวลา', prioritize_open_work: 'จัดลำดับงานเปิด',
  enqueue_configured_push: 'เข้าคิว Web Push', retry_delivery: 'ลองส่งใหม่', write_delivery_audit: 'บันทึกผลส่ง',
  write_agent_trace: 'บันทึกขั้นตอน Agent', draft_evidence_summary: 'ร่างสรุปจากหลักฐาน',
  enforce_policy: 'บังคับนโยบายความปลอดภัย', suppress_duplicate: 'ระงับงานซ้ำ', route_for_human_review: 'ส่งให้คนตรวจ',
  diagnosis: 'วินิจฉัย', treatment_change: 'เปลี่ยนการรักษา', repair_device: 'ซ่อมอุปกรณ์',
  declare_patient_emergency: 'ประกาศเหตุฉุกเฉิน', activate_care_plan: 'เปิดใช้แผนดูแล',
  complete_or_skip_task: 'ปิดหรือข้ามงาน', change_medication: 'เปลี่ยนยา', contact_doctor: 'ติดต่อแพทย์',
  contact_emergency_service: 'ติดต่อฉุกเฉิน', sign_clinical_document: 'ลงนามเอกสารทางคลินิก',
  edit_historical_measurement: 'แก้ข้อมูลย้อนหลัง', treatment_or_dose_change: 'เปลี่ยนการรักษาหรือขนาดยา',
  close_alert: 'ปิดเหตุการณ์', external_dispatch: 'ส่งต่อภายนอก',
};
function capabilityList(values: string[]) { return values.map((value) => capabilityLabels[value] ?? value).join(' · '); }

function stepSummary(step: Step) {
  const output = typeof step.output === 'object' && step.output ? step.output as Record<string, unknown> : {};
  if (step.tool_name === 'observe_vitals') return `HR ${compact(output.heart_rate)} · SpO₂ ${compact(output.spo2)} · RR ${compact(output.respiratory_rate)}`;
  if (step.tool_name === 'validate_data_contract') return output.valid && output.fresh ? 'ข้อมูลผ่านการตรวจคุณภาพและยังใหม่' : 'งดใช้ข้อมูลรอบนี้';
  if (step.tool_name === 'read_trained_model') {
    if (output.analysis_status !== 'READY') return 'โมเดลยังไม่พร้อมหรือผลเก่า';
    const forecast = objectValue(output.forecast);
    const prediction = Object.keys(forecast).length ? ` · คาดการณ์ HR ${compact(forecast.heart_rate)} / SpO₂ ${compact(forecast.spo2)} / RR ${compact(forecast.respiratory_rate)}` : '';
    return `โมเดลพร้อม · ${output.is_anomaly ? 'พบรูปแบบต่างจากชุดฝึก' : 'ไม่พบรูปแบบต่างจากชุดฝึก'}${prediction}`;
  }
  if (step.tool_name === 'read_reviewed_care_context') return `แผนดูแล ${compact(output.active_plans)} · งานเปิด ${compact(output.open_tasks)} · เกินกำหนด ${compact(output.overdue_tasks)}`;
  if (step.tool_name === 'apply_guarded_alert_policy') return output.requires_human_review ? 'เสนอให้บุคลากรตรวจสอบ' : 'ไม่สร้างงานใหม่';
  if (step.tool_name === 'document_decision') return output.audit_trace ? 'บันทึกเหตุผลและผลลัพธ์เพื่อตรวจสอบย้อนหลังแล้ว' : 'ยังไม่บันทึกหลักฐาน';
  return step.status;
}

function reviewSummary(run: Run) {
  const observation = run.steps.find((step) => step.tool_name === 'observe_vitals');
  return `${severityLabels[run.severity] ?? run.severity}${observation ? ` · ${stepSummary(observation)}` : ''}`;
}

export default function AgentPanel({ openPatient, openEvidence }: { openPatient: (id: string) => void; openEvidence: () => void }) {
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [bedside, setBedside] = useState<BedsideStatus | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [statusResponse, runsResponse, bedsideResponse] = await Promise.all([
        fetch("/api/agent/status", { cache: "no-store" }),
        fetch("/api/agent/runs?limit=30", { cache: "no-store" }),
        fetch("/api/bedside/status", { cache: "no-store" }),
      ]);
      if (!statusResponse.ok || !runsResponse.ok) throw new Error();
      const nextStatus = await statusResponse.json() as AgentStatus;
      const nextRuns = (await runsResponse.json() as { runs: Run[] }).runs;
      setBedside(bedsideResponse.ok ? await bedsideResponse.json() as BedsideStatus : null);
      setStatus(nextStatus); setRuns(nextRuns); setError("");
      setSelected((current) => current && nextRuns.some((run) => run.id === current) ? current : nextRuns[0]?.id ?? null);
    } catch { setError("โหลดสถานะทีม AI Agent ไม่สำเร็จ อย่าตีความว่า Agent กำลังทำงาน"); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => {
    const initial = setTimeout(() => void load(), 0);
    const timer = setInterval(() => void load(), 15000);
    return () => { clearTimeout(initial); clearInterval(timer); };
  }, [load]);
  const run = runs.find((item) => item.id === selected) ?? runs[0];
  const reviewRuns = runs.filter((item) => item.requires_human_review).slice(0, 8);
  const observed = run?.steps.find((step) => step.tool_name === 'observe_vitals');
  const model = run?.steps.find((step) => step.tool_name === 'read_trained_model');
  const policy = run?.steps.find((step) => step.tool_name === 'apply_guarded_alert_policy');

  return <>
    <ScenarioLab openEvidence={openEvidence} />
    <section className={styles.panel}>
      <div className={styles.cardHead}><div><p className={styles.eyebrow}>MULTI-AGENT CARE TEAM</p><h2 className={styles.h2}>ทีม AI Agent กำลังแบ่งงานกันทำ</h2><p className={styles.muted}>Agent แต่ละตัวมีหน้าที่และสิทธิ์แยกกัน ผู้ควบคุมความปลอดภัยจะหยุดงานที่ต้องใช้การตัดสินใจทางคลินิกและส่งให้บุคลากรยืนยัน</p></div><button className={styles.secondary} disabled={loading} onClick={() => void load()}>โหลดสถานะล่าสุด</button></div>
      {error && <p className={styles.error} role="alert">{error}</p>}
      <div className={styles.aiStatusGrid}>
        <div className={styles.aiStatusPrimary}><span className={styles.statusDot} /><div><small>สถานะขณะนี้</small><strong>{runtimeLabels[status?.runtime.status ?? ''] ?? 'กำลังตรวจสอบสถานะ'}</strong><span>อัปเดต {when(status?.runtime.heartbeat)}</span></div></div>
        <div><small>ข้อมูลที่ตรวจแล้วตั้งแต่เปิดระบบ</small><strong>{status?.runtime.processed_events ?? 0}</strong><span>รอบข้อมูล</span></div>
        <div><small>รายการที่เสนอให้คนตรวจ</small><strong>{status?.runtime.alert_proposals ?? 0}</strong><span>ไม่ดำเนินการแทนคน</span></div>
        <div><small>รอบใน 1 ชั่วโมง</small><strong>{status?.last_hour.runs ?? 0}</strong><span>งดประเมินเมื่อข้อมูลไม่พร้อม {status?.last_hour.abstentions ?? 0}</span></div>
      </div>
      <div className={styles.careFlow} aria-label="การส่งต่องานระหว่าง AI Agent"><div><b>1</b><span>Telemetry</span><small>รับ HR · SpO₂ · RR (1 Hz)</small></div><div><b>2</b><span>Data Quality</span><small>ตรวจความใหม่ ขาดช่วง → Abstain</small></div><div><b>3</b><span>Monitoring AI</span><small>Random Forest 30s vs Baseline</small></div><div><b>4</b><span>Care Coordinator</span><small>ดูแผนและงานค้าง</small></div><div><b>5</b><span>Safety Supervisor</span><small>อนุญาต หยุด หรือส่งให้คน</small></div><div><b>6</b><span>Documentation</span><small>บันทึกเหตุผลทุกขั้น</small></div></div>
      {run ? <div className={styles.aiProof}><div className={styles.cardHead}><div><small>หลักฐานการทำงานรอบล่าสุด</small><h3>{run.patient_id} · {decisions[run.decision] ?? run.decision}</h3></div><button className={styles.link} onClick={() => openPatient(run.patient_id)}>เปิดผู้ป่วย →</button></div><div className={styles.aiProofGrid}>
        <div><span>ข้อมูลเข้า</span><b>{observed ? stepSummary(observed) : 'ไม่มีข้อมูล'}</b><small>{run.source} · {when(run.created_at)}</small></div>
        <div><span>ผลโมเดล</span><b>{model ? stepSummary(model) : 'ไม่ได้เรียกโมเดล'}</b><small>{run.model_version}</small></div>
        <div><span>Agent ตัดสินใจ</span><b>{decisions[run.decision] ?? run.decision}</b><small>{run.summary}</small></div>
        <div><span>สิ่งที่ระบบทำ</span><b>{run.alert_id ? `สร้าง Alert #${run.alert_id}` : run.requires_human_review ? 'กำลังสร้างงานให้คนตรวจ' : 'ไม่สร้างงานใหม่'}</b><small>{policy ? stepSummary(policy) : 'บันทึกการประเมินเท่านั้น'}</small></div>
      </div></div> : <p className={styles.empty}>ยังไม่มีรอบการทำงาน เปิดระบบและรอข้อมูลต่อเนื่องประมาณ 60–70 วินาที</p>}
      <p className={styles.notice}>ระบบติดตามและแจ้งเตือนทำงานในเครื่อง ไม่พึ่ง Gemini ส่วน Gemini ใช้เฉพาะเมื่อบุคลากรถามหรือขอสรุปข้อความ</p>
      {status?.runtime.last_error && <p className={styles.error}>Agent error ล่าสุด: {status.runtime.last_error}</p>}
    </section>

    <section className={styles.panel}>
      <details className={styles.learnMoreDrawer}>
        <summary className={styles.learnMoreSummary}>
          <span>👥 ผังขอบเขตหน้าที่และความรับผิดชอบของทีม AI Agent (Learn More)</span>
          <span className={styles.learnMoreBadge}>ดูขอบเขตหน้าที่</span>
        </summary>
        <div className={styles.learnMoreBody}>
          <div className={styles.cardHead}><div><p className={styles.eyebrow}>AGENT RESPONSIBILITY MAP</p><h3 style={{ margin: 0 }}>ใครรับผิดชอบอะไร</h3><p className={styles.muted}>ไม่ใช่ Chatbot หลายชื่อ แต่เป็น worker แยกขอบเขต เชื่อมกันด้วย event และมี audit trail</p></div><span className={styles.badge}>{status?.team?.version ?? 'กำลังโหลด'}</span></div>
          <div className={styles.agentTeamGrid}>{status?.team?.roles.map((role) => <article key={role.id}>
            <span>{role.name}</span><h3>{role.responsibility}</h3>
            <p><b>ทำอัตโนมัติ:</b> {capabilityList(role.automatic_actions) || 'ไม่มี'}</p>
            <p><b>ต้องส่งให้คน:</b> {capabilityList(role.human_gate) || 'ไม่เกี่ยวกับการตัดสินใจทางคลินิก'}</p>
            <small>{role.implementation}</small>
          </article>)}</div>
          <p className={styles.notice}>หลักความปลอดภัย: AI ทำงานติดตาม งานเอกสาร งานจัดคิว และการแจ้งเตือนได้ แต่การวินิจฉัย เปลี่ยนยา เปลี่ยนการรักษา ปิดเหตุการณ์ และติดต่อฉุกเฉินยังต้องมีมนุษย์อนุมัติ</p>
        </div>
      </details>
    </section>

    <section className={styles.panel}>
      <div className={styles.cardHead}><div><h3 style={{ margin: 0 }}>รายการล่าสุดที่ AI เสนอให้ตรวจ</h3><p className={styles.muted}>แสดงเฉพาะงานที่ต้องให้บุคลากรพิจารณา รายละเอียดเทคนิคแยกไว้ด้านล่าง</p></div></div>
      {!reviewRuns.length ? <p className={styles.empty}>ยังไม่มีข้อเสนอใหม่จาก AI ไม่ได้หมายความว่าผู้ป่วยทุกคนปลอดภัย ให้ติดตามหน้าลำดับการดูแลและสถานะอุปกรณ์ร่วมด้วย</p> : <div className={styles.agentReviewList}>{reviewRuns.map((item) => <button key={item.id} onClick={() => openPatient(item.patient_id)}><div><b>{item.patient_id}</b><span>{decisions[item.decision] ?? 'เสนอให้ตรวจสอบ'}</span><small>{when(item.created_at)} · {reviewSummary(item)}</small></div><span>เปิดข้อมูลผู้ป่วย →</span></button>)}</div>}
    </section>

    <section className={styles.panel}><div className={styles.cardHead}><div><p className={styles.eyebrow}>DATASET → MODEL → RESULT</p><h3 style={{ margin: 0 }}>Dataset ถูกนำไปใช้อะไรจริง</h3><p className={styles.muted}>มีเพียงโมเดล “ใช้งานใน Monitor” ที่มีผลต่อข้อมูลสด ส่วนโมเดลวิจัยจะไม่ถูกเรียกอัตโนมัติ</p></div><button className={styles.primary} onClick={openEvidence}>ทดลองโมเดลกับข้อมูลกันไว้ →</button></div><div className={styles.datasetUseGrid}>
      <article data-tone="active">
        <span>ใช้งานใน Monitor</span>
        <h3>PhysioNet BIDMC HR / SpO₂ / RR (1 Hz)</h3>
        <p><b>Dataset ต้นทาง:</b> ข้อมูลจริง PhysioNet BIDMC (1 Hz) แบ่งกลุ่ม Train / Validation / Test ปราศจาก Data Leakage (ไม่รั่วไหลข้ามกลุ่ม)</p>
        <p><b>Model ทำงาน:</b> ใช้หน้าต่าง 60s พยากรณ์ล่วงหน้า 30 วินาที ด้วย Random Forest เทียบกับ Persistence Baseline และเลือก Abstain (งดทาย) ทันทีหากข้อมูลขาดช่วง</p>
        <p><b>ผลไปไหน:</b> กราฟผู้ป่วย → Agent → เสนอ Alert เมื่อเข้าเกณฑ์ (ไม่ตัดสินใจทางคลินิกแทนแพทย์)</p>
        <small>รอบที่โมเดลประเมินสำเร็จใน 1 ชม. {status?.last_hour.model_completed ?? 0}</small>
      </article>
      <article data-tone="pilot"><span>Shadow / เก็บ Ground Truth</span><h3>PMD Pressure Map</h3><p><b>Dataset สอน:</b> ท่าซ้าย ขวา และหงายจากแผ่นแรงกด 32×64</p><p><b>Model ทำ:</b> จำแนกท่าหรือ ABSTAIN และตรวจท่าเดิมนาน</p><p><b>ผลไปไหน:</b> สถานะข้างเตียง → งานตรวจ → บุคลากรยืนยันเฉลยจริง</p><small>รับ pressure map {bedside?.posture_observations ?? 0} · Ground Truth {bedside?.ground_truth_labels ?? 0}</small></article>
      <article data-tone="off"><span>ไม่ใช้กับข้อมูลสด</span><h3>Sepsis 2019 / ICU 2012</h3><p>เก็บไว้เป็นงานเปรียบเทียบวิจัยเท่านั้น เพราะ endpoint และช่วงข้อมูลไม่ตรงกับผู้ป่วยติดเตียงที่บ้าน</p><p><b>ผลไปไหน:</b> Research Lab เท่านั้น ไม่สร้าง Alert</p></article>
    </div></section>

    <section className={styles.panel}><h3 style={{ marginTop: 0 }}>ความพร้อมสำหรับดูแลผู้ป่วยติดเตียง</h3><div className={styles.readinessList}>
      <div><span className={styles.ready}>มีแล้ว</span><b>ติดตาม HR, SpO₂, RR และสร้างงานให้คนตรวจ</b></div>
      <div><span className={styles.ready}>มีแล้ว</span><b>ประวัติย้อนหลัง แผนดูแล บันทึกเหตุการณ์ และ Web Push</b></div>
      <div><span className={styles.pilot}>กำลังทดลอง</span><b>โมเดลท่าบนเตียงรับ pressure map ได้แล้ว แต่ยังไม่ได้รับรองกับเซนเซอร์จริง</b></div>
      <div><span className={styles.ready}>มีแล้ว</span><b>Device health: heartbeat แบตเตอรี่ สัญญาณ เซนเซอร์หลุด และการสอบเทียบ</b></div>
      <div><span className={styles.missing}>ยังขาด</span><b>Dataset ผู้สูงอายุ/ผู้ป่วยติดเตียงที่บ้านและการทดสอบทางคลินิก</b></div>
      <div><span className={styles.missing}>ยังขาด</span><b>การส่งต่อฉุกเฉินจริง SLA และการยืนยันว่ามีผู้รับผิดชอบ</b></div>
    </div></section>

    <section className={styles.panel}>
      <details className={styles.learnMoreDrawer}>
        <summary className={styles.learnMoreSummary}>
          <span>🔍 รายละเอียดสำหรับตรวจสอบระบบและอธิบายอาจารย์ · Audit Trace &amp; Model Registry (Learn More)</span>
          <span className={styles.learnMoreBadge}>Audit &amp; Registry</span>
        </summary>
        <div className={styles.learnMoreBody}>
          <p className={styles.muted} style={{ marginTop: 0 }}>ส่วนนี้เป็นหลักฐานทางเทคนิค ไม่จำเป็นสำหรับงานติดตามประจำวัน</p>
          <div className={styles.notice}>
            <b>หลักการ AI Evidence &amp; Clinical Transparency สำหรับกรรมการตรวจโปรเจ็กต์:</b>
            <ol style={{ margin: '8px 0 0 16px', padding: 0 }}>
              <li><b>ชุดข้อมูลจริงและการแบ่งกลุ่ม:</b> ใช้ PhysioNet BIDMC PPG and Respiration Dataset (1 Hz) แบ่งกลุ่ม Train / Validation / Test ตามรหัสผู้ป่วยอย่างเคร่งครัดโดยปราศจากการรั่วไหลของข้อมูล (Zero Data Leakage)</li>
              <li><b>การพยากรณ์ล่วงหน้า 30 วินาที &amp; Persistence Baseline:</b> สกัด Feature จากข้อมูลต่อเนื่อง 60 วินาที เพื่อพยากรณ์ค่าแนวโน้มล่วงหน้า 30 วินาที ด้วย Random Forest โดยวัดเทียบกับ Persistence Baseline (ค่าล่าสุดคงเดิม) เสมอ เพื่อพิสูจน์คุณค่าของโมเดลอย่างโปร่งใส</li>
              <li><b>การงดทาย (Abstain) เมื่อข้อมูลไม่สมบูรณ์:</b> เพื่อความปลอดภัยทางคลินิก (Clinical Safety First) หากข้อมูลขาดช่วง เซนเซอร์หลุด หรือไม่ผ่านการตรวจสอบคุณภาพ ระบบจะสั่งงดทาย (Abstain) ทันที ไม่เดาค่าหรือสร้างข้อมูลเท็จ</li>
            </ol>
          </div>
          <div className={styles.filters}>{runs.slice(0, 12).map((item) => <button key={item.id} className={`${styles.choice} ${item.id === run?.id ? styles.choiceActive : ""}`} onClick={() => setSelected(item.id)}>#{item.id} · {item.patient_id}</button>)}</div>
          {run && <><div className={styles.titleRow}><div><b>{decisions[run.decision] ?? run.decision}</b><p className={styles.muted}>{run.patient_id} · {run.source} · {run.model_version} · {when(run.created_at)}</p></div><button className={styles.link} onClick={() => openPatient(run.patient_id)}>เปิด {run.patient_id}</button></div><div className={styles.steps}>{run.steps.map((step) => <div className={styles.step} key={step.id}><span className={styles.stepNumber}>{step.sequence}</span><small>{agentLabels[step.agent_id] ?? step.agent_id}</small><b>{toolLabels[step.tool_name] ?? step.tool_name}</b><small>{step.status}</small><p>{stepSummary(step)}</p></div>)}</div></>}
          <details className={styles.learnMoreDrawer}>
            <summary className={styles.learnMoreSummary}>
              <span>📚 Dataset และ Model Registry ทั้งหมดในระบบ (Learn More)</span>
              <span className={styles.learnMoreBadge}>ดูตาราง Registry</span>
            </summary>
            <div className={styles.learnMoreBody}>
              <p className={styles.muted} style={{ marginTop: 0 }}>แยกโมเดลใช้งานจริงออกจากงานวิจัย ระบบไม่หยิบโมเดลวิจัยมาใช้เอง</p>
              <div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Dataset</th><th>บทบาท</th><th>ข้อจำกัด</th><th>แหล่งที่มา</th></tr></thead><tbody>{status?.datasets.map((dataset) => <tr key={dataset.id}><td>{dataset.name}</td><td>{dataset.role}</td><td>{dataset.fit}</td><td><a href={dataset.source} target="_blank" rel="noreferrer">แหล่งข้อมูล</a></td></tr>)}</tbody></table></div>
              <div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Model</th><th>สถานะ</th><th>ผลทดสอบ</th><th>ข้อจำกัด</th></tr></thead><tbody>{status?.models.map((model) => <tr key={model.id}><td>{model.id}</td><td>{model.status}</td><td>{model.metric}: {compact(model.result)}</td><td>{model.limitation}</td></tr>)}</tbody></table></div>
            </div>
          </details>
        </div>
      </details>
    </section>
  </>;
}
