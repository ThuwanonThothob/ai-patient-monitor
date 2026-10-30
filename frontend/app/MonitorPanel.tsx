"use client";

import { useEffect, useState, type FormEvent } from "react";
import { isFreshReading } from "./monitorView";
import { safeAnalysis, sourceLabel } from "./patientView";
import { usePatientResource } from './usePatientResource';
import s from "./Ward.module.css";

export type MonitorData = {
  patient_id: string; status: string; timestamp?: number; source?: string; source_record?: string; simulation_state?: string;
  heart_rate?: number; spo2?: number; respiratory_rate?: number;
  history?: { timestamp?: number; time?: string; heart_rate?: number | null; spo2?: number | null; respiratory_rate?: number | null }[];
  analysis: { status: string; history_points?: number; summary?: string; evaluated_at?: number; prediction_at?: number;
    forecast?: { heart_rate: number; spo2: number; respiratory_rate: number } | null;
    forecast_methods?: Record<string, string>; is_anomaly?: boolean };
};
type Worker = { status: string; fresh_beds: number; total_beds?: number; ingest_mode: string; error?: string; model: {
  recordings?: number; usable_windows?: number; test_windows?: number;
  test_selected_mae?: Record<string, number>; test_persistence_mae?: Record<string, number>;
  selected_forecast?: Record<string, string>;
} };

export function scoreNews2RR(rr?: number | null): number | null {
  if (typeof rr !== "number" || !Number.isFinite(rr)) return null;
  const v = Math.round(rr);
  if (v <= 8) return 3;
  if (v <= 11) return 1;
  if (v <= 20) return 0;
  if (v <= 24) return 2;
  return 3;
}

export function scoreNews2SpO2(spo2?: number | null): number | null {
  if (typeof spo2 !== "number" || !Number.isFinite(spo2)) return null;
  const v = Math.round(spo2);
  if (v <= 91) return 3;
  if (v <= 93) return 2;
  if (v <= 95) return 1;
  return 0;
}

export function scoreNews2HR(hr?: number | null): number | null {
  if (typeof hr !== "number" || !Number.isFinite(hr)) return null;
  const v = Math.round(hr);
  if (v <= 40) return 3;
  if (v <= 50) return 1;
  if (v <= 90) return 0;
  if (v <= 110) return 1;
  if (v <= 130) return 2;
  return 3;
}

export function calculateModifiedNews2(state: MonitorData | undefined, fresh: boolean) {
  if (!fresh) {
    return {
      ready: false,
      total: null as number | null,
      hrScore: null as number | null,
      spo2Score: null as number | null,
      rrScore: null as number | null,
      hasRedScore: false,
      tier: "stale" as const,
      riskLabel: "งดคำนวณคะแนน (ข้อมูลขาดช่วงหรือเก่าเกิน 15 วินาที)",
      badgeClass: s.badgeWarning,
    };
  }
  const hrScore = scoreNews2HR(state?.heart_rate);
  const spo2Score = scoreNews2SpO2(state?.spo2);
  const rrScore = scoreNews2RR(state?.respiratory_rate);
  if (hrScore === null || spo2Score === null || rrScore === null) {
    return {
      ready: false,
      total: null as number | null,
      hrScore,
      spo2Score,
      rrScore,
      hasRedScore: false,
      tier: "incomplete" as const,
      riskLabel: "รอข้อมูลครบ 3 ตัวแปรเพื่อคำนวณคะแนนรวม",
      badgeClass: s.badgeWarning,
    };
  }
  const total = hrScore + spo2Score + rrScore;
  const hasRedScore = hrScore === 3 || spo2Score === 3 || rrScore === 3;
  if (total >= 5 || hasRedScore) {
    return {
      ready: true,
      total,
      hrScore,
      spo2Score,
      rrScore,
      hasRedScore,
      tier: "high" as const,
      riskLabel: ">=5 หรือมีตัวแปรใดได้ 3 คะแนน: เร่งตรวจสอบทางคลินิก",
      badgeClass: s.badgeCritical,
    };
  }
  if (total >= 3) {
    return {
      ready: true,
      total,
      hrScore,
      spo2Score,
      rrScore,
      hasRedScore,
      tier: "medium" as const,
      riskLabel: "3-4 คะแนน: ควรประเมินซ้ำ",
      badgeClass: s.badgeWarning,
    };
  }
  return {
    ready: true,
    total,
    hrScore,
    spo2Score,
    rrScore,
    hasRedScore,
    tier: "low" as const,
    riskLabel: "0-2 คะแนน: เฝ้าระวังตามรอบ",
    badgeClass: s.badgeGood,
  };
}

export function PatientAnalysis({ state }: { state?: MonitorData }) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => { const timer = setInterval(() => setNow(Date.now() / 1000), 1000); return () => clearInterval(timer); }, []);
  const fresh = isFreshReading(state, now);
  const analysis = safeAnalysis(state, now, fresh) ?? { ...state?.analysis, forecast: null, status: !fresh ? "STALE_DATA" : state?.analysis?.status === "READY" ? "STALE_ANALYSIS" : state?.analysis?.status };
  const isReady = analysis?.status === "READY" && Boolean(analysis.forecast);
  const messages: Record<string, string> = {
    INSUFFICIENT_DATA: "กำลังสะสมข้อมูลต่อเนื่อง 60 วินาที (1 Hz) ก่อนเริ่มพยากรณ์ล่วงหน้า",
    STALE_DATA: "ข้อมูลขาดช่วงหรือเก่าแล้ว ระงับผลคาดการณ์ (Abstention)",
    STALE_ANALYSIS: "ผลวิเคราะห์เก่าแล้ว รอการประมวลผลรอบใหม่",
    SAMPLING_MISMATCH: "ต้องมีข้อมูลทุก 1 วินาทีต่อเนื่องครบ 60 จุด จึงจะพยากรณ์",
    MODEL_NOT_TRAINED: "ยังไม่มีไฟล์โมเดล กรุณารันชุดเตรียมข้อมูลและเทรน",
    INVALID_DATA: "ข้อมูลไม่ผ่านการตรวจสอบคุณภาพ จึงระงับผลคาดการณ์",
  };
  const forecastItems = isReady && analysis.forecast ? [
    {
      key: "heart_rate",
      label: "HR คาดการณ์ · bpm",
      predicted: analysis.forecast.heart_rate,
      current: fresh && typeof state?.heart_rate === "number" && Number.isFinite(state.heart_rate) ? state.heart_rate : null,
      method: analysis.forecast_methods?.heart_rate ?? "Random Forest (60s)",
      score: scoreNews2HR(analysis.forecast.heart_rate),
    },
    {
      key: "spo2",
      label: "SpO2 คาดการณ์ · %",
      predicted: analysis.forecast.spo2,
      current: fresh && typeof state?.spo2 === "number" && Number.isFinite(state.spo2) ? state.spo2 : null,
      method: analysis.forecast_methods?.spo2 ?? "Persistence Baseline",
      score: scoreNews2SpO2(analysis.forecast.spo2),
    },
    {
      key: "respiratory_rate",
      label: "RR คาดการณ์ · ครั้ง/นาที",
      predicted: analysis.forecast.respiratory_rate,
      current: fresh && typeof state?.respiratory_rate === "number" && Number.isFinite(state.respiratory_rate) ? state.respiratory_rate : null,
      method: analysis.forecast_methods?.respiratory_rate ?? "Random Forest (60s)",
      score: scoreNews2RR(analysis.forecast.respiratory_rate),
    },
  ] : [];

  return <section className="monitor-panel">
    <div className="monitor-heading">
      <div>
        <span className="portal-kicker">LOCAL AI · 30-SECOND FORECAST</span>
        <h3>{isReady ? "วิเคราะห์แนวโน้มล่วงหน้า 30 วินาทีโดยโมเดลที่เทรนแล้ว" : "สถานะการวิเคราะห์และพยากรณ์ 30 วินาที"}</h3>
      </div>
      <span className={`monitor-status ${isReady ? "is-live" : "is-stale"}`}>
        <i />
        {isReady ? "AI READY · พยากรณ์ +30 วินาที" : `Abstention (ระงับผลคาดการณ์) · ${analysis?.status ?? "WAITING"}`}
      </span>
    </div>

    <p>{isReady ? analysis.summary : messages[analysis?.status ?? "INSUFFICIENT_DATA"] ?? "รอข้อมูลต่อเนื่องเพื่อประมวลผล"}</p>

    {!isReady && (
      <div className={s.notice} role="status" style={{ marginTop: 10, marginBottom: 12 }}>
        <b>สถานะ Abstention (ระงับผลคาดการณ์ชั่วคราว):</b> ระบบไม่แสดงตัวเลขพยากรณ์เมื่อสัญญาณชีพขาดช่วง เก่าเกินเกณฑ์ หรือยังสะสมหน้าต่างข้อมูล 60 วินาทีไม่ครบ เพื่อป้องกันการเข้าใจผิดทางคลินิก
      </div>
    )}

    {isReady && analysis.forecast && (
      <div className="patient-metrics">
        {forecastItems.map((item) => {
          const delta = item.current !== null ? Number((item.predicted - item.current).toFixed(1)) : null;
          const deltaLabel = delta === null ? null : delta > 0 ? `+${delta}` : `${delta}`;
          return (
            <div key={item.key}>
              <small>{item.label}</small>
              <strong>{item.predicted}</strong>
              <small style={{ display: "flex", justifyContent: "space-between", gap: 6, flexWrap: "wrap" }}>
                <span>{deltaLabel !== null ? `เทียบค่าล่าสุด: ${deltaLabel}` : "คาดการณ์ที่ +30s"}</span>
                {item.score !== null && <b>NEWS2 +{item.score}</b>}
              </small>
            </div>
          );
        })}
      </div>
    )}

    <small>{sourceLabel(state?.source ?? '')} · {state?.source_record ?? "—"} · {analysis?.status ?? "WAITING"}</small>
    {analysis?.evaluated_at && <small>วิเคราะห์เมื่อ {new Date(analysis.evaluated_at * 1000).toLocaleTimeString("th-TH")} · คาดการณ์ ณ {analysis.prediction_at ? new Date(analysis.prediction_at * 1000).toLocaleTimeString("th-TH") : "—"}</small>}

    <details className={s.learnMoreDrawer}>
      <summary className={s.learnMoreSummary}>
        <span>🧠 รายละเอียดโมเดลพยากรณ์ 30 วินาที และเงื่อนไข Abstention (Learn More)</span>
        <span className={s.learnMoreBadge}>วิธีคำนวณของ AI</span>
      </summary>
      <div className={s.learnMoreBody}>
        <small>Isolation Forest ตรวจรูปแบบต่างจากชุดฝึก ไม่ใช่การวินิจฉัยโรค · SpO2 ใช้ persistence baseline ตามผล validation</small>
        <small>ระบบใช้หน้าต่างข้อมูลจริงต่อเนื่อง 60 วินาที (1 Hz) เพื่อพยากรณ์ค่าที่ +30 วินาทีข้างหน้า หากข้อมูลขาดหายแม้แต่จุดเดียวจะเข้าสู่โหมด Abstention ทันที</small>
      </div>
    </details>
  </section>;
}

export function LatestVitals({ state }: { state?: MonitorData }) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => { const timer = setInterval(() => setNow(Date.now() / 1000), 1000); return () => clearInterval(timer); }, []);
  const fresh = isFreshReading(state, now);
  const news2 = calculateModifiedNews2(state, fresh);
  const metrics = [
    { short: 'HR', label: 'ชีพจร', unit: 'bpm', value: state?.heart_rate, tone: 'heart', score: news2.hrScore, normalHint: 'เกณฑ์ปกติ 51–90' },
    { short: 'SpO₂', label: 'ออกซิเจนในเลือด', unit: '%', value: state?.spo2, tone: 'oxygen', score: news2.spo2Score, normalHint: 'เกณฑ์ปกติ ≥96%' },
    { short: 'RR', label: 'อัตราการหายใจ', unit: 'ครั้ง/นาที', value: state?.respiratory_rate, tone: 'breath', score: news2.rrScore, normalHint: 'เกณฑ์ปกติ 12–20' },
  ];
  return <section className="monitor-panel current-vitals" aria-label="สัญญาณชีพปัจจุบัน">
    <div className="monitor-heading">
      <div>
        <span className="portal-kicker">LIVE MEASUREMENT · 3-SECOND CLINICAL TRIAGE</span>
        <h3>สัญญาณชีพล่าสุด</h3>
      </div>
      <span className={`monitor-status ${fresh ? 'is-live' : 'is-stale'}`}>
        <i />
        {fresh ? "ข้อมูลล่าสุด" : "รอข้อมูลใหม่ / ข้อมูลขาดช่วง"}
      </span>
    </div>

    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexWrap: "wrap",
        gap: "8px 14px",
        padding: "12px 16px",
        marginTop: 12,
        borderRadius: 12,
        border: "1px solid #d5e4dc",
        background: news2.tier === "high" ? "#fff5f6" : news2.tier === "medium" ? "#fffbf0" : "#f4faf7",
      }}
      aria-label="สรุปคะแนน Modified NEWS2"
    >
      <div>
        <strong style={{ fontSize: 14.5, color: "#0f2922" }}>
          Modified NEWS2 (3 ตัวแปร): {news2.ready ? `${news2.total} / 9 คะแนน` : "รอข้อมูลสด"}
        </strong>
        <small style={{ display: "block", marginTop: 2 }}>
          คะแนนย่อยจาก 3 สัญญาณชีพ (HR, SpO₂, RR) · ยังไม่รวมความดัน อุณหภูมิ และระดับความรู้สึกตัว
        </small>
      </div>
      <span className={`${s.deviceFactBadge} ${news2.badgeClass}`} style={{ fontSize: 12, padding: "5px 10px", borderRadius: 999 }}>
        {news2.riskLabel}
      </span>
    </div>

    <div className="patient-metrics">
      {metrics.map((metric) => (
        <div className={`vital-current-card ${metric.tone}`} key={metric.short}>
          <div>
            <span>{metric.short}</span>
            <small>{metric.label}</small>
            <small style={{ fontSize: 11, opacity: 0.85 }}>
              {metric.normalHint}
              {fresh && metric.score !== null ? ` · NEWS2 +${metric.score}` : ""}
            </small>
          </div>
          <strong>
            {fresh && typeof metric.value === "number" && Number.isFinite(metric.value) ? metric.value : "—"}
            <small>{metric.unit}</small>
          </strong>
        </div>
      ))}
    </div>

    <div className="reading-meta">
      <span>วัดเมื่อ <b>{state?.timestamp ? new Date(state.timestamp * 1000).toLocaleString("th-TH", { hour12: false }) : "ยังไม่มีข้อมูล"}</b></span>
      <span>แหล่งข้อมูล <b>{sourceLabel(state?.source ?? '')}</b></span>
    </div>
    <small>เพื่อความปลอดภัย ระบบซ่อนค่าที่เก่าเกิน 15 วินาที และไม่แทนค่าที่หายไปด้วยศูนย์</small>

    <details className={s.learnMoreDrawer}>
      <summary className={s.learnMoreSummary}>
        <span>📋 เกณฑ์การให้คะแนน Modified NEWS2 Sub-score 3 ตัวแปร (Learn More)</span>
        <span className={s.learnMoreBadge}>เกณฑ์มาตรฐาน</span>
      </summary>
      <div className={s.learnMoreBody}>
        <small>
          <b>เกณฑ์คะแนนย่อยรายตัวแปร (Royal College of Physicians NEWS2):</b>
        </small>
        <small>• <b>RR (ครั้ง/นาที):</b> &lt;=8 (3 คะแนน), 9–11 (1 คะแนน), 12–20 (0 คะแนน), 21–24 (2 คะแนน), &gt;=25 (3 คะแนน)</small>
        <small>• <b>SpO₂ (%):</b> &lt;=91 (3 คะแนน), 92–93 (2 คะแนน), 94–95 (1 คะแนน), &gt;=96 (0 คะแนน)</small>
        <small>• <b>HR (bpm):</b> &lt;=40 (3 คะแนน), 41–50 (1 คะแนน), 51–90 (0 คะแนน), 91–110 (1 คะแนน), 111–130 (2 คะแนน), &gt;=131 (3 คะแนน)</small>
        <small>
          <b>การแปลผลระดับความเสี่ยงย่อย:</b> 0-2 คะแนน: เฝ้าระวังตามรอบ · 3-4 คะแนน: ควรประเมินซ้ำ · &gt;=5 หรือมีตัวแปรใดได้ 3 คะแนน: เร่งตรวจสอบทางคลินิก (ต้องวัดความดันโลหิต อุณหภูมิ และประเมินความรู้สึกตัวเพิ่มเติมเสมอ)
        </small>
      </div>
    </details>
  </section>;
}

export default function MonitorPanel({ openPatient, compact = false }: { openPatient: (id: string) => void; compact?: boolean }) {
  const { data: state, error, refresh } = usePatientResource<Worker>('/api/monitor/status', 5000);
  const [id, setId] = useState("");
  function find(e: FormEvent) { e.preventDefault(); openPatient(id.trim().toUpperCase()); }
  return <section className="monitor-panel"><div className="monitor-heading"><div><span className="portal-kicker">AUTONOMOUS MONITOR</span>
    <h2>ติดตามอัตโนมัติด้วยโมเดล AI</h2></div><span className={`monitor-status${state?.status === 'RUNNING' ? '' : ' is-stale'}`}>{state?.status === "RUNNING" ? "กำลังทำงาน" : state?.status === "STOPPED" ? "หยุดทำงาน" : state?.status ?? "กำลังตรวจการเชื่อมต่อ"} · {state?.fresh_beds ?? '—'}/{state?.total_beds ?? '—'} คน</span></div>
    {error && <p className="patient-warning" role="alert">{error} <button onClick={refresh}>ลองใหม่</button></p>}
    <p className="monitor-description">{state?.ingest_mode === "replay" ? "กำลังเล่นข้อมูล BIDMC ตามเวลา · ทะเบียนผู้ป่วยจำลอง" : state?.ingest_mode === "mqtt" ? "รับข้อมูลจาก MQTT" : "รอสถานะแหล่งข้อมูล"} · ทำงานเมื่อ backend เปิดอยู่</p>
    <form className="monitor-search" onSubmit={find}><label htmlFor="quick-id">เปิดข้อมูลจาก ID</label><input id="quick-id" value={id} onChange={(e) => setId(e.target.value.toUpperCase())} placeholder="A001 หรือ TEST_P" maxLength={64} autoCapitalize="characters" spellCheck={false} required /><button disabled={!id.trim()}>เรียกดูผล AI</button></form>
    <details className={s.learnMoreDrawer} open={!compact}>
      <summary className={s.learnMoreSummary}>
        <span>📊 ที่มาของข้อมูลและผลทดสอบโมเดล (Learn More)</span>
        <span className={s.learnMoreBadge}>MAE &amp; Baseline</span>
      </summary>
      <div className={s.learnMoreBody}>
        <p>BIDMC · {state?.model.recordings ?? "—"} recordings · {state?.model.usable_windows ?? "—"} หน้าต่างข้อมูล</p>
        <div className="monitor-table"><table><caption>ชุดทดสอบแยก recording จากชุดฝึก · MAE ยิ่งต่ำยิ่งดี</caption><thead><tr><th>ตัวแปร</th><th>วิธีที่เลือก</th><th>MAE ชุดทดสอบ</th><th>baseline</th></tr></thead><tbody>{[["heart_rate", "HR · bpm"], ["spo2", "SpO2 · จุดเปอร์เซ็นต์"], ["respiratory_rate", "RR · ครั้ง/นาที"]].map(([key, label]) => <tr key={key}><td>{label}</td><td>{state?.model.selected_forecast?.[key] ?? "—"}</td><td>{state?.model.test_selected_mae?.[key] ?? "—"}</td><td>{state?.model.test_persistence_mae?.[key] ?? "—"}</td></tr>)}</tbody></table></div>
        <small>ยังไม่เหนือกว่า baseline ทุกตัวและยังไม่ผ่าน clinical validation · ไม่มี label สำหรับวัดความแม่นยำการตรวจโรค</small>
        <small>ทะเบียนสาธิตใช้สัญญาณชุดทดสอบวนซ้ำ ส่วน TEST_P ใช้เซนเซอร์บ้านจำลอง แสดงเฉพาะผู้ป่วยตามสิทธิ์บัญชี โรคและประวัติในทะเบียนไม่ใช่ label ของ BIDMC</small>
      </div>
    </details>
  </section>;
}
