"use client";

import { useEffect, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import s from "./ResearchPanel.module.css";

type Model = "logistic" | "hist_gradient_boosting" | "threshold_rule";
type Split = "test" | "external_B";
type Metrics = {
  hourly_average_precision: number | null; hourly_auroc: number | null; hourly_brier: number;
  hourly_positive_rate: number; event_sensitivity: number | null; alert_ppv: number | null;
  false_alerts_per_100_patient_hours: number; median_timely_lead_hours: number | null;
  coverage: number; missed_events: number; timely_alerts: number; false_alerts: number;
  event_sensitivity_ci95: number[] | null; patients: number; threshold: number;
};
type Report = {
  status: string; message?: string; run_id: string; notice: string; dataset: string; source: string;
  downloaded_records: number; publisher_records: number; selected_model: Model;
  splits: Record<string, { patients: number; events: number; eligible_hours: number }>;
  excluded_records: Record<string, number>; thresholds: Record<Model, number>;
  metrics: Record<Model, Record<Split | "validation", Metrics>>;
  protocol: Record<string, string>; limitations: string[]; license_note: string;
};
type CaseIndex = { id: string; site: string; split: Split; hours: number; outcome: string; event: boolean };
type Point = { hour: number; eligible: boolean; scores: Record<Model, number | null>;
  input_values: Record<string, number | null>; observed: Record<string, number | null>;
  input_age_hours: Record<string, number | null>; label: number };
type Case = { id: string; run_id: string; split: Split; site: string; onset_hour: number | null;
  timeline: Point[]; outcomes: Record<Model, { outcome: string; first_alert_hour: number | null; lead_hours: number | null }> };
const base = "/api/research/sepsis";
const models: Model[] = ["logistic", "hist_gradient_boosting", "threshold_rule"];
const names: Record<Model, string> = { logistic: "Logistic Regression", hist_gradient_boosting: "HistGradientBoosting", threshold_rule: "กฎตัวอย่าง (ไม่ใช่ NEWS2)" };
const outcomes: Record<string, string> = { all: "ทุกผลลัพธ์", timely_alert: "เตือนในช่วงเป้าหมาย", early_false_alert: "เตือนเร็วเกินช่วงเป้าหมาย", false_alert: "เตือนผิด (ไม่มีเหตุการณ์)", missed_event: "พลาดเหตุการณ์", no_alert_no_event: "ไม่เตือน / ไม่มีเหตุการณ์" };
const number = (n: number | null | undefined, digits = 3) => n == null ? "—" : n.toFixed(digits);
const percent = (n: number | null | undefined) => n == null ? "—" : (100 * n).toFixed(1) + "%";

async function getJson<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal, cache: "no-store" });
  if (!response.ok) throw new Error(response.status === 401 ? "กรุณาเข้าสู่ระบบบุคลากรอีกครั้ง" : "โหลดผลวิจัยไม่สำเร็จ กรุณาลองใหม่");
  return response.json() as Promise<T>;
}

export default function ResearchPanel() {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [split, setSplit] = useState<Split>("test");
  const [outcome, setOutcome] = useState("all");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [listing, setListing] = useState<{ total: number; cases: CaseIndex[] } | null>(null);
  const [caseId, setCaseId] = useState("");
  const [record, setRecord] = useState<Case | null>(null);
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [reveal, setReveal] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    getJson<Report>(base + "/status", controller.signal).then(setReport).catch((e: Error) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [revision]);

  useEffect(() => {
    if (report?.status !== "READY") return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      const query = new URLSearchParams({ split, outcome, search, offset: String(offset), limit: "25" });
      getJson<{ run_id: string; total: number; cases: CaseIndex[] }>(base + "/cases?" + query, controller.signal)
        .then((data) => {
          if (data.run_id !== report.run_id) throw new Error("มีผลเทรนชุดใหม่ กรุณากดโหลดผลใหม่");
          setListing(data);
        }).catch((e: Error) => { if (!controller.signal.aborted) setError(e.message); });
    }, 150);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [report, split, outcome, search, offset]);

  useEffect(() => {
    if (!caseId || !report) return;
    const controller = new AbortController();
    getJson<Case>(base + "/cases/" + caseId, controller.signal).then((data) => {
      if (data.run_id !== report.run_id) throw new Error("มีผลเทรนชุดใหม่ กรุณากดโหลดผลใหม่");
      setRecord(data);
    }).catch((e: Error) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [caseId, report]);

  useEffect(() => {
    if (!playing || !record) return;
    const timer = window.setInterval(() => setCursor((i) => Math.min(i + 1, record.timeline.length - 1)), 1000);
    return () => window.clearInterval(timer);
  }, [playing, record]);

  function resetCase() { setCaseId(""); setRecord(null); setCursor(0); setPlaying(false); setReveal(false); setError(""); }
  function changeSplit(value: Split) { setSplit(value); setOffset(0); setListing(null); resetCase(); }
  function selectCase(id: string) { resetCase(); setCaseId(id); }
  const point = record?.timeline[cursor];
  const currentRows = record?.timeline.slice(0, cursor + 1).map((row) => ({ hour: row.hour, ...row.scores })) ?? [];
  const selected = report?.selected_model;
  const firstProposal = selected ? record?.timeline.slice(0, cursor + 1).find((row) => row.scores[selected] !== null && row.scores[selected]! >= report!.thresholds[selected])?.hour : undefined;
  const scoreCeiling = Math.min(1, Math.max(.1, selected ? report!.thresholds[selected] : 0,
    ...currentRows.flatMap((row) => [row.logistic ?? 0, row.hist_gradient_boosting ?? 0])) * 1.2);

  return <section className={s.root} aria-label="AI Research Lab">
    <header className={s.header}><div><small className={s.eyebrow}>AI RESEARCH LAB · OFFLINE EVIDENCE</small><h2>เห็นผล AI จากข้อมูลจริง</h2><p>ทดสอบย้อนหลัง แยกจาก 60 เตียง · ไม่ส่งข้อมูลไป Gemini · ไม่สร้างคำสั่งรักษา</p></div><button onClick={() => { resetCase(); setReport(null); setListing(null); setRevision((n) => n + 1); }}>โหลดผลใหม่</button></header>
    <details className={s.learnMoreDrawer} role="note" aria-label="คำอธิบายการแยกส่วนโมเดลสำหรับแพทย์และผู้ตรวจประเมิน">
      <summary className={s.learnMoreSummary}>
        <span>🔬 ข้อมูลขอบเขตโมเดลและระเบียบวิธีวิจัย (Learn More)</span>
        <span className={s.learnMoreBadge}>รายละเอียดทางเทคนิค</span>
      </summary>
      <div className={s.learnMoreBody}>
        <small className={s.eyebrow}>CLINICAL &amp; EVALUATOR SCOPE · การแยกส่วนโมเดลอย่างชัดเจน</small>
        <div className={s.twoColumns}>
          <div><strong>1. โมเดลเฝ้าระวังสัญญาณชีพสด 1 Hz (PhysioNet BIDMC)</strong><p className={s.muted}>ทำงานบนกระแสข้อมูลสัญญาณชีพแบบต่อเนื่อง (HR, SpO₂, RR) สำหรับเฝ้าระวังและพยากรณ์แนวโน้มระยะสั้น (+30 วินาที) ในระบบมอนิเตอร์หอผู้ป่วย 60 เตียง</p></div>
          <div><strong>2. โมเดลวิจัยย้อนหลัง ICU Sepsis Benchmark</strong><p className={s.muted}>หน้านี้ประมวลผลข้อมูลย้อนหลังระดับรายชั่วโมงจาก PhysioNet Sepsis Challenge แบบออฟไลน์ เพื่อตรวจสอบความแม่นยำและข้อจำกัดทางสถิติ แยกขาดจากระบบเตือนภัยข้างเตียงและไม่มีผลต่อการสั่งการรักษาจริง</p></div>
        </div>
      </div>
    </details>
    {error && <p role="alert" className={s.warning}>{error}</p>}
    {!report ? <p role="status">กำลังโหลดหลักฐานการเทรน…</p> : report.status !== "READY" ? <div className={s.card}><h3>ยังไม่มีผลวิจัยพร้อมใช้งาน</h3><p>{report.message}</p><p>ไม่มีการสร้างคะแนนสมมติแทนผลเทรน</p><code>python -m ml_pipeline.download_sepsis2019 --per-site 2000<br />python -m ml_pipeline.train_sepsis2019</code><p>รันจากโฟลเดอร์ backend แล้วกดโหลดผลใหม่</p></div> : <>
      <div className={s.warning}>{report.notice}<br />คะแนนบนกราฟยังไม่ใช่เปอร์เซ็นต์ความเสี่ยงทางคลินิกที่ผ่านการสอบเทียบ<br /><b>ยังไม่พร้อมใช้แจ้งเตือนผู้ป่วยจริง — โปรดดูจำนวนเหตุการณ์ที่พลาดและผลข้ามโรงพยาบาล ไม่พิจารณา AUROC เพียงตัวเดียว</b></div>
      <div className={s.stats}>
        <article><small>ข้อมูลที่ใช้จริง</small><strong>{report.downloaded_records.toLocaleString()} ราย</strong><span>ชุดย่อยจาก {report.publisher_records.toLocaleString()} ราย</span></article>
        <article><small>ฝึก / ปรับเกณฑ์ / ทดสอบภายใน</small><strong>{report.splits.train.patients} / {report.splits.validation.patients} / {report.splits.test.patients}</strong><span>Site A แยกไฟล์ผู้ป่วย ไม่สุ่มแถวปะปน</span></article>
        <article><small>ทดสอบข้ามโรงพยาบาล</small><strong>{report.splits.external_B.patients} ราย</strong><span>Site B ไม่ใช้ฝึกหรือเลือก threshold</span></article>
      </div>
      <div className={s.card}>
        <div className={s.header}><div><h3>เปรียบเทียบผลบนชุดที่ไม่ใช้ฝึก</h3><p>เลือกโมเดลจาก validation: {names[report.selected_model]} · ไม่เลือกจากคะแนน test</p></div><a href={base + "/report"}>↓ หลักฐานผลทดสอบ .txt</a></div>
        <div className={s.actions}><button aria-pressed={split === "test"} onClick={() => changeSplit("test")}>Test · Site A</button><button aria-pressed={split === "external_B"} onClick={() => changeSplit("external_B")}>External · Site B</button></div>
        <div className={s.scroll}><table><thead><tr><th>วิธี</th><th>AP ↑</th><th>AUROC ↑</th><th>Brier ↓</th><th>ตรวจพบเหตุการณ์<br />[95% CI]</th><th>สัดส่วนเตือนถูก</th><th>เตือนผิด / 100 ชม.</th><th>เตือนก่อน (มัธยฐาน)</th></tr></thead><tbody>{models.map((model) => { const m = report.metrics[model][split]; return <tr key={model}><th>{names[model]}{model === selected && <small>เลือกจาก validation</small>}</th><td>{number(m.hourly_average_precision)}</td><td>{number(m.hourly_auroc)}</td><td>{number(m.hourly_brier)}</td><td>{percent(m.event_sensitivity)}<small>{m.event_sensitivity_ci95 ? `[${m.event_sensitivity_ci95.map(percent).join("–")}]` : "—"}</small></td><td>{percent(m.alert_ppv)}</td><td>{number(m.false_alerts_per_100_patient_hours)}</td><td>{number(m.median_timely_lead_hours, 1)} ชม.</td></tr>; })}</tbody></table></div>
        <p className={s.muted}>AP / AUROC / Brier วัดระดับรายชั่วโมง ส่วนการเตือนวัดครั้งแรกต่อผู้ป่วย · ยิ่ง AP/AUROC สูงยิ่งดี, Brier ต่ำยิ่งดี ไม่ใช่ Accuracy</p>
        <p>ชุดนี้มี label บวก {percent(report.metrics[report.selected_model][split].hourly_positive_rate)} ของชั่วโมงที่ประเมินได้ · Coverage {percent(report.metrics[report.selected_model][split].coverage)} · พลาด {report.metrics[report.selected_model][split].missed_events} เหตุการณ์</p>
      </div>

      <div className={s.layout}>
        <aside className={s.card}><h3>เลือกเคสจริงในชุดทดสอบ</h3><p>ไม่ใช่ ID ของทะเบียน A001–C020</p>
          <label>ค้นหา Research ID<input value={search} placeholder="เช่น A-p000123" onChange={(e) => { setSearch(e.target.value); setOffset(0); setListing(null); resetCase(); }} /></label>
          <label>ผลของโมเดลที่เลือก<select value={outcome} onChange={(e) => { setOutcome(e.target.value); setOffset(0); setListing(null); resetCase(); }}>{Object.entries(outcomes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <p>{listing ? `${listing.total} เคสตรงเงื่อนไข` : "กำลังค้นหา…"}</p>
          <div className={s.cases}>{listing?.cases.map((item) => <button key={item.id} aria-pressed={caseId === item.id} onClick={() => selectCase(item.id)}><b>{item.id}</b><small>{outcomes[item.outcome]}</small><small>{item.hours} ชั่วโมงก่อน onset / จบข้อมูล</small></button>)}</div>
          {listing?.total === 0 && <p>ไม่มีเคสในกลุ่มนี้</p>}
          <div className={s.actions}><button disabled={!offset || !listing} onClick={() => { setOffset(offset - 25); setListing(null); }}>ก่อนหน้า</button><button disabled={!listing || offset + 25 >= listing.total} onClick={() => { setOffset(offset + 25); setListing(null); }}>ถัดไป</button></div>
        </aside>
        <article className={s.card}>{!record || !point ? <div className={s.empty}>{caseId ? "กำลังโหลดเคส…" : "เลือกเคสเพื่อดู AI ประเมินทีละชั่วโมง"}</div> : <>
          <div className={s.header}>
            <div>
              <h3>{record.id}</h3>
              <p>ICU ชั่วโมง {point.hour} · {point.eligible ? "ข้อมูลถึงเกณฑ์ประเมิน" : "ABSTAIN — ข้อมูลไม่พอ"}</p>
            </div>
            <div className={s.actions} style={{ margin: 0 }}>
              <span className={`${s.statusPill} ${!point.eligible ? s.statusAbstain : ""}`}>
                {point.eligible ? `ประเมินได้ · ชั่วโมง ${point.hour}` : "ABSTAIN · ข้อมูลไม่พอ"}
              </span>
              <button onClick={() => { setCursor(0); setPlaying(false); }}>เริ่มใหม่</button>
            </div>
          </div>
          <div className={s.actions}><button disabled={cursor === record.timeline.length - 1} onClick={() => setPlaying(!playing)}>{playing && cursor < record.timeline.length - 1 ? "หยุด" : "▶ เล่นย้อนหลัง"}</button><span>1 วินาทีหน้าจอ = 1 ชั่วโมงใน Dataset (ไม่ใช่เวลาจริง)</span></div>
          <label>ชั่วโมงที่ทบทวน<input aria-label="ชั่วโมงที่ทบทวน" type="range" min="0" max={record.timeline.length - 1} value={cursor} onChange={(e) => { setCursor(Number(e.target.value)); setPlaying(false); }} /></label>
          <div className={s.summaryStrip}>
            <span>คะแนน {names[report.selected_model]}: <b>{point.scores[report.selected_model] === null ? "ABSTAIN" : number(point.scores[report.selected_model], 4)}</b></span>
            <span>เกณฑ์เตือน (Threshold): <b>{number(report.thresholds[report.selected_model], 4)}</b></span>
            <span>ข้อเสนอแรกที่เกิดแล้ว: <b>{firstProposal === undefined ? "ยังไม่มี" : `ชั่วโมง ${firstProposal}`}</b></span>
            <span>กฎตัวอย่าง ณ ชั่วโมงนี้: <b>{point.scores.threshold_rule === null ? "ABSTAIN" : point.scores.threshold_rule === 1 ? "เข้าเงื่อนไข (1)" : "ไม่เข้าเงื่อนไข (0)"}</b></span>
          </div>
          <div className={s.chart}><ResponsiveContainer width="100%" height="100%">
            <LineChart data={currentRows} margin={{ top: 15, right: 30, bottom: 5, left: 0 }}>
              <CartesianGrid stroke="#dfe7df" strokeDasharray="3 3" />
              <XAxis dataKey="hour" type="number" domain={[record.timeline[0].hour, Math.max(record.timeline[record.timeline.length - 1].hour, record.onset_hour ?? 0)]} stroke="#627468" />
              <YAxis domain={[0, scoreCeiling]} tickFormatter={(value: number) => value.toFixed(2)} stroke="#627468" />
              <Tooltip contentStyle={{ background: "#ffffff", borderColor: "#becfc5", color: "#20392e" }} /><Legend />
              {reveal && record.onset_hour !== null && <ReferenceArea x1={record.onset_hour - 6} x2={record.onset_hour} fill="#a16b12" fillOpacity={.1} />}
              {reveal && record.onset_hour !== null && <ReferenceLine x={record.onset_hour} stroke="#a16b12" label={{ value: "onset", position: "insideTopLeft", fill: "#76561f" }} />}
              {report.thresholds[report.selected_model] <= 1 && <ReferenceLine y={report.thresholds[report.selected_model]} stroke="#627468" strokeDasharray="3 3" label={{ value: "threshold", position: "insideTopLeft", fill: "#465a4d" }} />}
              {(["logistic", "hist_gradient_boosting"] as Model[]).map((model, index) => <Line key={model} dataKey={model} name={names[model]} stroke={["#2563a6", "#176e53"][index]} strokeWidth={2} strokeDasharray={index ? "6 3" : undefined} dot={false} connectNulls={false} isAnimationActive={false} />)}
            </LineChart>
          </ResponsiveContainer></div>
          <p className={s.muted}>กราฟแสดงคะแนน ML (แกน Y ปรับตามค่าที่เห็น) ส่วนกฎตัวอย่างเป็นค่า 0/1 จึงแสดงแยกด้านบน · สีเหลืองเมื่อเปิดเฉลย = ช่วงเป้าหมาย 6 ชั่วโมง</p>
          <label className={s.check}><input type="checkbox" checked={reveal} onChange={(e) => setReveal(e.target.checked)} />เปิดเฉลยย้อนหลัง (ไม่ใช่ข้อมูลที่ AI รู้ในขณะนั้น)</label>
          {reveal && <div className={s.warning}>Inferred onset: {record.onset_hour ?? "ไม่มีใน label"}{record.onset_hour !== null ? " ชม. (เริ่ม label บวก + 6 ชม.)" : ""}<ul>{models.map((model) => <li key={model}>{names[model]}: {outcomes[record.outcomes[model].outcome]} · เตือนครั้งแรก {record.outcomes[model].first_alert_hour ?? "—"}</li>)}</ul></div>}
          <details className={s.learnMoreDrawer}>
            <summary className={s.learnMoreSummary}>
              <span>📋 หลักฐาน ณ ชั่วโมง {point.hour} · ตารางข้อมูลเข้าและอายุข้อมูล (Learn More)</span>
              <span className={s.learnMoreBadge}>ดูข้อมูลเข้า</span>
            </summary>
            <div className={s.learnMoreBody}>
              <p className={s.muted} style={{ marginTop: 0 }}>ค่าด้านล่างเป็นข้อมูลเข้า ไม่ใช่คำอธิบายเชิงสาเหตุของโมเดล</p>
              <div className={s.scroll}><table><thead><tr><th>ตัวแปร</th><th>วัดใหม่ชั่วโมงนี้</th><th>ค่าที่โมเดลใช้</th><th>อายุข้อมูล (ชม.)</th></tr></thead><tbody>{Object.entries(point.input_values).map(([key, value]) => <tr key={key}><th>{key}</th><td>{number(point.observed[key], 2)}</td><td>{number(value, 2)}</td><td>{value === null ? "ขาด / หมดอายุ" : number(point.input_age_hours[key], 0)}</td></tr>)}</tbody></table></div>
            </div>
          </details>
          <a className={s.download} href={`${base}/cases/${record.id}/summary?hour=${point.hour}`}>↓ ร่างสรุปส่งต่อเพื่อทบทวน ณ ชั่วโมงนี้ (.txt)</a><p className={s.muted}>สรุปจากข้อมูลถึงชั่วโมงที่เลือกเท่านั้น มี source hour และรายการข้อมูลขาด ไม่ใช้เฉลยจากอนาคต</p>
        </>}</article>
      </div>
      <details className={s.learnMoreDrawer}>
        <summary className={s.learnMoreSummary}>
          <span>📚 วิธีทดลอง ข้อจำกัด และที่มาของชุดข้อมูล Sepsis 2019 (สำหรับอธิบายงานวิจัย · Learn More)</span>
          <span className={s.learnMoreBadge}>Protocol &amp; Limitations</span>
        </summary>
        <div className={s.learnMoreBody}>
          <p><a href={report.source} target="_blank" rel="noreferrer">{report.dataset}</a> · Run {report.run_id}</p>
          <p>Excluded: {Object.entries(report.excluded_records).map(([key, value]) => `${key}: ${value}`).join("; ")}</p>
          <dl>{Object.entries(report.protocol).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>
          <ul>{report.limitations.map((value) => <li key={value}>{value}</li>)}</ul>
          <p>{report.license_note}</p>
        </div>
      </details>
    </>}
  </section>;
}
