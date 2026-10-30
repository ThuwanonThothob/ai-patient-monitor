"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import s from "./ResearchPanel.module.css";
import w from "./Ward.module.css";
import type { TaskHistoryItem } from "./apiRequest";
import CareProfilePanel from "./CareProfilePanel";
import DailySummaryPanel from "./DailySummaryPanel";

type Plan = { id: number; title: string; instructions: string; assigned_to: string; interval_minutes: number; next_due: number; state: string; version: number };
type Task = { id: number; title: string; instructions: string; assigned_to: string; scheduled_at: number; state: string; version: number; note: string; overdue_seconds: number };
type Care = { task_count: number; open_task_count: number; task_list_truncated: boolean; patient_id: string; plans: Plan[]; tasks: Task[]; events: { id: number; action: string; actor: string; detail: string; created_at: number }[] };

const ids = ["A", "B", "C"].flatMap((zone) => Array.from({ length: 20 }, (_, i) => `${zone}${String(i + 1).padStart(3, "0")}`));
const states: Record<string, string> = {
  DRAFT: "📝 รอคนตรวจแผน",
  ACTIVE: "🟢 เปิดใช้งาน",
  PAUSED: "⏸️ พักแผน",
  COMPLETED: "✅ จบแผนครั้งเดียว",
  PENDING: "⚠️ รอรับงาน",
  ACKNOWLEDGED: "⏳ รับงานแล้ว",
  DONE: "✅ บันทึกเสร็จแล้ว",
  SKIPPED: "⏭️ ข้ามพร้อมเหตุผล",
  CANCELLED: "🚫 ยกเลิกรอบจากการพักแผน",
};
const date = (value: number) => new Date(value * 1000).toLocaleString("th-TH", { hour12: false });

const templates = [
  { title: "พลิกตัวและตรวจผิวหนังทุก 2 ชม.", instructions: "จัดท่าตะแคงสลับซ้าย-ขวา ตรวจจุดกดทับบริเวณก้นกบและส้นเท้า พร้อมบันทึกสภาพผิวหนัง", assigned_to: "ทีมพยาบาลเวร", interval: 120 },
  { title: "ตรวจตำแหน่งเซนเซอร์และค่าสัญญาณชีพ", instructions: "ตรวจสอบความกระชับของเซนเซอร์วัด SpO2 และแผ่นวัดแรงกดข้างเตียง พร้อมเทียบค่าสัญญาณชีพ", assigned_to: "ทีมพยาบาลเวร", interval: 60 },
  { title: "จัดท่านอนศีรษะสูงและสังเกตการหายใจ", instructions: "จัดท่าศีรษะสูง 30-45 องศา สังเกตจังหวะการหายใจ อาการเหนื่อยหอบ และค่าออกซิเจน", assigned_to: "ทีมพยาบาลเวร", interval: 180 },
];

export default function CarePanel() {
  const [patient, setPatient] = useState("A001");
  const [view, setView] = useState<"profile" | "tasks" | "daily">("profile");
  const [data, setData] = useState<Care | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const request = useRef(0);
  const revision = useRef(0);
  const formRef = useRef<HTMLFormElement | null>(null);

  const applyTemplate = (t: (typeof templates)[number]) => {
    const form = formRef.current;
    if (!form) return;
    const set = (k: string, v: string) => {
      const el = form.elements.namedItem(k) as HTMLInputElement | HTMLTextAreaElement | null;
      if (el) el.value = v;
    };
    set("title", t.title);
    set("instructions", t.instructions);
    set("assigned_to", t.assigned_to);
    set("delay", "0");
    set("interval", String(t.interval));
  };

  const invalidate = useCallback(() => { request.current++; }, []);

  const load = useCallback(async () => {
    const id = ++request.current;
    try {
      const r = await fetch(`/api/care/patients/${patient}`);
      if (!r.ok) throw new Error("โหลดแผนไม่สำเร็จ กรุณารีเฟรช ไม่ได้หมายความว่าไม่มีงานค้าง");
      const result = await r.json() as Care;
      if (id === request.current) { setData(result); setError(""); }
    } catch (e) {
      if (id === request.current) setError(e instanceof Error ? e.message : "โหลดไม่สำเร็จ");
    }
  }, [patient]);

  useEffect(() => {
    const first = setTimeout(() => void load(), 0);
    const timer = setInterval(() => void load(), 5000);
    return () => { invalidate(); clearTimeout(first); clearInterval(timer); };
  }, [load, invalidate]);

  async function write(path: string, method: string, body: unknown) {
    const current = revision.current;
    setBusy(true);
    setError("");
    try {
      const r = await fetch(path, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const result = await r.json();
        throw new Error(typeof result.detail === "string" ? result.detail : "ข้อมูลไม่ครบหรือไม่ถูกต้อง");
      }
      if (current === revision.current) await load();
      return true;
    } catch (e) {
      if (current === revision.current) setError(e instanceof Error ? e.message : "บันทึกไม่สำเร็จ");
      return false;
    } finally {
      if (current === revision.current) setBusy(false);
    }
  }

  async function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const values = new FormData(form);
    const saved = await write(`/api/care/patients/${patient}/plans`, "POST", {
      title: values.get("title"),
      instructions: values.get("instructions"),
      assigned_to: values.get("assigned_to"),
      interval_minutes: Number(values.get("interval")),
      first_due: Date.now() / 1000 + Number(values.get("delay")) * 60,
    });
    if (saved) form.reset();
  }

  const visible = data?.patient_id === patient ? data : null;
  const activePlansCount = visible?.plans.filter((p) => p.state === "ACTIVE").length ?? 0;
  const draftPlansCount = visible?.plans.filter((p) => p.state === "DRAFT").length ?? 0;

  return (
    <div className={s.root}>
      <section className={s.card}>
        <div className={s.header} style={{ marginBottom: 12 }}>
          <div>
            <div className={s.eyebrow}>HUMAN PLAN → REVIEW → DUE TASK → ACKNOWLEDGE → RECORD</div>
            <h2>พื้นที่ดูแลรายบุคคล · เตียง {patient}</h2>
          </div>
          {visible && (
            <div className={s.actions} style={{ margin: 0 }}>
              <span className={w.pill} style={{ borderColor: "#c9dfd3", background: "#f2f9f5", color: "#155d44" }}>
                งานถึงกำหนด {visible.open_task_count} รายการ
              </span>
              <span className={w.pill} style={{ borderColor: "#cbd5e1", background: "#f8fafc", color: "#334155" }}>
                แผนเปิดใช้ {activePlansCount} · ร่าง {draftPlansCount}
              </span>
            </div>
          )}
        </div>

        <div className={s.twoColumns} style={{ alignItems: "end", gap: 14 }}>
          <label style={{ margin: 0 }}>
            🛏️ เตียง / Patient ID
            <select
              value={patient}
              disabled={busy}
              onChange={(e) => {
                revision.current++;
                request.current++;
                setData(null);
                setPatient(e.target.value);
                setConfirmed(false);
                setError("");
              }}
            >
              {ids.map((id) => (
                <option key={id} value={id}>🛏️ เตียง {id}</option>
              ))}
            </select>
          </label>

          <div className={s.actions} style={{ margin: 0, justifyContent: "space-between" }}>
            <div className={s.actions} style={{ margin: 0 }} role="group" aria-label="หมวดย่อยการดูแล">
              <button disabled={busy} aria-pressed={view === "profile"} onClick={() => setView("profile")}>
                ข้อมูลการดูแล
              </button>
              <button disabled={busy} aria-pressed={view === "tasks"} onClick={() => setView("tasks")}>
                งานดูแล
              </button>
              <button disabled={busy} aria-pressed={view === "daily"} onClick={() => setView("daily")}>
                สรุปประจำวัน
              </button>
            </div>
            {view === "tasks" && (
              <div className={s.actions} style={{ margin: 0 }}>
                <button disabled={busy} onClick={() => void load()}>รีเฟรชงาน</button>
                <a className={s.download} style={{ marginTop: 0 }} href={`/api/care/patients/${patient}/report`}>
                  รายงานส่งต่อ Text
                </a>
              </div>
            )}
          </div>
        </div>

        <details className={w.learnMoreDrawer}>
          <summary className={w.learnMoreSummary}>
            <span>ℹ️ ขั้นตอนการใช้งานและขอบเขตการเข้าถึงข้อมูลแผนดูแล (Learn More)</span>
            <span className={w.learnMoreBadge}>ดูรายละเอียด</span>
          </summary>
          <div className={w.learnMoreBody}>
            <p className={s.muted}>
              เลือก Patient ID เพื่อจัดการโปรไฟล์ งานดูแล และสรุปประจำวัน ข้อมูลที่คนกำหนดต้องผ่านการตรวจยืนยัน ไม่ใช่ AI สั่งการรักษา
            </p>
            <p className={s.muted}>
              แผนที่ยืนยันแล้ว: ฝั่งผู้ป่วย ID เดียวกันอ่านชื่องาน รายละเอียด กำหนดเวลา และสถานะได้ แต่ไม่เห็นบันทึกผลภายในหรือแก้ไขงาน
            </p>
            <p className={s.warning} style={{ marginBottom: 0 }}>
              ใช้กับทะเบียนสาธิตเท่านั้น บัญชีบุคลากรร่วมยังไม่ใช่การยืนยันแพทย์ผู้อนุมัติ · ไม่มีการส่ง Push งานดูแล ติดต่อบุคคล หรือเปลี่ยนการรักษาอัตโนมัติ · ผู้รับผิดชอบเป็นป้ายชื่อ ไม่ใช่บัญชีผู้รับจริง
            </p>
          </div>
        </details>

        {error && <p role="alert" className={w.error} style={{ marginTop: 12, marginBottom: 0 }}>{error}</p>}
      </section>

      {view === "profile" ? (
        <CareProfilePanel key={patient} patientId={patient} />
      ) : view === "daily" ? (
        <DailySummaryPanel key={patient} patientId={patient} />
      ) : (
        <div className={s.layout}>
          <section className={s.card}>
            <h3>สร้างร่างแผน · {patient}</h3>

            <div
              style={{
                padding: "12px 14px",
                background: "#f4faf7",
                border: "1px solid #cce0d3",
                borderRadius: 10,
                marginBottom: 14,
              }}
            >
              <div className={s.actions} style={{ margin: 0 }} role="group" aria-label="แม่แบบแผนดูแลด่วน">
                <span style={{ fontWeight: 700, color: "#176e53", width: "100%", marginBottom: 2 }}>
                  ⚡ แม่แบบแผนดูแลด่วน (คลิกเพื่อเติมฟอร์มทันที):
                </span>
                {templates.map((t) => (
                  <button
                    key={t.title}
                    type="button"
                    disabled={busy}
                    onClick={() => applyTemplate(t)}
                    style={{ fontSize: 12.5, padding: "6px 10px", minHeight: 36, textAlign: "left" }}
                  >
                    {t.title} ({t.interval} นาที)
                  </button>
                ))}
              </div>
            </div>

            <form ref={formRef} key={patient} onSubmit={create}>
              <label>
                ชื่องาน
                <input name="title" required minLength={3} maxLength={120} placeholder="เช่น ตรวจอุปกรณ์วัด" />
              </label>
              <label>
                รายละเอียดที่ผู้ดูแลกำหนด
                <textarea
                  name="instructions"
                  required
                  minLength={3}
                  maxLength={1000}
                  rows={3}
                  placeholder="ระบุวิธีดำเนินการตามแผนที่ได้รับการประเมินแล้ว"
                />
              </label>
              <label>
                ป้ายชื่อผู้รับผิดชอบ
                <input name="assigned_to" required minLength={2} maxLength={100} placeholder="ทีมสาธิต" />
              </label>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <label style={{ margin: "6px 0" }}>
                  เริ่มอีกกี่นาที (0 = ตอนนี้)
                  <input name="delay" type="number" min={0} max={525600} step={1} defaultValue={0} required />
                </label>
                <label style={{ margin: "6px 0" }}>
                  ทำซ้ำหลังจบงานกี่นาที (0 = ครั้งเดียว)
                  <input name="interval" type="number" min={0} max={10080} step={1} defaultValue={0} required />
                </label>
              </div>

              <div style={{ marginTop: 12 }}>
                <button disabled={busy} type="submit" style={{ width: "100%", fontWeight: 700, background: "#176e53", color: "#fff", borderColor: "#176e53" }}>
                  บันทึกร่าง ยังไม่เปิดใช้งาน
                </button>
              </div>

              <details className={w.learnMoreDrawer}>
                <summary className={w.learnMoreSummary}>
                  <span>📋 คำอธิบายขั้นตอนการตั้งความถี่และเปิดใช้งานแผน (Learn More)</span>
                  <span className={w.learnMoreBadge}>ดูขั้นตอน</span>
                </summary>
                <div className={w.learnMoreBody}>
                  <p className={s.muted} style={{ margin: 0 }}>
                    ไม่กำหนดความถี่ทางการแพทย์สำเร็จรูป ต้องให้ผู้ดูแลกำหนดตามแผนเฉพาะราย เมื่อบันทึกร่างแล้ว ให้ตรวจสอบในหัวข้อ &ldquo;แผนที่บันทึกไว้&rdquo; ด้านขวาเพื่อติ๊กยืนยันและกดเปิดใช้งาน
                  </p>
                </div>
              </details>
            </form>
          </section>

          <div>
            <section className={s.card}>
              <div className={s.header} style={{ marginBottom: 8 }}>
                <h3>งานถึงกำหนด · {patient}</h3>
                {visible && (
                  <span className={s.muted}>
                    งานเปิด {visible.open_task_count} · ทั้งหมด {visible.task_count} · แสดง {visible.tasks.length} รายการ โดยให้งานค้างมาก่อน
                  </span>
                )}
              </div>
              {visible?.task_list_truncated && (
                <p className={s.warning}>
                  รายการยาวเกิน 100 งาน หน้านี้และรายงานแสดงเพียง 100 รายการแรก ไม่ใช่ประวัติครบทั้งหมด
                </p>
              )}
              {!visible ? (
                <p>กำลังโหลด…</p>
              ) : !visible.tasks.length ? (
                <p className={s.muted}>ยังไม่มีงานถึงกำหนดจากแผนที่เปิดใช้</p>
              ) : (
                visible.tasks.map((task) => (
                  <TaskCard
                    key={task.id}
                    task={task}
                    busy={busy}
                    update={(state, note) => write(`/api/care/tasks/${task.id}`, "PATCH", { version: task.version, state, note })}
                  />
                ))
              )}

              <details className={w.learnMoreDrawer}>
                <summary className={w.learnMoreSummary}>
                  <span>🔄 เงื่อนไขการอัปเดตงานถึงกำหนดอัตโนมัติ (Learn More)</span>
                  <span className={w.learnMoreBadge}>ดูรายละเอียด</span>
                </summary>
                <div className={w.learnMoreBody}>
                  <p className={s.muted} style={{ margin: 0 }}>
                    ตรวจทุก 5 วินาทีเมื่อ backend ทำงาน หากปิดระบบ งานจะไม่ถูกบันทึกว่าเสร็จเอง
                  </p>
                </div>
              </details>
            </section>

            <section className={s.card}>
              <h3>แผนที่บันทึกไว้</h3>
              <label className={s.check} style={{ padding: "10px 12px", background: "#f8faf8", borderRadius: 8, border: "1px solid #dfe7df" }}>
                <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />{" "}
                ฉันตรวจแผนสาธิตที่กำลังจะเปิดใช้แล้ว การกดนี้ไม่ใช่การอนุมัติทางการแพทย์
              </label>

              {visible?.plans.map((plan) => (
                <article className={s.task} key={plan.id}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <b>{plan.title} · {states[plan.state]}</b>
                    <small className={s.muted}>
                      {plan.assigned_to} · {plan.interval_minutes ? `ทำซ้ำหลังจบงาน ${plan.interval_minutes} นาที` : "ครั้งเดียว"} · กำหนด {date(plan.next_due)}
                    </small>
                  </div>
                  <p style={{ margin: "6px 0 8px" }}>{plan.instructions}</p>
                  <div className={s.actions}>
                    {["DRAFT", "PAUSED"].includes(plan.state) && (
                      <button
                        disabled={busy || !confirmed}
                        onClick={() =>
                          void write(`/api/care/plans/${plan.id}`, "PATCH", {
                            version: plan.version,
                            state: "ACTIVE",
                            demo_review_confirmed: confirmed,
                          }).then((ok) => {
                            if (ok) setConfirmed(false);
                          })
                        }
                      >
                        ยืนยันและเปิดใช้
                      </button>
                    )}
                    {plan.state === "ACTIVE" && (
                      <button
                        disabled={busy}
                        onClick={() => void write(`/api/care/plans/${plan.id}`, "PATCH", { version: plan.version, state: "PAUSED" })}
                      >
                        พักแผนและยกเลิกงานรอบที่ค้าง
                      </button>
                    )}
                  </div>
                </article>
              ))}

              {visible && !visible.plans.length && <p className={s.muted}>ยังไม่มีแผน เริ่มสร้างร่างทางด้านซ้าย</p>}

              <details className={w.learnMoreDrawer}>
                <summary className={w.learnMoreSummary}>
                  <span>📌 การแก้ไขแผนและประวัติการดำเนินการล่าสุด (Learn More)</span>
                  <span className={w.learnMoreBadge}>ดูประวัติ ({visible?.events.length ?? 0})</span>
                </summary>
                <div className={w.learnMoreBody}>
                  <p className={s.muted}>
                    หากต้องเปลี่ยนรายละเอียด ให้พักแผนเดิมแล้วสร้างใหม่ เพื่อเก็บประวัติเดิมไว้ การเปิดแผนที่พักไว้อีกครั้งจะเริ่มรอบใหม่ทันที
                  </p>
                  <details>
                    <summary>ประวัติการดำเนินการ (ล่าสุด 100 รายการ)</summary>
                    {visible?.events.map((event) => (
                      <p key={event.id}>
                        <b>{event.action}</b>
                        <small>{date(event.created_at)} · {event.actor}</small>
                        {event.detail}
                      </p>
                    ))}
                  </details>
                </div>
              </details>
            </section>
          </div>
        </div>
      )}
    </div>
  );
}

function TaskCard({ task, busy, update }: { task: Task; busy: boolean; update: (state: string, note: string) => Promise<boolean> }) {
  const [note, setNote] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState<TaskHistoryItem[] | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");

  const open = ["PENDING", "ACKNOWLEDGED"].includes(task.state);
  const isOverdue = open && task.overdue_seconds > 0;

  const toggleHistory = async () => {
    if (showHistory) {
      setShowHistory(false);
      return;
    }
    setShowHistory(true);
    if (!history) {
      setHistoryLoading(true);
      setHistoryError("");
      try {
        const res = await fetch(`/api/care/tasks/${task.id}/history`);
        if (!res.ok) throw new Error("ไม่สามารถโหลดประวัติสถานะได้");
        const json = (await res.json()) as { history?: TaskHistoryItem[] } | TaskHistoryItem[];
        const list = Array.isArray(json) ? json : (json.history ?? []);
        setHistory(list);
      } catch (err) {
        setHistoryError(err instanceof Error ? err.message : "โหลดประวัติไม่สำเร็จ");
      } finally {
        setHistoryLoading(false);
      }
    }
  };

  const handleUpdate = async (state: string, n: string) => {
    const ok = await update(state, n);
    if (ok) {
      setHistory(null);
    }
    return ok;
  };

  return (
    <article className={s.task}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <b>
          {isOverdue ? "🚨 " : task.state === "PENDING" ? "⚠️ " : task.state === "ACKNOWLEDGED" ? "⏳ " : "✅ "}
          {task.title} · {states[task.state]}
        </b>
        <small className={s.muted}>
          {task.assigned_to} · ถึงกำหนด {date(task.scheduled_at)}
          {open
            ? isOverdue
              ? ` · 🚨 เกินกำหนด ${Math.floor(task.overdue_seconds / 60)} นาที`
              : ` · เกินกำหนด ${Math.floor(task.overdue_seconds / 60)} นาที`
            : ""}
        </small>
      </div>
      <p style={{ margin: "6px 0 8px" }}>{task.instructions}</p>
      {open ? (
        <>
          <label>
            ผลการดำเนินการ / เหตุผลที่ข้าม
            <textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} rows={2} />
          </label>
          <div className={s.actions}>
            {task.state === "PENDING" ? (
              <button disabled={busy} onClick={() => void handleUpdate("ACKNOWLEDGED", note)}>
                รับงาน
              </button>
            ) : (
              <button disabled={busy || !note.trim()} onClick={() => void handleUpdate("DONE", note)}>
                บันทึกว่าเสร็จแล้ว
              </button>
            )}
            <button disabled={busy || !note.trim()} onClick={() => void handleUpdate("SKIPPED", note)}>
              ข้ามพร้อมเหตุผล
            </button>
          </div>
        </>
      ) : (
        <p className={s.muted}>{task.note || "ไม่มีบันทึกผล"}</p>
      )}
      <div className={s.actions} style={{ marginTop: 6 }}>
        <button type="button" className={w.auditToggleBtn} onClick={toggleHistory}>
          📋 {showHistory ? "ซ่อนประวัติสถานะ" : "ดูประวัติสถานะ (Audit Trail)"}
        </button>
      </div>
      {showHistory && (
        <div className={w.auditTrailSection}>
          {historyLoading && <p className={w.auditLoading}>กำลังดึงข้อมูลประวัติสถานะ…</p>}
          {historyError && <p role="alert" className={w.auditError}>{historyError}</p>}
          {history && !history.length && !historyLoading && (
            <p className={w.auditEmpty}>ยังไม่มีบันทึกการเปลี่ยนสถานะของงานนี้</p>
          )}
          {history && history.length > 0 && (
            <ol className={w.auditTrailList}>
              {history.map((item, idx) => (
                <li key={item.id ?? idx} className={w.auditItem}>
                  <div className={w.auditHead}>
                    <span className={w.auditTransition}>
                      {states[item.previous_state] || item.previous_state} ➔ {states[item.new_state] || item.new_state}
                    </span>
                    <small className={w.auditTime}>
                      {item.timestamp || item.created_at ? date(item.timestamp || item.created_at) : "—"}
                    </small>
                  </div>
                  <div className={w.auditDetails}>
                    <span>ผู้ดำเนินการ: <b>{item.actor}</b></span>
                    {item.skip_reason && <span className={w.auditReason}>เหตุผล: {item.skip_reason}</span>}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </article>
  );
}
