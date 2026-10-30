"use client";

import { useEffect, useState } from "react";
import { metric } from "./evidenceView";
import s from "./ResearchPanel.module.css";

type Metrics = { accuracy: number; macro_f1: number; samples: number; confusion_matrix: number[][]; per_subject_accuracy: Record<string, number>; per_class: Record<string, { precision: number; recall: number; "f1-score": number; support: number }> };
type Report = { status: string; message?: string; run_id: string; selected_model: string; classes: string[]; split_counts: Record<string, number>; splits: Record<string, number[]>; metrics: Record<string, { validation: Metrics; test: Metrics }>; coverage: number; accepted_accuracy: number | null; excluded_frames: number; protocol_revision: string; source: string; license: string; model_sha256: string };
type Case = { ref: number; run_id: string; subject: number; prediction: string; decision: string; label?: string; probabilities: Record<string, number>; pressure_map: number[][]; baseline: string; source_file?: string };
const labels: Record<string, string> = { left: "ตะแคงซ้าย", right: "ตะแคงขวา", supine: "นอนหงาย", ABSTAIN: "งดสรุปท่า" };

export default function PosturePanel() {
  const [report, setReport] = useState<Report | null>(null);
  const [cases, setCases] = useState<{ ref: number; subject: number }[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [outcome, setOutcome] = useState("all");
  const [reveal, setReveal] = useState(false);
  const [data, setData] = useState<Case | null>(null);
  const [error, setError] = useState("");
  const [loadedOutcome, setLoadedOutcome] = useState<string | null>(null);
  useEffect(() => {
    const abort = new AbortController();
    fetch("/api/research/posture/status", { signal: abort.signal }).then(async (r) => { if (!r.ok) throw new Error("โหลดสถานะ PMD ไม่สำเร็จ"); return r.json() as Promise<Report>; }).then(setReport).catch((e) => { if (!abort.signal.aborted) setError(String(e.message)); });
    return () => abort.abort();
  }, []);
  useEffect(() => {
    if (report?.status !== "READY") return;
    const abort = new AbortController();
    fetch(`/api/research/posture/cases?outcome=${outcome}`, { signal: abort.signal }).then(async (r) => { if (!r.ok) throw new Error("โหลดรายการ PMD ไม่สำเร็จ"); return r.json(); }).then((result) => {
      if (result.run_id !== report.run_id) throw new Error("โมเดลเปลี่ยนระหว่างเปิดหน้า กรุณาโหลดหน้าเว็บใหม่");
      setCases(result.cases); setSelected(result.cases[0]?.ref ?? null); setData(null); setReveal(false); setError(""); setLoadedOutcome(outcome);
    }).catch((e) => { if (!abort.signal.aborted) setError(String(e.message)); });
    return () => abort.abort();
  }, [report, outcome]);
  useEffect(() => {
    if (selected === null) return;
    const abort = new AbortController();
    fetch(`/api/research/posture/cases/${selected}?reveal=${reveal}`, { signal: abort.signal }).then(async (r) => { if (!r.ok) throw new Error("อ่านหลักฐานเคสไม่สำเร็จ"); return r.json() as Promise<Case>; }).then((result) => {
      if (result.run_id !== report?.run_id) throw new Error("โมเดลเปลี่ยนระหว่างเปิดหน้า กรุณาโหลดหน้าเว็บใหม่");
      setData(result); setError("");
    }).catch((e) => { if (!abort.signal.aborted) setError(String(e.message)); });
    return () => abort.abort();
  }, [selected, reveal, report?.run_id]);
  const visible = data?.ref === selected && data?.run_id === report?.run_id && Boolean(data.label) === reveal ? data : null;
  const caseListPending = loadedOutcome !== outcome;
  const metrics = report?.status === "READY" ? report.metrics[report.selected_model].test : null;
  const max = visible ? Math.max(...visible.pressure_map.flat()) : 1;
  return <>
    <section className={s.card}>
      <div className={s.eyebrow}>PRESSURE MAP → 128 FEATURES → TRAINED CLASSIFIER → HUMAN LABEL</div>
      <h2>AI เห็นท่าบนเตียงจากรูปแบบแรงกด</h2>
      <p>ทดลองด้วย Pressure Map Dataset (PMD) จาก PhysioNet · 3 ท่ามาตรฐาน · เทียบ Logistic Regression, Random Forest และ baseline ที่ทายท่าพบบ่อยที่สุดในชุดฝึก</p>
      <details className={s.learnMoreDrawer}>
        <summary className={s.learnMoreSummary}>
          <span>🛏️ ระเบียบวิธีสกัด 128 Spatial Features และเกณฑ์งดสรุปท่า (Learn More)</span>
          <span className={s.learnMoreBadge}>PMD 32×64 Pipeline</span>
        </summary>
        <div className={s.learnMoreBody}>
          <p>
            <b>1) การสกัดคุณลักษณะเชิงพื้นที่ (Spatial Pooling):</b> แผ่นวัดแรงกดขนาด 32×64 จุด ถูกย่อเป็นกริด 8×16 (128 มิติ) และหารด้วยผลรวมแรงกดทั้งหมด (Normalized by Sum) เพื่อให้โมเดลจำแนกรูปร่างการกระจายน้ำหนักโดยไม่ยึดติดกับน้ำหนักตัวดิบของแต่ละบุคคล
          </p>
          <p>
            <b>2) การแยกกลุ่มผู้เข้าร่วม (Subject-Disjoint Split):</b> แบ่งผู้เข้าร่วม 13 คนออกเป็น Train (7 คน), Validation (3 คน) และ Test (3 คน) โดยไม่ปะปนเฟรมของคนเดียวกันข้ามกลุ่ม และตั้งเกณฑ์งดสรุปท่า (Abstain) เมื่อความน่าจะเป็นสูงสุดต่ำกว่า 0.60
          </p>
        </div>
      </details>
      <p className={s.warning}>เฉพาะงานวิจัย: ผู้เข้าร่วม 13 คน อายุ 19–34 ปี ไม่ใช่กลุ่มผู้สูงอายุติดเตียง ไม่มีป้ายกำกับแผลกดทับ และยังไม่ได้เชื่อมแผ่นเซนเซอร์ที่บ้าน ห้ามตีความผลนี้เป็นการวินิจฉัยหรือตารางพลิกตัว</p>
      {error && <p role="alert">{error}</p>}
      {report?.status !== "READY" && <p role="status">{report?.message ?? "กำลังโหลดผลเทรน…"}</p>}
    </section>
    {report?.status === "READY" && metrics && <>
      <div className={s.stats}><article><span>โมเดลเลือกจาก validation macro-F1</span><strong>{report.selected_model === "logistic" ? "Logistic Regression" : "Random Forest"}</strong><small>ไม่ได้เลือกจากคะแนน test</small></article><article><span>Test macro-F1 · ทุกเฟรมก่อนงดสรุป</span><strong>{metric(metrics.macro_f1, 3)}</strong><small>Accuracy {metric(metrics.accuracy * 100, 1)}% · {metrics.samples} เฟรมจาก 3 คน</small></article><article><span>Coverage หลังใช้ cutoff 0.60</span><strong>{metric(report.coverage * 100, 1)}%</strong><small>Accuracy เฉพาะที่รับผล {report.accepted_accuracy == null ? "—" : metric(report.accepted_accuracy * 100, 1) + "%"} · ไม่ใช่ความมั่นใจทางคลินิก</small></article></div>
      <div className={s.layout}>
        <section className={s.card}><h3>ลองดูเคสที่โมเดลไม่เคยฝึก</h3><label>ตัวกรองย้อนหลัง<select value={outcome} onChange={(e) => { setOutcome(e.target.value); setLoadedOutcome(null); setSelected(null); setData(null); setCases([]); }}><option value="all">ทั้งหมด · ซ่อนเฉลย</option><option value="correct">รับผลและทายถูก</option><option value="incorrect">รับผลแต่ทายผิด</option><option value="abstained">งดสรุปท่า</option></select></label><p className={s.muted}>ตัวกรองถูก/ผิดใช้เฉลยย้อนหลังเพื่อวิเคราะห์ข้อผิดพลาด ไม่ใช่การทดสอบแบบไม่รู้คำตอบ</p><label>เฟรมทดสอบ<select disabled={caseListPending || !cases.length} value={selected ?? ""} onChange={(e) => { setSelected(Number(e.target.value)); setReveal(false); setData(null); }}>{!cases.length && <option value="">{caseListPending ? "กำลังโหลดรายการ…" : "ไม่มีเคสในกลุ่มนี้"}</option>}{cases.map((c) => <option key={c.ref} value={c.ref}>เคส {c.ref + 1} · ผู้เข้าร่วม S{c.subject}</option>)}</select></label><p className={s.muted}>เฟรมในท่าเดียวกันมีความสัมพันธ์กัน แต่ละเคสไม่ใช่ผู้ป่วยคนใหม่</p></section>
        <section className={s.card}>{visible ? <>
          <div className={s.header} style={{ marginBottom: 8 }}>
            <div>
              <h3>ผล: {labels[visible.decision]}</h3>
              <p style={{ margin: 0 }}>Baseline: {labels[visible.baseline]} · ผู้เข้าร่วม S{visible.subject}</p>
            </div>
            <span className={`${s.statusPill} ${visible.decision === "ABSTAIN" ? s.statusAbstain : ""}`}>
              {visible.decision === "ABSTAIN" ? "ABSTAIN · งดสรุปท่า" : `โมเดลสรุป: ${labels[visible.decision]}`}
            </span>
          </div>
          <div className={s.pressure}>
            <div className={s.pressureMeta}>
              <span>◀ ด้านศีรษะ (Head)</span>
              <span>ตารางเซนเซอร์แรงกด 32 แถว × 64 คอลัมน์</span>
              <span>ด้านปลายเท้า (Foot) ▶</span>
            </div>
            <svg viewBox="0 0 64 32" role="img" aria-label={`แผนที่แรงกด 32 แถว 64 คอลัมน์ ผู้เข้าร่วม S${visible.subject}`} shapeRendering="crispEdges">{visible.pressure_map.flatMap((row, y) => row.map((value, x) => <rect key={`${x}-${y}`} x={x} y={y} width="1" height="1" fill={`hsl(${220 - 200 * value / max} 76% ${96 - 48 * value / max}%)`} />))}</svg>
            <div className={s.pressureScale}>
              <span>0 (แรงกดต่ำ)</span>
              <div className={s.pressureScaleBar} />
              <span>สูงสุดในเฟรม {metric(max, 0)} raw counts</span>
            </div>
          </div>
          <p className={s.muted}>สีอ่อน = แรงกดดิบต่ำ · สีเข้ม/ส้ม = สูง · สเกลปรับตามเฟรม 0–{metric(max, 0)} raw counts ไม่ใช่ mmHg หรือระดับเสี่ยงแผลกดทับ</p>
          <div className={s.scroll}><table><thead><tr><th>ท่า</th><th>คะแนนโมเดล (ยังไม่สอบเทียบ)</th></tr></thead><tbody>{Object.entries(visible.probabilities).map(([key, value]) => <tr key={key}><td><b>{labels[key]}</b></td><td><span className={s.probTrack}><span className={s.probFill} style={{ width: `${Math.min(100, Math.max(0, value * 100))}%` }} /></span>{metric(value * 100, 1)}%</td></tr>)}</tbody></table></div>
          <div className={s.actions}><button onClick={() => { setData(null); setReveal(!reveal); }}>{reveal ? "ซ่อนเฉลย" : "เปิดเฉลยจากผู้เก็บ Dataset"}</button></div>
          {visible.label && <p role="status">เฉลย: <b>{labels[visible.label]}</b> · {visible.prediction === visible.label ? "โมเดลทายถูก" : "โมเดลทายผิด"}{visible.decision === "ABSTAIN" ? " (แต่ระบบงดรับผลเพราะคะแนนต่ำ)" : ""}<small>{visible.source_file}</small></p>}
        </> : <p role="status">{error ? "ยังแสดงเคสไม่ได้ กรุณาตรวจข้อความด้านบน" : caseListPending ? "กำลังโหลดรายการ…" : selected === null ? "ไม่มีเคสในกลุ่มนี้" : "กำลังโหลดแผนที่แรงกด…"}</p>}</section>
      </div>
      <section className={s.card}>
        <h3>หลักฐานเปรียบเทียบโมเดล</h3>
        <div className={s.scroll}><table><thead><tr><th>โมเดล</th><th>Validation macro-F1</th><th>Test macro-F1</th><th>Test accuracy</th></tr></thead><tbody>{Object.entries(report.metrics).map(([name, values]) => <tr key={name}><td>{name}{name === report.selected_model ? " · เลือกใช้" : ""}</td><td>{metric(values.validation.macro_f1, 3)}</td><td>{metric(values.test.macro_f1, 3)}</td><td>{metric(values.test.accuracy * 100, 1)}%</td></tr>)}</tbody></table></div>
        <h3 style={{ marginTop: 24 }}>Confusion matrix · แถว = เฉลย / คอลัมน์ = คำทำนาย</h3>
        <div className={s.scroll}><table><thead><tr><th>จำนวนเฟรม</th>{report.classes.map((c) => <th key={c}>{labels[c]}</th>)}</tr></thead><tbody>{metrics.confusion_matrix.map((row, index) => <tr key={index}><th>{labels[report.classes[index]]}</th>{row.map((n, j) => <td key={j}>{n}</td>)}</tr>)}</tbody></table></div>
        <p>Test รายคน: {Object.entries(metrics.per_subject_accuracy).map(([id, score]) => `${id} ${metric(score * 100, 1)}%`).join(" · ")}</p>
        <details className={s.learnMoreDrawer}>
          <summary className={s.learnMoreSummary}>
            <span>📋 ที่มา การแบ่งข้อมูล และข้อจำกัดของชุดข้อมูล PMD (Learn More)</span>
            <span className={s.learnMoreBadge}>Model SHA-256 &amp; Splits</span>
          </summary>
          <div className={s.learnMoreBody}>
            <p>ใช้เฉพาะ Experiment I ท่า 1, 2, 3 รวม 39 ไฟล์ · ลดการสุ่มซ้ำโดยใช้ทุกเฟรมที่ 5 · pooling 8×16 / normalize ด้วยผลรวม · เฟรมที่ไม่ผ่านคุณภาพ {report.excluded_frames}</p>
            {Object.entries(report.splits).map(([name, ids]) => <p key={name}>{name}: {ids.map((id) => `S${id}`).join(", ")} · {report.split_counts[name]} เฟรม</p>)}
            <p>แก้ importer หลังการทดลองแรกเพราะค่าดิบเกิน 1,000 ไม่ได้หมายความว่าไฟล์เสีย จึงถือผลเป็น exploratory และยังต้องมีชุดทดสอบใหม่ก่อนอ้างความแม่นยำสุดท้าย</p>
            <p>ไม่มีคลาสเตียงว่าง ตกเตียง หรือแผลกดทับ ข้อมูลคนละท่าเป็นการทดลองแยก ไม่ใช่เหตุการณ์พลิกตัวต่อเนื่อง</p>
            <p><a href={report.source} target="_blank" rel="noreferrer">Dataset ต้นฉบับและเอกสารกำกับ</a> · {report.license} · Pouyan et al. (2017)</p>
            <p style={{ overflowWrap: "anywhere" }}>Run {report.run_id}<br />Model SHA-256: {report.model_sha256}</p>
          </div>
        </details>
        <a href="/api/research/posture/report" className={s.download}>ดาวน์โหลดผลทดลอง · Text</a>
      </section>
    </>}
  </>;
}
