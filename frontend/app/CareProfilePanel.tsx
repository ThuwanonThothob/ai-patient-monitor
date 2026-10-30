"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { LineChart, Line, ReferenceArea, ReferenceLine, ResponsiveContainer, XAxis, YAxis, Tooltip } from "recharts";
import { careTime, careVitals, careVitalLabels, formRanges, type CareVital } from "./careView";
import { metric } from "./evidenceView";
import s from "./ResearchPanel.module.css";

type Content = {
  conditions: string;
  medications: string;
  allergies: string;
  limitations: string;
  caregiver: string;
  care_notes: string;
  use_reference: boolean;
  reference_minutes: number;
  ranges: Partial<Record<CareVital, { low: number; high: number }>>;
};
type Version = {
  version: number;
  state: string;
  content: Content;
  saved_at: number;
  saved_by: string;
  reviewed_at: number | null;
  reviewed_by: string | null;
  reference: { status: string; start: number; end: number; expires_at: number; sample_count: number } | null;
};
type Comparison = {
  status: string;
  profile_version?: number;
  reference_status: string;
  ranges: Partial<Record<CareVital, { value: number; low: number; high: number; outside: boolean }>>;
  reference: Partial<Record<CareVital, { value: number; median: number; difference: number; p05: number; p95: number; outside_sample_band: boolean }>>;
};
type Profile = {
  patient_id: string;
  version: number;
  latest: Version | null;
  active: Version | null;
  history: Version[];
  registry_condition: string;
  comparison: Comparison;
  recent_readings: ({ timestamp: number } & Record<CareVital, number>)[];
};

const empty: Content = {
  conditions: "",
  medications: "",
  allergies: "",
  limitations: "",
  caregiver: "",
  care_notes: "",
  ranges: {},
  use_reference: false,
  reference_minutes: 5,
};

const stateLabels: Record<string, string> = {
  DRAFT: "รอตรวจยืนยัน",
  ACTIVE: "ฉบับที่ยืนยันแล้ว",
  SUPERSEDED: "ฉบับก่อนหน้า",
  PAUSED: "พักใช้งาน",
};

const statusLabels: Record<string, string> = {
  READY: "พร้อมเปรียบเทียบ",
  NO_REVIEWED_PROFILE: "ยังไม่มีโปรไฟล์ยืนยัน",
  NO_READING: "ยังไม่มีข้อมูลวัด",
  STALE_READING: "ค่าที่วัดเก่าแล้ว — งดเปรียบเทียบ",
  READING_BEFORE_REVIEW: "รอค่าที่วัดหลังยืนยันโปรไฟล์",
  INVALID_READING: "ข้อมูลวัดไม่ผ่านคุณภาพ",
  UNKNOWN_SOURCE: "ไม่ทราบแหล่งการวัด",
  NOT_CONFIGURED: "ไม่ได้เปิดช่วงอ้างอิง",
  INSUFFICIENT_DATA: "ข้อมูลอ้างอิงไม่พอ ต้องมีอย่างน้อย 60 snapshot ต่อเนื่อง",
  SOURCE_MIXED_OR_UNKNOWN: "แหล่งข้อมูลผสม/ไม่ชัดเจน",
  REPLAY_SEGMENT_CHANGED: "ข้อมูล replay เปลี่ยนรอบหรือไม่มีแหล่งกำกับ",
  DATA_GAPS: "ข้อมูลอ้างอิงขาดช่วง",
  EXPIRED: "ช่วงอ้างอิงหมดอายุ ต้องให้คนทบทวนใหม่",
  READING_OVERLAPS_REFERENCE: "รอค่าที่วัดหลังช่วงอ้างอิง",
  SOURCE_CHANGED: "แหล่ง/รอบข้อมูลเปลี่ยน — ไม่เปรียบเทียบข้ามแหล่ง",
};

export default function CareProfilePanel({ patientId }: { patientId: string }) {
  const [data, setData] = useState<Profile | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const mounted = useRef(true);

  const load = useCallback(async () => {
    const r = await fetch(`/api/care/patients/${patientId}/profile`);
    if (!r.ok) throw new Error("โหลดโปรไฟล์ไม่ได้ กรุณาลองใหม่");
    const result = await r.json() as Profile;
    if (mounted.current) {
      setData(result);
      setConfirmed(false);
    }
  }, [patientId]);

  useEffect(() => {
    mounted.current = true;
    void load().catch((e) => {
      if (mounted.current) setError(e.message);
    });
    return () => {
      mounted.current = false;
    };
  }, [load]);

  async function mutate(path: string, method: string, body: unknown) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const r = await fetch(`/api/care/patients/${patientId}/${path}`, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const result = await r.json();
      if (!r.ok) {
        throw new Error(
          typeof result.detail === "string"
            ? result.detail
            : "ข้อมูลโปรไฟล์ไม่ถูกต้อง กรุณาตรวจขอบเขตและความยาวข้อความ"
        );
      }
      await load();
    } catch (e) {
      if (mounted.current) setError(e instanceof Error ? e.message : "บันทึกไม่สำเร็จ");
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const content = {
        conditions: form.get("conditions"),
        medications: form.get("medications"),
        allergies: form.get("allergies"),
        limitations: form.get("limitations"),
        caregiver: form.get("caregiver"),
        care_notes: form.get("care_notes"),
        ranges: formRanges(form),
        use_reference: form.get("use_reference") === "on",
        reference_minutes: Number(form.get("reference_minutes")),
      };
      void mutate("profile", "POST", { expected_version: data?.version ?? 0, content });
    } catch (e) {
      setError(e instanceof Error ? e.message : "ตรวจข้อมูลอีกครั้ง");
    }
  }

  const content = data?.latest?.content ?? empty;
  const hasDraft = data?.latest?.state === "DRAFT";

  return (
    <>
      <section className={s.card}>
        <div className={s.header} style={{ marginBottom: 10 }}>
          <div>
            <div className={s.eyebrow}>PERSONAL CARE PROFILE · HUMAN REVIEW</div>
            <h2>ข้อมูลการดูแล · {patientId}</h2>
          </div>
          <button
            disabled={busy}
            onClick={() => {
              setError("");
              void load().catch((e) => setError(e.message));
            }}
          >
            โหลดโปรไฟล์ล่าสุด
          </button>
        </div>

        {data && (
          <div className={s.stats} style={{ margin: "10px 0 14px" }}>
            <article style={{ padding: "12px 16px", background: data.active ? "#f2f9f5" : "#f8faf8", borderColor: data.active ? "#b7dcd0" : "#dfe7df" }}>
              <span>สถานะฉบับที่ยืนยันแล้ว (Active)</span>
              <strong style={{ fontSize: 18, margin: "4px 0" }}>
                {data.active ? `🟢 v${data.active.version} · ยืนยันแล้ว` : "⚪ ยังไม่มีฉบับที่ยืนยันแล้ว"}
              </strong>
              <small>{data.active ? `ยืนยันโดย ${data.active.reviewed_by} · ${careTime(data.active.reviewed_at!)}` : "ต้องสร้างร่างและกดยืนยันก่อนเริ่มเปรียบเทียบ"}</small>
            </article>
            <article style={{ padding: "12px 16px", background: hasDraft ? "#fff9eb" : "#f8faf8", borderColor: hasDraft ? "#e8d4ad" : "#dfe7df" }}>
              <span>สถานะฉบับร่าง (Draft)</span>
              <strong style={{ fontSize: 18, margin: "4px 0", color: hasDraft ? "#76561f" : "#20392e" }}>
                {hasDraft ? `📝 ร่าง v${data.latest!.version} รอยืนยัน` : "✔️ ไม่มีฉบับร่างค้างตรวจ"}
              </strong>
              <small>{hasDraft ? `บันทึกโดย ${data.latest!.saved_by} · ${careTime(data.latest!.saved_at)}` : "ข้อมูลล่าสุดตรงกับฉบับที่ตรวจสอบแล้ว"}</small>
            </article>
            <article style={{ padding: "12px 16px" }}>
              <span>สถานะการเปรียบเทียบรายบุคคล</span>
              <strong style={{ fontSize: 18, margin: "4px 0" }}>
                {statusLabels[data.comparison.status] ?? data.comparison.status}
              </strong>
              <small>ช่วงอ้างอิง: {statusLabels[data.comparison.reference_status] ?? data.comparison.reference_status}</small>
            </article>
          </div>
        )}

        <details className={s.learnMoreDrawer}>
          <summary className={s.learnMoreSummary}>
            <span>ℹ️ ขอบเขตการใช้งานโปรไฟล์และการคุ้มครองความปลอดภัยทางคลินิก (Learn More)</span>
            <span className={s.learnMoreBadge}>ดูรายละเอียด</span>
          </summary>
          <div className={s.learnMoreBody}>
            <p className={s.muted}>
              บันทึกบริบทและขอบเขตที่ผู้ดูแลกำหนด แยกจากทะเบียนสังเคราะห์ ไม่เลือกยาและไม่กำหนดเกณฑ์ตามชื่อโรคให้เอง
            </p>
            <p className={s.warning} style={{ marginBottom: 0 }}>
              ใช้เปรียบเทียบในหน้าจอและร่างรายงานเท่านั้น ไม่เปลี่ยนกฎแจ้งเตือนเดิม ไม่ลดระดับเร่งด่วน และไม่ส่งข้อมูลโปรไฟล์เข้า Gemini
            </p>
          </div>
        </details>

        {error && <p role="alert" className={s.warning} style={{ marginTop: 12, marginBottom: 0 }}>{error}</p>}
      </section>

      {!data ? (
        <p role="status">กำลังโหลดโปรไฟล์…</p>
      ) : (
        <div className={s.twoColumns}>
          <section className={s.card}>
            <h3>ร่างข้อมูลฉบับใหม่</h3>
            <p className={s.muted}>
              โรคในทะเบียนสังเคราะห์: <b>{data.registry_condition}</b> — ไม่ถูกนำมาเติมเป็นประวัติที่ยืนยันแล้วโดยอัตโนมัติ
            </p>
            <form key={`${patientId}-${data.version}`} onSubmit={save}>
              <fieldset className={s.fieldset} style={{ marginTop: 10 }}>
                <legend>1. ข้อมูลคลินิกและข้อควรระวัง</legend>
                {([
                  ["conditions", "โรค/ภาวะที่ผู้ดูแลบันทึก", 1500],
                  ["medications", "ยาที่มีการบันทึกไว้ (ไม่ใช่ใบสั่งยา)", 1500],
                  ["allergies", "ประวัติแพ้ที่บันทึกไว้", 1000],
                  ["limitations", "ข้อจำกัดและสิ่งที่ต้องระวัง", 1500],
                  ["care_notes", "หมายเหตุการดูแล", 2000],
                ] as const).map(([key, label, max]) => (
                  <label key={key}>
                    {label}
                    <textarea
                      name={key}
                      maxLength={max}
                      rows={2}
                      defaultValue={content[key]}
                      placeholder="ยังไม่ทราบให้เว้นว่าง ไม่ได้แปลว่าไม่มี"
                    />
                  </label>
                ))}
                <label>
                  ป้ายชื่อผู้ดูแลหลัก
                  <input
                    name="caregiver"
                    maxLength={150}
                    defaultValue={content.caregiver}
                    placeholder="ชื่อทีมสาธิต ไม่ใช่บัญชีผู้รับแจ้งเตือน"
                  />
                </label>
              </fieldset>

              <fieldset className={s.fieldset}>
                <legend>2. ขอบเขตสำหรับทบทวนรายคนและช่วงค่าอ้างอิง</legend>
                <p className={s.muted} style={{ marginTop: 0 }}>
                  เว้นว่างทั้งคู่หากยังไม่มีเกณฑ์ที่กำหนด ค่าเหล่านี้ไม่ใช่ข้อแนะนำทางการแพทย์จากระบบ
                </p>
                {careVitals.map((key) => (
                  <div key={key} className={s.rangeRow} style={{ marginBottom: 8 }}>
                    <b>{careVitalLabels[key]}</b>
                    <label style={{ margin: 0 }}>
                      ต่ำ
                      <input
                        aria-label={`${careVitalLabels[key]} ขอบเขตต่ำ`}
                        name={key + "_low"}
                        type="number"
                        step="0.1"
                        min="0.1"
                        max={key === "heart_rate" ? 250 : key === "spo2" ? 100 : 80}
                        defaultValue={content.ranges[key]?.low ?? ""}
                      />
                    </label>
                    <label style={{ margin: 0 }}>
                      สูง
                      <input
                        aria-label={`${careVitalLabels[key]} ขอบเขตสูง`}
                        name={key + "_high"}
                        type="number"
                        step="0.1"
                        min="0.1"
                        max={key === "heart_rate" ? 250 : key === "spo2" ? 100 : 80}
                        defaultValue={content.ranges[key]?.high ?? ""}
                      />
                    </label>
                  </div>
                ))}

                <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid #dfe7df" }}>
                  <label style={{ margin: "6px 0" }}>
                    <input name="use_reference" type="checkbox" defaultChecked={content.use_reference} />{" "}
                    สร้างช่วงอ้างอิงจากข้อมูลก่อนเวลายืนยันฉบับนี้
                  </label>
                  <label style={{ margin: "6px 0" }}>
                    ย้อนหลังเป็นนาที
                    <input
                      name="reference_minutes"
                      type="number"
                      min="5"
                      max="1440"
                      step="1"
                      defaultValue={content.reference_minutes}
                      required
                    />
                  </label>
                </div>
              </fieldset>

              <button
                type="submit"
                disabled={busy}
                style={{ width: "100%", fontWeight: 700, background: "#176e53", color: "#fff", borderColor: "#176e53" }}
              >
                บันทึกร่างโปรไฟล์
              </button>

              <details className={s.learnMoreDrawer}>
                <summary className={s.learnMoreSummary}>
                  <span>📐 เงื่อนไขการคำนวณช่วงอ้างอิง 60 Snapshot และการแสดงผลฝั่งผู้ป่วย (Learn More)</span>
                  <span className={s.learnMoreBadge}>ดูเงื่อนไข</span>
                </summary>
                <div className={s.learnMoreBody}>
                  <p className={s.muted}>
                    ต้องมี 60 snapshot ที่ผ่านคุณภาพและต่อเนื่อง ไม่ผสมแหล่ง/รอบ replay; แช่แข็งค่ามัธยฐานและช่วงเปอร์เซ็นไทล์ 5–95 ไม่เรียนรู้เอง และหมดอายุใน 24 ชั่วโมง นี่คือเงื่อนไขซอฟต์แวร์สาธิต ไม่ใช่เกณฑ์ภาวะปกติทางคลินิก
                  </p>
                  <small className={s.muted}>
                    หลังยืนยัน ฝั่งผู้ป่วย ID นี้จะอ่านโรค/ภาวะ รายการยาที่บันทึก ประวัติแพ้ และข้อจำกัดได้ ส่วนหมายเหตุการดูแลและป้ายชื่อผู้ดูแลไม่ถูกส่งไปฝั่งผู้ป่วย
                  </small>
                </div>
              </details>
            </form>
          </section>

          <div>
            <section className={s.card}>
              <h3>ฉบับที่ใช้เปรียบเทียบ</h3>

              <div
                style={{
                  padding: "14px 16px",
                  borderRadius: 10,
                  border: "1px solid #cce0d3",
                  background: "#f6fbf8",
                  marginBottom: 14,
                }}
              >
                {data.active ? (
                  <>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
                      <b>🟢 ฉบับที่ยืนยันแล้ว: v{data.active.version}</b>
                      <small className={s.muted}>
                        ยืนยันโดย {data.active.reviewed_by} · {careTime(data.active.reviewed_at!)}
                      </small>
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 8 }}>
                      {Object.entries({
                        "โรค/ภาวะ": data.active.content.conditions,
                        "ยาที่บันทึก": data.active.content.medications,
                        "ประวัติแพ้": data.active.content.allergies,
                        "ข้อจำกัด": data.active.content.limitations,
                        "ผู้ดูแล": data.active.content.caregiver,
                        "หมายเหตุ": data.active.content.care_notes,
                      }).map(([label, value]) => (
                        <p key={label} style={{ margin: "2px 0", fontSize: 13 }}>
                          <b>{label}:</b> {value || "ยังไม่ได้บันทึก"}
                        </p>
                      ))}
                    </div>
                    <p style={{ margin: "10px 0 2px", fontSize: 13 }}>
                      <b>ช่วงอ้างอิง:</b> {statusLabels[data.active.reference?.status ?? "NOT_CONFIGURED"]}
                    </p>
                    {data.active.reference && (
                      <small className={s.muted}>
                        {data.active.reference.sample_count} snapshot · {careTime(data.active.reference.start)} ถึง {careTime(data.active.reference.end)}
                      </small>
                    )}
                  </>
                ) : (
                  <p style={{ margin: 0 }}>ยังไม่มีฉบับที่ยืนยันแล้ว</p>
                )}
              </div>

              {hasDraft && (
                <p className={s.warning}>
                  📝 มีร่าง v{data.latest!.version} รอยืนยัน ฉบับเดิมยังคงใช้จนกว่าจะยืนยันฉบับใหม่หรือพักการใช้
                </p>
              )}

              <label className={s.check} style={{ padding: "10px 12px", background: "#f8faf8", borderRadius: 8, border: "1px solid #dfe7df" }}>
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                />{" "}
                ฉันตรวจข้อมูลและช่วงอ้างอิงที่เลือกแล้ว ใช้สำหรับสาธิต ไม่ใช่การอนุมัติรักษา
              </label>

              <div className={s.actions}>
                {hasDraft && (
                  <button
                    disabled={busy || !confirmed}
                    onClick={() =>
                      void mutate("profile/review", "PATCH", {
                        expected_version: data.version,
                        action: "APPROVE",
                        confirmed,
                      })
                    }
                  >
                    ยืนยันโปรไฟล์ฉบับร่าง
                  </button>
                )}
                {data.active && (
                  <button
                    disabled={busy || !confirmed}
                    onClick={() =>
                      void mutate("profile/review", "PATCH", {
                        expected_version: data.version,
                        action: "PAUSE",
                        confirmed,
                      })
                    }
                  >
                    พักการเปรียบเทียบรายคน
                  </button>
                )}
              </div>
            </section>

            <ProfileComparison
              key={`${patientId}-${data.version}-${data.active?.version ?? "none"}-${data.active?.state ?? "none"}`}
              patientId={patientId}
            />

            <section className={s.card}>
              <details className={s.learnMoreDrawer} style={{ margin: 0 }}>
                <summary className={s.learnMoreSummary}>
                  <span>🗂️ ประวัติโปรไฟล์ (ล่าสุด 20 ฉบับ · Learn More)</span>
                  <span className={s.learnMoreBadge}>ดู {data.history.length} ฉบับ</span>
                </summary>
                <div className={s.learnMoreBody}>
                  {data.history.map((v) => (
                    <p key={v.version} style={{ paddingBottom: 8, borderBottom: "1px solid #dfe7df" }}>
                      <b>v{v.version} · {stateLabels[v.state] ?? v.state}</b>
                      <small>{careTime(v.saved_at)} · {v.saved_by}</small>
                      {v.content.conditions || "ไม่ได้ระบุโรค/ภาวะ"}
                    </p>
                  ))}
                </div>
              </details>
            </section>
          </div>
        </div>
      )}
    </>
  );
}

function ProfileComparison({ patientId }: { patientId: string }) {
  const [data, setData] = useState<Profile | null>(null);
  const [error, setError] = useState("");
  const [key, setKey] = useState<CareVital>("heart_rate");

  useEffect(() => {
    const abort = new AbortController();
    let revision = 0;
    async function load() {
      const id = ++revision;
      try {
        const r = await fetch(`/api/care/patients/${patientId}/profile`, { signal: abort.signal });
        if (!r.ok) throw new Error();
        const value = await r.json();
        if (id === revision) {
          setData(value);
          setError("");
        }
      } catch {
        if (!abort.signal.aborted && id === revision) {
          setData(null);
          setError("โหลดค่าปัจจุบันไม่ได้ ไม่แสดงผลเก่าเป็นค่าล่าสุด");
        }
      }
    }
    void load();
    const timer = setInterval(load, 5000);
    return () => {
      revision++;
      abort.abort();
      clearInterval(timer);
    };
  }, [patientId]);

  const c = data?.comparison;
  const reference = c?.reference[key];
  const range = c?.ranges[key];

  return (
    <section className={s.card}>
      <h3>เทียบกับข้อมูลของรายนี้</h3>
      <p className={s.muted}>การเปรียบเทียบเชิงสถิติ/กฎ ไม่ใช่โมเดล ML ใหม่ · อัปเดตทุก 5 วินาที</p>
      {error && <p role="alert">{error}</p>}
      {c && (
        <>
          <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
            <span><b>โปรไฟล์ v{c.profile_version ?? "—"}:</b> {statusLabels[c.status] ?? c.status}</span>
            <span className={s.muted}>ช่วงอ้างอิง: {statusLabels[c.reference_status] ?? c.reference_status}</span>
          </div>
          <label>
            ตัวแปร
            <select value={key} onChange={(e) => setKey(e.target.value as CareVital)}>
              {careVitals.map((k) => (
                <option key={k} value={k}>{careVitalLabels[k]}</option>
              ))}
            </select>
          </label>
          {c.status === "READY" && (
            <>
              <div className={s.chart}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data?.recent_readings} margin={{ top: 12, right: 12, left: 0, bottom: 6 }}>
                    <XAxis
                      dataKey="timestamp"
                      type="number"
                      domain={["dataMin", "dataMax"]}
                      tickFormatter={(v) => new Date(v * 1000).toLocaleTimeString("th-TH", { timeZone: "Asia/Bangkok" })}
                      minTickGap={45}
                    />
                    <YAxis domain={["auto", "auto"]} width={45} />
                    <Tooltip labelFormatter={(v) => careTime(Number(v))} />
                    {reference && (
                      <ReferenceArea y1={reference.p05} y2={reference.p95} fill="#b9d5e9" fillOpacity={0.35} ifOverflow="extendDomain" />
                    )}
                    {range && (
                      <>
                        <ReferenceLine y={range.low} stroke="#ad7435" strokeDasharray="4 4" ifOverflow="extendDomain" />
                        <ReferenceLine y={range.high} stroke="#ad7435" strokeDasharray="4 4" ifOverflow="extendDomain" />
                      </>
                    )}
                    <Line dataKey={key} name={careVitalLabels[key]} stroke="#176e53" dot={false} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p>
                เกณฑ์ที่คนกำหนด:{" "}
                {range
                  ? `${range.low}–${range.high}; ล่าสุด ${range.value} (${
                      range.outside ? "นอกขอบเขตที่ตั้งไว้ ให้ทบทวน" : "อยู่ในขอบเขตที่ตั้งไว้ ไม่ใช่ยืนยันว่าปลอดภัย"
                    })`
                  : "ยังไม่ได้กำหนด"}
              </p>
              <p>
                ค่ามัธยฐานอ้างอิง: {metric(reference?.median)} · ต่างจากค่าล่าสุด {metric(reference?.difference)}
              </p>
              <small className={s.muted}>
                สีฟ้า = ช่วงค่าจากตัวอย่าง 5–95 percentile ไม่ใช่ช่วงความมั่นใจทางคลินิก · เส้นประ = ขอบเขตที่คนกำหนด
              </small>
            </>
          )}
        </>
      )}
    </section>
  );
}
