"use client";

import { useEffect, useState } from "react";
import { Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import s from "./ResearchPanel.module.css";
import { metric, replayChart, vitalKeys, type Point, type Vital } from "./evidenceView";
import PosturePanel from "./PosturePanel";

type Status = { records: { id: string; samples: number }[]; metadata: { trained_at: string; splits: Record<string, string[]>; selected_forecast: Record<Vital, string>; test_selected_mae: Record<Vital, number>; test_persistence_mae: Record<Vital, number>; test_windows: number } };
type Evidence = { record_id: string; anchor: number; observed_until: number; anchor_second: number; target_second: number; input: Point[]; observed_after: Point[]; baseline: Point; evaluation_status: string; model_sha256: string; analysis: { status: string; forecast: Record<Vital, number> | null; anomaly_score?: number; is_anomaly: boolean }; feature_evidence: (Record<Vital, number> & { statistic: string })[]; comparison: Record<Vital, { actual: number; selected: number; baseline: number; selected_absolute_error: number; baseline_absolute_error: number }> | null };
const names: Record<Vital, string> = { heart_rate: "ชีพจร · bpm", spo2: "SpO₂ · %", respiratory_rate: "การหายใจ · ครั้ง/นาที" };
const evaluation: Record<string, string> = { WAITING_FOR_TARGET: "ยังไม่เปิดเผยผลจริงที่ +30 วินาที", EVALUATED: "ครบเวลาแล้ว — เปรียบเทียบกับค่าจริงได้", ABSTAIN: "งดพยากรณ์: ข้อมูลยังไม่ครบหรือไม่ผ่านคุณภาพ", TARGET_WINDOW_INVALID: "ข้อมูลช่วงเป้าหมายไม่ผ่านคุณภาพ — ไม่คำนวณความคลาดเคลื่อน", TARGET_OUTSIDE_RECORD: "จุดเป้าหมายอยู่นอกไฟล์ — ไม่มีผลจริงให้เปรียบเทียบ" };

export default function EvidencePanel() {
  const [tab, setTab] = useState("vitals");
  return <div className={s.root}><div className={s.actions} role="group" aria-label="หลักฐาน AI"><button aria-pressed={tab === "vitals"} onClick={() => setTab("vitals")}>01 · พยากรณ์สัญญาณชีพ</button><button aria-pressed={tab === "posture"} onClick={() => setTab("posture")}>02 · จำแนกท่าบนเตียง</button></div>{tab === "vitals" ? <VitalsEvidence /> : <PosturePanel />}</div>;
}

function VitalsEvidence() {
  const [status, setStatus] = useState<Status | null>(null);
  const [record, setRecord] = useState("");
  const [anchor, setAnchor] = useState(59);
  const [cursor, setCursor] = useState(59);
  const [playing, setPlaying] = useState(false);
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [error, setError] = useState("");
  const [vital, setVital] = useState<Vital>("heart_rate");
  useEffect(() => {
    const abort = new AbortController();
    fetch("/api/evidence/status", { signal: abort.signal }).then(async (r) => { if (!r.ok) throw new Error("ยังเปิดข้อมูล BIDMC ไม่ได้ กรุณาตรวจ Dataset และโมเดลที่ backend"); return r.json() as Promise<Status>; }).then((data) => { setStatus(data); setRecord(data.records[0]?.id ?? ""); }).catch((e) => { if (!abort.signal.aborted) setError(String(e.message)); });
    return () => abort.abort();
  }, []);
  useEffect(() => {
    if (!record) return;
    const abort = new AbortController();
    fetch(`/api/evidence/records/${record}?anchor=${anchor}&observed_until=${cursor}`, { signal: abort.signal }).then(async (r) => { if (!r.ok) throw new Error("โหลดหลักฐานไม่สำเร็จ ลองเลือกไฟล์ใหม่"); return r.json() as Promise<Evidence>; }).then((data) => { setEvidence(data); setError(""); }).catch((e) => { if (!abort.signal.aborted) setError(String(e.message)); });
    return () => abort.abort();
  }, [record, anchor, cursor]);
  const end = Math.min(anchor + 30, (status?.records.find((r) => r.id === record)?.samples ?? 1) - 1);
  useEffect(() => {
    if (!playing || cursor >= end) return;
    const timer = setTimeout(() => setCursor((value) => Math.min(end, value + 1)), 1000);
    return () => clearTimeout(timer);
  }, [playing, cursor, end]);
  const visible = evidence?.record_id === record && evidence.anchor === anchor && evidence.observed_until === cursor ? evidence : null;
  function reset(nextAnchor: number, nextRecord = record) { setPlaying(false); setEvidence(null); setAnchor(nextAnchor); setCursor(nextAnchor); setRecord(nextRecord); }
  return <>
    <section className={s.card}>
      <div className={s.eyebrow}>AI EVIDENCE TRANSPARENCY · 60S FEATURES → 30S FORECAST → ACTUAL COMPARISON</div>
      <h2>พิสูจน์ AI: พยากรณ์ล่วงหน้าก่อนรู้คำตอบจริง (Evidence Replay)</h2>
      <details className={s.learnMoreDrawer}>
        <summary className={s.learnMoreSummary}>
          <span>📖 ข้อมูลระเบียบวิธีวิจัยและหลักฐานความโปร่งใส (Learn More)</span>
          <span className={s.learnMoreBadge}>รายละเอียดระเบียบวิธี</span>
        </summary>
        <div className={s.learnMoreBody}>
          <p>
            <b>1) แหล่งข้อมูลจริงและการแบ่งกลุ่ม:</b> ข้อมูลสกัดจากชุดข้อมูลจริง <b>PhysioNet BIDMC (Sampling Rate 1 Hz)</b> โดยแบ่งกลุ่ม <b>Train / Validation / Test</b> ตามรหัสไฟล์ผู้ป่วยอย่างเด็ดขาด จึงมั่นใจได้ว่า <b>ไม่มีข้อมูลรั่วไหล (Zero Data Leakage)</b> ข้ามชุดทดลอง ไฟล์ที่ให้เลือกคือ Held-out Test Set ทั้งหมด และสามารถทดลองเลือกดูได้ทุกเคส ไม่ใช่เฉพาะเคสที่ทายถูก
          </p>
          <p>
            <b>2) เส้นพยากรณ์ล่วงหน้า 30 วินาที & Persistence Baseline:</b> ระบบนำข้อมูลสังเกตการณ์ย้อนหลัง 60 วินาที (-59s ถึง 0s) มาสกัด Features สถิติเพื่อพยากรณ์ค่าที่จุดเป้าหมายล่วงหน้า 30 วินาที (+30s Lookahead) ด้วยโมเดล <b>Random Forest</b> เทียบกับ <b>Persistence Baseline</b> (สมมติว่าค่าล่าสุดจะคงที่) เพื่อให้เห็นชัดเจนว่าโมเดลทำนายการเปลี่ยนแปลงได้ดีกว่าการถือค่าคงเดิมหรือไม่
          </p>
          <p>
            <b>3) การงดทาย (Abstain) เมื่อข้อมูลขาดช่วง:</b> ตามหลักความปลอดภัยทางคลินิก (Clinical Safety & Fail-Safe) หากเซนเซอร์หลุด สัญญาณรบกวน หรือข้อมูลขาดช่วงไม่ครบหน้าต่าง 60 วินาที ระบบจะเลือก <b>งดพยากรณ์ (Abstain)</b> ทันที ไม่เดาค่า ไม่แปลงค่าสูญหายเป็นศูนย์ เพื่อป้องกันการแจ้งเตือนผิดพลาด (False Alarm)
          </p>
        </div>
      </details>
      <div className={s.warning}>
        <b>คำเตือนทางคลินิก:</b> หน้านี้ไม่ใช่ข้อมูลสดของ 60 เตียง ไม่ส่งแจ้งเตือน และไม่ได้วินิจฉัยโรค การเล่นย้อนหลังแสดงการไหลของข้อมูล ไม่ใช่การทดลองทางคลินิก
      </div>
      {error && <p role="alert">{error}</p>}
      {status && <div className={s.layout}><label>ไฟล์ชุดทดสอบ<select value={record} onChange={(e) => reset(59, e.target.value)}>{status.records.map((r) => <option key={r.id} value={r.id}>{r.id} · {r.samples} จุด</option>)}</select></label><label>จุดที่หยุดรับข้อมูลเพื่อพยากรณ์: {anchor} วินาที<input aria-label="จุดพยากรณ์" type="range" min="0" max={(status.records.find((r) => r.id === record)?.samples ?? 1) - 1} value={anchor} onChange={(e) => reset(Number(e.target.value))} /></label></div>}
      <div className={s.actions}><button disabled={!visible || cursor >= end} onClick={() => setPlaying(!playing)}>{playing && cursor < end ? "หยุดชั่วคราว" : "▶ เล่นย้อนหลัง 1 วินาที/จุด"}</button><button disabled={!record || cursor >= end} onClick={() => { setPlaying(false); setCursor(end); }}>เปิดผลถึง +30 วินาที</button><button disabled={!record} onClick={() => reset(anchor)}>เริ่มจุดนี้ใหม่</button><span>เปิดผลจริงแล้ว +{cursor - anchor} วินาที</span></div>
    </section>
    {visible ? <>
      <section className={s.card}>
        <div className={s.header} style={{ marginBottom: 8 }}>
          <div>
            <h3>{evaluation[visible.evaluation_status] ?? visible.evaluation_status}</h3>
            <p style={{ margin: 0 }}>สถานะโมเดล: {visible.analysis.status} · วิธีที่เลือก: {status?.metadata.selected_forecast[vital]}</p>
          </div>
          <span className={`${s.statusPill} ${visible.evaluation_status === "ABSTAIN" || visible.analysis.status !== "READY" ? s.statusAbstain : visible.evaluation_status === "EVALUATED" ? "" : s.statusWarn}`}>
            {visible.evaluation_status === "ABSTAIN" ? "ABSTAIN · งดพยากรณ์" : visible.evaluation_status}
          </span>
        </div>

        <div className={s.summaryStrip}>
          <span>ไฟล์ชุดทดสอบ: <b>{visible.record_id}</b></span>
          <span>จุดตัดข้อมูล (Anchor): <b>{visible.anchor_second}s</b></span>
          <span>เป้าหมายพยากรณ์ (+30 วินาที): <b>{visible.target_second}s</b></span>
          <span>เปิดผลจริงถึง: <b>{cursor}s (+{cursor - anchor} วินาที)</b></span>
        </div>

        <label>ตัวแปรที่แสดง<select value={vital} onChange={(e) => setVital(e.target.value as Vital)}>{vitalKeys.map((key) => <option value={key} key={key}>{names[key]}</option>)}</select></label>
        <div className={s.chart}><ResponsiveContainer width="100%" height="100%"><LineChart data={replayChart(visible.input, visible.observed_after, visible.target_second, visible.analysis.forecast?.[vital] ?? null, visible.baseline[vital], vital)} margin={{ top: 15, right: 20, left: 0, bottom: 10 }}><XAxis dataKey="second" type="number" domain={["dataMin", "dataMax"]} unit="s" /><YAxis domain={["auto", "auto"]} width={50} /><Tooltip /><ReferenceLine x={visible.anchor_second} stroke="#666" label="ตัดข้อมูล" /><Line name="ค่าจริงที่เปิดแล้ว" type="linear" dataKey="actual" stroke="#176e53" dot={false} isAnimationActive={false} /><Line name="จุดพยากรณ์ +30s" dataKey="forecast" stroke="#8b57a0" strokeDasharray="5 5" connectNulls dot isAnimationActive={false} /><Line name="ใช้ค่าล่าสุดคงเดิม" dataKey="baseline" stroke="#b17820" strokeDasharray="3 4" connectNulls dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></div>
        <p className={s.muted}>
          <b>คำอธิบายเส้นกราฟ:</b> เขียว = ค่าจริงที่เปิดแล้ว (PhysioNet BIDMC 1 Hz) · ม่วง = จุดพยากรณ์ล่วงหน้าที่ +30s (Random Forest Forecast) · เหลือง = Persistence Baseline (ค่าล่าสุดคงเดิม) · เส้นประเป็นเพียงเส้นนำสายตาเชื่อมไปยังจุดเป้าหมาย +30s ไม่ใช่การพยากรณ์ทุกวินาที · หากข้อมูลขาดช่วงหรือไม่สมบูรณ์ ระบบจะแสดงสถานะงดพยากรณ์ (Abstain) และไม่แสดงจุดพยากรณ์
        </p>
        <div className={s.scroll}><table><caption>หลักฐานรายตัวแปร ณ จุดนี้</caption><thead><tr><th>ตัวแปร</th><th>ผลพยากรณ์</th><th>ค่าจริง +30s</th><th>ผิดพลาดโมเดล</th><th>ผิดพลาด baseline</th></tr></thead><tbody>{vitalKeys.map((key) => <tr key={key}><td>{names[key]}</td><td>{metric(visible.analysis.forecast?.[key])}</td><td>{metric(visible.comparison?.[key].actual)}</td><td>{metric(visible.comparison?.[key].selected_absolute_error)}</td><td>{metric(visible.comparison?.[key].baseline_absolute_error)}</td></tr>)}</tbody></table></div>
        <p>Isolation Forest: {visible.analysis.status !== "READY" ? "ยังประเมินไม่ได้" : visible.analysis.is_anomaly ? "พบรูปแบบต่างจากชุดฝึก" : "ยังไม่พบรูปแบบต่างจากชุดฝึก"} · score {metric(visible.analysis.anomaly_score, 4)} ไม่ใช่โอกาสเกิดโรค</p>
        <details className={s.learnMoreDrawer}>
          <summary className={s.learnMoreSummary}>
            <span>🔍 ดู input features 21 มิติ และแหล่งโมเดล (Learn More)</span>
            <span className={s.learnMoreBadge}>Features &amp; SHA-256</span>
          </summary>
          <div className={s.learnMoreBody}>
            <p className={s.muted} style={{ marginTop: 0 }}>สถิติเหล่านี้คือข้อมูลเข้า ไม่ใช่เหตุผลเชิงสาเหตุหรือ SHAP</p>
            <div className={s.scroll}><table><thead><tr><th>สถิติ</th>{vitalKeys.map((k) => <th key={k}>{names[k]}</th>)}</tr></thead><tbody>{visible.feature_evidence.map((row) => <tr key={row.statistic}><td>{row.statistic}</td>{vitalKeys.map((k) => <td key={k}>{metric(row[k], 3)}</td>)}</tr>)}</tbody></table></div>
            <p style={{ overflowWrap: "anywhere", marginBottom: 0 }}>Model SHA-256: {visible.model_sha256}</p>
          </div>
        </details>
        <a className={s.download} href={`/api/evidence/records/${record}/report?anchor=${anchor}&observed_until=${cursor}`}>ดาวน์โหลดหลักฐาน ณ จุดที่เปิดอยู่ · Text</a>
      </section>
    </> : record && !error ? <p role="status">กำลังคำนวณจากข้อมูลที่เลือก…</p> : null}
    {status && <section className={s.card}>
      <h3>ดูทั้งชุดทดสอบ ไม่ใช่เพียงเคสเดียว (Held-out Test Evaluation)</h3>
      <p>{status.metadata.test_windows} หน้าต่างจาก {status.records.length} ไฟล์ทดสอบ · วัดผลด้วย MAE (Mean Absolute Error) ยิ่งต่ำยิ่งดี · หน้าต่างสไลด์มีช่วงซ้อนทับกัน (Overlapping Windows)</p>
      <div className={s.scroll}><table><thead><tr><th>ตัวแปร</th><th>วิธีที่เลือกจาก validation</th><th>Test MAE</th><th>Baseline MAE</th></tr></thead><tbody>{vitalKeys.map((key) => <tr key={key}><td>{names[key]}</td><td>{status.metadata.selected_forecast[key]}</td><td>{metric(status.metadata.test_selected_mae[key], 4)}</td><td>{metric(status.metadata.test_persistence_mae[key], 4)}</td></tr>)}</tbody></table></div>
      <p className={s.warning}><b>หลักฐานความโปร่งใส:</b> โมเดล Random Forest ไม่จำเป็นต้องชนะ baseline ทุกตัว (เช่น SpO₂ ที่มีช่วงแกว่งสั้นๆ น้อย ค่าคงเดิมจึงแม่นยำมาก) ผลปัจจุบันยังไม่ใช่หลักฐานว่าใช้กับผู้สูงอายุที่บ้านได้แม่นยำ</p>
      <details className={s.learnMoreDrawer}>
        <summary className={s.learnMoreSummary}>
          <span>🗂️ การแบ่งกลุ่ม Train / Validation / Test (ปราศจาก Data Leakage · Learn More)</span>
          <span className={s.learnMoreBadge}>Disjoint Splits</span>
        </summary>
        <div className={s.learnMoreBody}>
          <p className={s.muted} style={{ marginTop: 0 }}>แยกผู้ป่วยตามรหัสไฟล์ชัดเจน ไม่ปะปนข้อมูลข้ามชุดฝึกสอนและชุดทดสอบ</p>
          {Object.entries(status.metadata.splits).map(([name, ids]) => <p key={name}><b>{name}:</b> {ids.join(", ")}</p>)}
        </div>
      </details>
    </section>}
  </>;
}
