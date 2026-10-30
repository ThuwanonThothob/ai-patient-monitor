"use client";

import { useEffect, useRef, useState } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { bangkokDay, careTime, careVitals, careVitalLabels, type CareVital } from "./careView";
import { metric } from "./evidenceView";
import s from "./ResearchPanel.module.css";

type Gap = { start: number; end: number; seconds: number };
type Coverage = {
  estimated_percent: number;
  valid_snapshot_count: number;
  gap_count: number;
  longest_gap_seconds: number;
  largest_gaps: Gap[];
  note: string;
};
type Measurement = {
  count: number;
  mean: number;
  min: number;
  max: number;
  first: number;
  last: number;
  change: number;
  first_at: number;
  last_at: number;
  evidence_ids: Record<string, number>;
};
type Summary = {
  patient_id: string;
  day: string;
  generated_at: number;
  start: number;
  as_of: number;
  partial_day: boolean;
  digest: string;
  text: string;
  limitations: string[];
  overall_recording: Coverage;
  sources: Record<
    string,
    {
      row_count: number;
      invalid_snapshot_count: number;
      measurements: Record<CareVital, Measurement | null>;
      hourly: ({ hour: number; timestamp: number } & Record<CareVital, number | null>)[];
      coverage: Coverage;
    }
  >;
  ml: Record<
    string,
    {
      evaluations: number;
      ready: number;
      unusual_pattern_evaluations: number;
      abstention_statuses: Record<string, number>;
    }
  >;
  alerts: {
    new_count: number;
    resolved_count: number;
    open_as_of_count: number;
    open_items: { id: number; severity: string; reason: string; created_at: number }[];
  };
  care: {
    due_in_period: number;
    done_in_period: number;
    skipped_in_period: number;
    cancelled_in_period: number;
    open_due_as_of_count: number;
    open_items: { id: number; title: string; assigned_to: string; scheduled_at: number; state: string }[];
    finished_items: { id: number; title: string; note: string; state: string; completed_at: number }[];
  };
  reviews: { id: number; digest: string; reviewed_at: number; reviewed_by: string; note: string }[];
};

export default function DailySummaryPanel({ patientId }: { patientId: string }) {
  const [day, setDay] = useState(bangkokDay());
  return (
    <>
      <section className={s.card}>
        <div className={s.header} style={{ marginBottom: 10 }}>
          <div>
            <div className={s.eyebrow}>DAILY EVIDENCE · ASIA/BANGKOK</div>
            <h2>สรุปการดูแลประจำวัน · {patientId}</h2>
          </div>
          <label style={{ margin: 0, minWidth: 220 }}>
            วันที่รายงาน (เวลาไทย)
            <input
              type="date"
              min="2000-01-01"
              max={bangkokDay()}
              value={day}
              onChange={(e) => setDay(e.target.value)}
            />
          </label>
        </div>

        <details className={s.learnMoreDrawer}>
          <summary className={s.learnMoreSummary}>
            <span>ℹ️ ที่มาของร่างรายงานประจำวันและขอบเขตข้อมูล (Learn More)</span>
            <span className={s.learnMoreBadge}>ดูรายละเอียด</span>
          </summary>
          <div className={s.learnMoreBody}>
            <p className={s.muted}>
              ระบบเตรียมร่างเบื้องหลังทุก 5 นาทีขณะ backend ทำงาน ไม่ต้องเปิดหน้าจอไว้ และกดสร้างฉบับล่าสุดได้
            </p>
            <p className={s.warning} style={{ marginBottom: 0 }}>
              เป็นร่างจากสถิติและผล ML ที่มีหลักฐาน ไม่ได้ใช้ Gemini แต่งข้อความ ไม่วินิจฉัยหรือสั่งรักษา วันที่ยังไม่จบจะแสดงเพียงข้อมูลถึงเวลาที่สร้างร่าง
            </p>
          </div>
        </details>
      </section>

      {day ? <DailyReport key={`${patientId}-${day}`} patientId={patientId} day={day} /> : <p>กรุณาเลือกวันที่</p>}
    </>
  );
}

function DailyReport({ patientId, day }: { patientId: string; day: string }) {
  const [data, setData] = useState<Summary | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [note, setNote] = useState("");
  const [key, setKey] = useState<CareVital>("heart_rate");
  const alive = useRef(true);
  const base = `/api/care/patients/${patientId}/daily`;

  async function read(response: Response) {
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "อ่านรายงานไม่สำเร็จ");
    return result as Summary;
  }

  useEffect(() => {
    alive.current = true;
    const abort = new AbortController();
    fetch(`${base}?day=${day}`, { signal: abort.signal })
      .then(read)
      .then((result) => {
        if (!abort.signal.aborted) setData(result);
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(e.message);
      });
    return () => {
      alive.current = false;
      abort.abort();
    };
  }, [base, day]);

  async function refresh() {
    setBusy(true);
    setError("");
    try {
      const result = await read(await fetch(`${base}/refresh?day=${day}`, { method: "POST" }));
      if (alive.current) {
        setData(result);
        setConfirmed(false);
        setNote("");
      }
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : "สร้างร่างใหม่ไม่สำเร็จ");
    } finally {
      if (alive.current) setBusy(false);
    }
  }

  async function review() {
    if (!data) return;
    setBusy(true);
    setError("");
    try {
      const r = await fetch(`${base}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ day, digest: data.digest, confirmed, note }),
      });
      const result = await r.json();
      if (!r.ok) throw new Error(typeof result.detail === "string" ? result.detail : "บันทึกผลทบทวนไม่สำเร็จ");
      const updated = await read(await fetch(`${base}?day=${day}`));
      if (alive.current) {
        setData(updated);
        setConfirmed(false);
        setNote("");
      }
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : "ตรวจทานไม่สำเร็จ");
    } finally {
      if (alive.current) setBusy(false);
    }
  }

  const matchingReview = data?.reviews.find((r) => r.digest === data.digest);

  return (
    <>
      <section className={s.card}>
        <div className={s.header} style={{ marginBottom: 8 }}>
          <div>
            {data ? (
              <p style={{ margin: 0 }}>
                <b>
                  {matchingReview ? "🟢 ยืนยันแล้ว (ตรงกับร่างที่แสดง)" : "📝 ฉบับร่างรอตรวจทาน"}
                </b>{" "}
                · ข้อมูลถึงก่อน {careTime(data.as_of)} · {data.partial_day ? "ยังไม่ครบวัน" : "สิ้นสุดวันแล้ว"}
                <small className={s.muted}>
                  ร่างสร้างเมื่อ {careTime(data.generated_at)} — ไม่ใช่ค่าปัจจุบันทุกวินาที กดสร้างใหม่หากต้องการข้อมูลล่าสุด
                </small>
              </p>
            ) : (
              <p style={{ margin: 0 }}>จัดการร่างรายงานประจำวัน</p>
            )}
          </div>
          <div className={s.actions} style={{ margin: 0 }}>
            <button disabled={busy} onClick={() => void refresh()}>
              สร้างร่างจากข้อมูลล่าสุด
            </button>
            {data && (
              <a className={s.download} style={{ marginTop: 0 }} href={`${base}/report?day=${day}&digest=${data.digest}`}>
                ดาวน์โหลดร่าง Text + หลักฐาน
              </a>
            )}
          </div>
        </div>
        {error && <p role="alert" className={s.warning} style={{ marginBottom: 0 }}>{error}</p>}
      </section>

      {!data ? (
        <p role="status">{error ? "ยังแสดงรายงานไม่ได้" : "กำลังรวบรวมหลักฐาน…"}</p>
      ) : (
        <>
          <div className={s.stats}>
            <article>
              <span>ความครอบคลุมข้อมูลโดยประมาณ</span>
              <strong>{metric(data.overall_recording.estimated_percent, 1)}%</strong>
              <small>คิดจาก snapshot ที่ผ่านคุณภาพทั้ง 3 ค่า ไม่ใช่หลักฐานว่าระบบออนไลน์ครบทุกวินาที</small>
            </article>
            <article>
              <span>Alert ใหม่ / ยังไม่ปิด ณ เวลารายงาน</span>
              <strong>{data.alerts.new_count} / {data.alerts.open_as_of_count}</strong>
              <small>ปิดในช่วงนี้ {data.alerts.resolved_count} · ไม่ใช่จำนวนเหตุการณ์โรค</small>
            </article>
            <article>
              <span>งานดูแลเสร็จ / ยังค้างถึงกำหนด</span>
              <strong>{data.care.done_in_period} / {data.care.open_due_as_of_count}</strong>
              <small>
                ข้าม {data.care.skipped_in_period} · ยกเลิก {data.care.cancelled_in_period} · กำหนดในช่วงนี้ {data.care.due_in_period}
              </small>
            </article>
          </div>

          <div className={s.twoColumns}>
            <section className={s.card}>
              <div className={s.header} style={{ marginBottom: 8 }}>
                <h3>ร่างสรุปสำหรับผู้ดูแล</h3>
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: 700,
                    padding: "4px 10px",
                    borderRadius: 999,
                    background: matchingReview ? "#e5f3ee" : "#fff6e7",
                    color: matchingReview ? "#176e53" : "#76561f",
                    border: `1px solid ${matchingReview ? "#b7dcd0" : "#e8d4ad"}`,
                  }}
                >
                  {matchingReview ? `ยืนยันแล้ว (#${matchingReview.id})` : "ฉบับร่าง (Draft)"}
                </span>
              </div>
              <pre className={s.narrative} style={{ padding: 14, background: "#f8faf8", borderRadius: 10, border: "1px solid #dfe7df" }}>
                {data.text}
              </pre>
            </section>

            <section className={s.card}>
              <h3>ตรวจทานและเก็บฉบับส่งต่อ</h3>
              <p className={s.muted}>
                เก็บสำเนาร่างที่ตรวจแล้วแบบไม่เขียนทับ หากระบบสร้างร่างใหม่ การตรวจฉบับเก่าไม่ถือว่าครอบคลุมข้อมูลใหม่
              </p>

              <div
                style={{
                  padding: "12px 14px",
                  borderRadius: 10,
                  border: `1px solid ${matchingReview ? "#b7dcd0" : "#e8d4ad"}`,
                  background: matchingReview ? "#f2f9f5" : "#fffdf8",
                  marginBottom: 12,
                }}
              >
                <label className={s.check} style={{ marginTop: 0 }}>
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(e) => setConfirmed(e.target.checked)}
                  />{" "}
                  ฉันตรวจแหล่งข้อมูล เวลา และข้อจำกัดของร่างนี้แล้ว
                </label>
                <label>
                  บันทึกผู้ตรวจทาน
                  <textarea
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    maxLength={1000}
                    rows={3}
                    placeholder="ระบุผลการทบทวนและข้อสังเกตสำหรับส่งต่อเวร (อย่างน้อย 3 ตัวอักษร)"
                  />
                </label>
                <button
                  disabled={busy || !confirmed || note.trim().length < 3}
                  onClick={() => void review()}
                  style={{ width: "100%", fontWeight: 700, background: "#176e53", color: "#fff", borderColor: "#176e53" }}
                >
                  บันทึกฉบับที่ตรวจทานแล้ว
                </button>
              </div>

              <details className={s.learnMoreDrawer}>
                <summary className={s.learnMoreSummary}>
                  <span>🗂️ ประวัติฉบับที่ตรวจทานแล้วและข้อจำกัดรายงาน ({data.reviews.length} ฉบับ · Learn More)</span>
                  <span className={s.learnMoreBadge}>ดูประวัติ</span>
                </summary>
                <div className={s.learnMoreBody}>
                  {!data.reviews.length && <p className={s.muted}>ยังไม่มีฉบับที่ตรวจทานแล้วสำหรับวันนี้</p>}
                  {data.reviews.map((r) => (
                    <article key={r.id} className={s.task}>
                      <b>ฉบับตรวจทาน #{r.id}</b>
                      <small>
                        {careTime(r.reviewed_at)} · {r.reviewed_by} ·{" "}
                        {r.digest === data.digest ? "ตรงกับร่างที่แสดง" : "เป็นร่างก่อนหน้า"}
                      </small>
                      <p>{r.note}</p>
                      <a href={`${base}/reviews/${r.id}/report`}>ดาวน์โหลดสำเนาฉบับนี้ · Text</a>
                    </article>
                  ))}
                  <details style={{ marginTop: 12 }}>
                    <summary>ข้อจำกัดของรายงาน</summary>
                    <ul>
                      {data.limitations.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </details>
                </div>
              </details>
            </section>
          </div>

          <section className={s.card}>
            <div className={s.header} style={{ marginBottom: 10 }}>
              <h3>หลักฐานการวัด แยกตามแหล่งข้อมูล</h3>
              <label style={{ margin: 0, minWidth: 220 }}>
                ตัวแปรในกราฟ
                <select value={key} onChange={(e) => setKey(e.target.value as CareVital)}>
                  {careVitals.map((k) => (
                    <option key={k} value={k}>{careVitalLabels[k]}</option>
                  ))}
                </select>
              </label>
            </div>
            {!Object.keys(data.sources).length && (
              <p className={s.warning}>ไม่มีการวัดในช่วงนี้ ไม่แสดงค่าจากทะเบียนแทนข้อมูลจริง</p>
            )}
            {Object.entries(data.sources).map(([source, group]) => (
              <article key={source} className={s.task}>
                <h3>
                  {source === "BIDMC_REPLAY"
                    ? "BIDMC · เล่นข้อมูลย้อนหลัง"
                    : source === "MQTT"
                    ? "MQTT · ตามแหล่งที่ระบบบันทึก"
                    : source === "TEST_SIMULATION"
                    ? "TEST Simulation · เซนเซอร์บ้านจำลอง"
                    : "ไม่ทราบแหล่งข้อมูล"}
                </h3>
                <p>
                  {group.row_count} แถว · snapshot ไม่ครบ/ไม่ผ่านคุณภาพ {group.invalid_snapshot_count} จุด · ไม่เฉลี่ยรวมกับแหล่งอื่น
                </p>
                <div className={s.chart}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={group.hourly}>
                      <XAxis dataKey="hour" type="number" domain={[0, 23]} unit=" น." />
                      <YAxis domain={["auto", "auto"]} width={45} />
                      <Tooltip />
                      <Line
                        name={careVitalLabels[key]}
                        dataKey={key}
                        stroke="#176e53"
                        connectNulls={false}
                        isAnimationActive={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
                <p className={s.muted}>ค่าเฉลี่ยรายชั่วโมง ไม่ใช่กราฟวัดทุกวินาที</p>
                <div className={s.scroll}>
                  <table>
                    <thead>
                      <tr>
                        <th>ตัวแปร</th>
                        <th>จำนวน</th>
                        <th>เฉลี่ย</th>
                        <th>ต่ำสุด–สูงสุด</th>
                        <th>แรก → ท้าย</th>
                        <th>หลักฐานแถวข้อมูล</th>
                      </tr>
                    </thead>
                    <tbody>
                      {careVitals.map((k) => {
                        const m = group.measurements[k];
                        return (
                          <tr key={k}>
                            <td>{careVitalLabels[k]}</td>
                            <td>{m?.count ?? 0}</td>
                            <td>{metric(m?.mean)}</td>
                            <td>{metric(m?.min)}–{metric(m?.max)}</td>
                            <td>{metric(m?.first)} → {metric(m?.last)}</td>
                            <td>
                              {m
                                ? Object.entries(m.evidence_ids)
                                    .map(([label, id]) => `${label}: #${id}`)
                                    .join(" · ")
                                : "ไม่มีข้อมูล"}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </article>
            ))}
          </section>

          <section className={s.card}>
            <h3>งานค้าง ผลที่บันทึก และรายละเอียดเทคนิค</h3>
            <div className={s.twoColumns}>
              <div>
                {data.care.open_items.map((t) => (
                  <p key={t.id}>
                    <b>งาน #{t.id} · {t.title}</b>
                    <small>{t.assigned_to} · กำหนด {careTime(t.scheduled_at)} · {t.state}</small>
                  </p>
                ))}
                {data.care.finished_items.map((t) => (
                  <p key={t.id}>
                    <b>งาน #{t.id} · {t.title} · {t.state}</b>
                    <small>{careTime(t.completed_at)}</small>
                    {t.note || "ไม่มีหมายเหตุ"}
                  </p>
                ))}
              </div>
              <div>
                <details>
                  <summary>Alert ที่ยังไม่ปิด ณ เวลารายงาน ({data.alerts.open_items.length})</summary>
                  {data.alerts.open_items.map((a) => (
                    <p key={a.id}>
                      <b>Alert #{a.id} · {a.severity}</b>
                      <small>{careTime(a.created_at)}</small>
                      {a.reason}
                    </p>
                  ))}
                </details>
              </div>
            </div>

            <details className={s.learnMoreDrawer}>
              <summary className={s.learnMoreSummary}>
                <span>📊 ข้อมูลขาดช่วงและประวัติการประเมินจากโมเดล ML (Learn More)</span>
                <span className={s.learnMoreBadge}>ดูหลักฐานเทคนิค</span>
              </summary>
              <div className={s.learnMoreBody}>
                <div className={s.twoColumns}>
                  <div>
                    <h4>ข้อมูลขาดช่วง</h4>
                    <p>
                      {data.overall_recording.gap_count} ช่วงเกิน 15 วินาที · นานสุด{" "}
                      {Math.round(data.overall_recording.longest_gap_seconds)} วินาที
                    </p>
                    <p className={s.muted}>{data.overall_recording.note}</p>
                    {data.overall_recording.largest_gaps.map((g) => (
                      <p key={g.start}>
                        {careTime(g.start)} → {careTime(g.end)}
                        <small>{Math.round(g.seconds)} วินาที</small>
                      </p>
                    ))}
                  </div>
                  <div>
                    <h4>ML ที่บันทึกไว้จริง</h4>
                    {!Object.keys(data.ml).length && (
                      <p>ไม่มีประวัติผลโมเดลในช่วงนี้ ไม่ได้แปลว่าโมเดลตรวจแล้วไม่พบความผิดปกติ</p>
                    )}
                    {Object.entries(data.ml).map(([source, m]) => (
                      <article key={source}>
                        <b>{source}</b>
                        <p>
                          {m.evaluations} รอบ · พร้อม {m.ready} · รูปแบบต่างจากชุดฝึก {m.unusual_pattern_evaluations} รอบ
                        </p>
                        <small>
                          งดประเมิน:{" "}
                          {Object.entries(m.abstention_statuses)
                            .map(([name, count]) => `${name} ${count}`)
                            .join(", ") || "ไม่มีในประวัติที่บันทึก"}
                        </small>
                      </article>
                    ))}
                    <p className={s.muted}>
                      ไม่คำนวณย้อนหลังแล้วอ้างว่าเคยแจ้งเตือน และไม่ใช้ผล Research Lab เป็นผลของผู้ป่วยรายนี้
                    </p>
                  </div>
                </div>
              </div>
            </details>
          </section>
        </>
      )}
    </>
  );
}
