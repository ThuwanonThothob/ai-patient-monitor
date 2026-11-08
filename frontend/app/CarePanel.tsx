"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import w from "./Ward.module.css";
import type { TaskHistoryItem } from "./apiRequest";
import CareProfilePanel from "./CareProfilePanel";
import DailySummaryPanel from "./DailySummaryPanel";

type Plan = {
  id: number;
  title: string;
  instructions: string;
  assigned_to: string;
  interval_minutes: number;
  next_due: number;
  state: string;
  version: number;
};
type Task = {
  id: number;
  title: string;
  instructions: string;
  assigned_to: string;
  scheduled_at: number;
  state: string;
  version: number;
  note: string;
  overdue_seconds: number;
};
type Care = {
  task_count: number;
  open_task_count: number;
  task_list_truncated: boolean;
  patient_id: string;
  plans: Plan[];
  tasks: Task[];
  events: { id: number; action: string; actor: string; detail: string; created_at: number }[];
};

const defaultIds = ["A", "B", "C"].flatMap((zone) =>
  Array.from({ length: 20 }, (_, i) => `${zone}${String(i + 1).padStart(3, "0")}`)
);

const states: Record<string, string> = {
  DRAFT: "รอตรวจแผน",
  ACTIVE: "เปิดใช้งาน",
  PAUSED: "พักแผน",
  COMPLETED: "จบแผนครั้งเดียว",
  PENDING: "รอรับงาน",
  ACKNOWLEDGED: "รับงานแล้ว",
  DONE: "บันทึกเสร็จแล้ว",
  SKIPPED: "ข้ามพร้อมเหตุผล",
  CANCELLED: "ยกเลิกรอบ",
};
const date = (value: number) =>
  new Date(value * 1000).toLocaleString("th-TH", { hour12: false });

const templates = [
  {
    title: "พลิกตัวและตรวจผิวหนังทุก 2 ชม.",
    instructions:
      "จัดท่าตะแคงสลับซ้าย-ขวา ตรวจจุดกดทับบริเวณก้นกบและส้นเท้า พร้อมบันทึกสภาพผิวหนัง",
    assigned_to: "ทีมพยาบาลเวร",
    interval: 120,
  },
  {
    title: "ตรวจตำแหน่งเซนเซอร์และค่าสัญญาณชีพ",
    instructions:
      "ตรวจสอบความกระชับของเซนเซอร์วัด SpO2 และแผ่นวัดแรงกดข้างเตียง พร้อมเทียบค่าสัญญาณชีพ",
    assigned_to: "ทีมพยาบาลเวร",
    interval: 60,
  },
  {
    title: "จัดท่านอนศีรษะสูงและสังเกตการหายใจ",
    instructions:
      "จัดท่าศีรษะสูง 30-45 องศา สังเกตจังหวะการหายใจ อาการเหนื่อยหอบ และค่าออกซิเจน",
    assigned_to: "ทีมพยาบาลเวร",
    interval: 180,
  },
];

const QUICK_TASK_NOTES = [
  "ดำเนินการตามแผนเรียบร้อย ผู้ป่วยสุขสบายดี",
  "พลิกตัวจัดท่าและตรวจผิวหนังแล้ว ไม่พบรอยกดทับใหม่",
  "ตรวจสอบตำแหน่งเซนเซอร์และเทียบสัญญาณชีพข้างเตียงแล้ว",
  "ผู้ป่วยกำลังพักผ่อนหรืออยู่ระหว่างหัตถการอื่น จึงขอเลื่อนรอบนี้",
];

type CareTab = "tasks" | "plans" | "create" | "profile" | "daily";

export default function CarePanel({
  initialPatientId,
  lockedPatientId,
  allowedPatientIds,
}: {
  initialPatientId?: string;
  lockedPatientId?: string;
  allowedPatientIds?: string[];
} = {}) {
  const [scopedIds, setScopedIds] = useState<string[] | null>(null);

  useEffect(() => {
    if (allowedPatientIds && allowedPatientIds.length > 0) return;
    let alive = true;
    fetch("/api/session/profile")
      .then((r) => (r.ok ? r.json() : null))
      .then(
        (prof: { assigned_patients?: { patient_id?: string }[]; role_type?: string } | null) => {
          if (!alive || !prof) return;
          if (Array.isArray(prof.assigned_patients) && prof.assigned_patients.length > 0) {
            const list = prof.assigned_patients
              .map((p) => p.patient_id)
              .filter((id): id is string => Boolean(id));
            if (list.length > 0) setScopedIds(list);
          }
        }
      )
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [allowedPatientIds]);

  const availableIds = useMemo(() => {
    const base =
      allowedPatientIds && allowedPatientIds.length > 0
        ? allowedPatientIds
        : scopedIds && scopedIds.length > 0
          ? scopedIds
          : defaultIds;
    const unique = Array.from(new Set(base));
    if (lockedPatientId && !unique.includes(lockedPatientId)) {
      unique.unshift(lockedPatientId);
    }
    return unique.length > 0 ? unique : defaultIds;
  }, [allowedPatientIds, scopedIds, lockedPatientId]);

  const [selectedPatient, setSelectedPatient] = useState<string>(() => {
    if (lockedPatientId) return lockedPatientId;
    if (initialPatientId) return initialPatientId;
    return availableIds[0] ?? "A001";
  });

  const patient = lockedPatientId
    ? lockedPatientId
    : availableIds.includes(selectedPatient)
      ? selectedPatient
      : initialPatientId && availableIds.includes(initialPatientId)
        ? initialPatientId
        : availableIds[0] ?? "A001";

  const [tab, setTab] = useState<CareTab>("tasks");
  const [data, setData] = useState<Care | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [autoActivate, setAutoActivate] = useState(true);
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
    setNotice(`เติมแม่แบบ "${t.title}" แล้ว — สามารถกดปุ่มบันทึกด้านล่างเพื่อเริ่มใช้งานได้ทันที`);
  };

  const invalidate = useCallback(() => {
    request.current++;
  }, []);

  const load = useCallback(async () => {
    if (!patient) return;
    const id = ++request.current;
    try {
      const r = await fetch(`/api/care/patients/${encodeURIComponent(patient)}`);
      if (!r.ok) throw new Error("โหลดแผนไม่สำเร็จ กรุณารีเฟรช ไม่ได้หมายความว่าไม่มีงานค้าง");
      const result = (await r.json()) as Care;
      if (id === request.current) {
        setData(result);
        setError("");
      }
    } catch (e) {
      if (id === request.current) setError(e instanceof Error ? e.message : "โหลดไม่สำเร็จ");
    }
  }, [patient]);

  useEffect(() => {
    const first = setTimeout(() => void load(), 0);
    const timer = setInterval(() => void load(), 5000);
    return () => {
      invalidate();
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [load, invalidate]);

  async function write(path: string, method: string, body: unknown, silentReload = false) {
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
        const result = await r.json().catch(() => ({}));
        throw new Error(typeof result.detail === "string" ? result.detail : "ข้อมูลไม่ครบหรือไม่ถูกต้อง");
      }
      if (current === revision.current && !silentReload) await load();
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
    const delayMinutes = Number(values.get("delay") ?? 0);
    const nowSec = Date.now() / 1000;
    const firstDue = delayMinutes <= 0 ? nowSec - 1 : nowSec + delayMinutes * 60;
    const current = revision.current;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const r = await fetch(`/api/care/patients/${encodeURIComponent(patient)}/plans`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: values.get("title"),
          instructions: values.get("instructions"),
          assigned_to: values.get("assigned_to"),
          interval_minutes: Number(values.get("interval")),
          first_due: firstDue,
        }),
      });
      const created = (await r.json().catch(() => ({}))) as { id?: number; detail?: string };
      if (!r.ok || !created.id) {
        throw new Error(typeof created.detail === "string" ? created.detail : "ไม่สามารถสร้างแผนการดูแลได้");
      }

      if (autoActivate) {
        const actRes = await fetch(`/api/care/plans/${created.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            version: 1,
            state: "ACTIVE",
            demo_review_confirmed: true,
          }),
        });
        if (!actRes.ok) {
          const actErr = (await actRes.json().catch(() => ({}))) as { detail?: string };
          throw new Error(typeof actErr.detail === "string" ? actErr.detail : "สร้างร่างสำเร็จแต่เปิดใช้งานไม่สำเร็จ");
        }
        setNotice(
          delayMinutes <= 0
            ? "บันทึกและเปิดใช้งานแผนเรียบร้อย — สร้างงานถึงกำหนดในแท็บงานที่ต้องทำแล้ว"
            : `บันทึกและเปิดใช้งานแผนเรียบร้อย — งานรอบแรกจะถึงกำหนดในอีก ${delayMinutes} นาที`
        );
        setTab("tasks");
      } else {
        setNotice("บันทึกร่างแผนแล้ว — กรุณาไปที่แท็บแผนการดูแลเพื่อยืนยันและเปิดใช้งาน");
        setTab("plans");
      }

      if (current === revision.current) {
        form.reset();
        await load();
      }
    } catch (err) {
      if (current === revision.current) {
        setError(err instanceof Error ? err.message : "บันทึกแผนไม่สำเร็จ");
      }
    } finally {
      if (current === revision.current) setBusy(false);
    }
  }

  async function triggerPlanNow(plan: Plan) {
    setNotice("");
    if (plan.state === "ACTIVE") {
      const paused = await write(`/api/care/plans/${plan.id}`, "PATCH", { version: plan.version, state: "PAUSED" }, true);
      if (!paused) return;
      const resumed = await write(
        `/api/care/plans/${plan.id}`,
        "PATCH",
        { version: plan.version + 1, state: "ACTIVE", demo_review_confirmed: true },
        false
      );
      if (resumed) {
        setNotice(`เร่งรอบงาน "${plan.title}" ให้ถึงกำหนดตอนนี้เรียบร้อยแล้ว`);
      }
    }
  }

  const visible = data?.patient_id === patient ? data : null;
  const activePlansCount = visible?.plans.filter((p) => p.state === "ACTIVE").length ?? 0;
  const draftPlansCount = visible?.plans.filter((p) => p.state === "DRAFT").length ?? 0;

  return (
    <div className={w.carePanelContainer}>
      {/* Patient Identity & Mode Selector Card */}
      <section className={w.carePanelHeaderCard} aria-label="ข้อมูลงานดูแลผู้ป่วย">
        <div className={w.carePanelHeaderTop}>
          <div className={w.carePanelTitleRow}>
            <span className={w.eyebrow}>
              CLINICAL CARE PROTOCOLS &amp; WORKFLOW · ระบบงานบริบาลและแผนการดูแลเฉพาะบุคคล
            </span>
            <h2 className={w.carePanelTitle}>งานบริบาลและแผนการดูแล · เตียง {patient}</h2>
            <div className={w.carePanelBedSelectRow}>
              {lockedPatientId ? (
                <span className={w.pill} style={{ borderColor: "#176e53", background: "#eaf5f0", color: "#134e3a", fontWeight: 700 }}>
                  เตียงที่กำลังดูแล: {patient}
                </span>
              ) : (
                <label style={{ display: "inline-flex", alignItems: "center", gap: 8, margin: 0, fontWeight: 700, fontSize: 13.5 }}>
                  <span>สลับเตียงผู้ป่วย:</span>
                  <select
                    className={w.carePanelBedSelect}
                    value={patient}
                    disabled={busy}
                    aria-label="เลือกเตียงผู้ป่วยเพื่อจัดการงานดูแล"
                    onChange={(e) => {
                      revision.current++;
                      request.current++;
                      setData(null);
                      setSelectedPatient(e.target.value);
                      setConfirmed(false);
                      setError("");
                      setNotice("");
                    }}
                  >
                    {availableIds.map((id) => (
                      <option key={id} value={id}>
                        เตียง {id}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <span className={w.pill} style={{ borderColor: "#c9dfd3", background: "#f2f9f5", color: "#155d44" }}>
                งานถึงกำหนด: {visible?.open_task_count ?? 0} รายการ
              </span>
              <span className={w.pill} style={{ borderColor: "#cbd5e1", background: "#f8fafc", color: "#334155" }}>
                แผนเปิดใช้: {activePlansCount} · ร่าง: {draftPlansCount}
              </span>
            </div>
          </div>

          <div className={w.actions} style={{ margin: 0 }}>
            <button
              type="button"
              className={w.secondary}
              disabled={busy}
              onClick={() => void load()}
              title="ดึงข้อมูลงานและแผนล่าสุด"
            >
              ↻ รีเฟรชงาน
            </button>
            <a
              className={w.secondary}
              style={{ textDecoration: "none", display: "inline-flex", alignItems: "center" }}
              href={`/api/care/patients/${encodeURIComponent(patient)}/report`}
              target="_blank"
              rel="noreferrer"
            >
              รายงานส่งต่อ Text
            </a>
          </div>
        </div>

        {/* Spacious 5-Tab Bar */}
        <div className={w.carePanelTabBar} role="tablist" aria-label="หมวดงานดูแลผู้ป่วย">
          <button
            type="button"
            className={`${w.carePanelTabBtn} ${tab === "tasks" ? w.carePanelTabBtnActive : ""}`}
            aria-pressed={tab === "tasks"}
            onClick={() => setTab("tasks")}
          >
            <span>งานที่ต้องทำ</span>
            <span className={w.careHubTabCount}>{visible?.open_task_count ?? 0}</span>
          </button>
          <button
            type="button"
            className={`${w.carePanelTabBtn} ${tab === "plans" ? w.carePanelTabBtnActive : ""}`}
            aria-pressed={tab === "plans"}
            onClick={() => setTab("plans")}
          >
            <span>แผนการดูแล</span>
            <span className={w.careHubTabCount}>{activePlansCount}</span>
          </button>
          <button
            type="button"
            className={`${w.carePanelTabBtn} ${tab === "create" ? w.carePanelTabBtnActive : ""}`}
            aria-pressed={tab === "create"}
            onClick={() => setTab("create")}
          >
            <span>สร้างแผนใหม่</span>
          </button>
          <button
            type="button"
            className={`${w.carePanelTabBtn} ${tab === "profile" ? w.carePanelTabBtnActive : ""}`}
            aria-pressed={tab === "profile"}
            onClick={() => setTab("profile")}
          >
            <span>เกณฑ์และโปรไฟล์</span>
          </button>
          <button
            type="button"
            className={`${w.carePanelTabBtn} ${tab === "daily" ? w.carePanelTabBtnActive : ""}`}
            aria-pressed={tab === "daily"}
            onClick={() => setTab("daily")}
          >
            <span>สรุปเวรประจำวัน</span>
          </button>
        </div>

        {notice && (
          <p role="status" className={w.notice} style={{ margin: 0 }}>
            {notice}
          </p>
        )}
        {error && (
          <p role="alert" className={w.error} style={{ margin: 0 }}>
            {error}
          </p>
        )}
      </section>

      {/* Tab 1: Operational Due Tasks Queue */}
      {tab === "tasks" && (
        <section className={w.careCard} aria-label="งานดูแลที่ต้องปฏิบัติตามรอบ">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 12, marginBottom: 16 }}>
            <div>
              <span className={w.eyebrow}>OPERATIONAL CARE QUEUE · งานที่ต้องปฏิบัติตามรอบ</span>
              <h3 style={{ margin: "4px 0 4px", fontSize: 18 }}>
                งานดูแลถึงกำหนด · เตียง {patient}
              </h3>
              <p className={w.muted} style={{ margin: 0, fontSize: 13.5 }}>
                จัดการงานถึงกำหนด บันทึกผลการดูแล หรือข้ามงานพร้อมเหตุผล (เฉพาะที่คนกำหนด ไม่ใช่ AI สั่งการ)
              </p>
            </div>
            <button
              type="button"
              className={w.secondary}
              onClick={() => setTab("create")}
            >
              เพิ่มแผนงานใหม่
            </button>
          </div>

          {visible?.task_list_truncated && (
            <p className={w.notice} style={{ margin: "0 0 14px" }}>
              รายการยาวเกิน 100 งาน หน้านี้แสดงเพียง 100 รายการแรก เพื่อความรวดเร็วในการเปิดดูข้างเตียง
            </p>
          )}

          {!visible ? (
            <p className={w.muted}>กำลังโหลดข้อมูลงานดูแล…</p>
          ) : !visible.tasks.length ? (
            <div style={{ padding: "32px 24px", borderRadius: 16, background: "#f8faf9", border: "1px dashed #c9ded4", textAlign: "center" }}>
              <b style={{ display: "block", fontSize: 16, color: "#163a2c", marginBottom: 4 }}>
                ไม่มีงานค้างในรอบนี้สำหรับเตียง {patient}
              </b>
              <p className={w.muted} style={{ margin: "0 auto 16px", maxWidth: 480, fontSize: 13.5 }}>
                แผนการดูแลทุกรายการได้รับการปฏิบัติเรียบร้อย หรือยังไม่ถึงรอบกำหนดเวลาถัดไป
              </p>
              <div className={w.actions} style={{ justifyContent: "center", gap: 10 }}>
                <button type="button" className={w.secondary} onClick={() => setTab("plans")}>
                  ตรวจดูแผนการดูแล ({activePlansCount} แผน)
                </button>
                <button type="button" className={w.primary} onClick={() => setTab("create")}>
                  สร้างแผนการดูแลใหม่
                </button>
              </div>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {visible.tasks.map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  busy={busy}
                  update={(state, note) =>
                    write(`/api/care/tasks/${task.id}`, "PATCH", { version: task.version, state, note })
                  }
                  completeFromPending={async (note) => {
                    const ackOk = await write(
                      `/api/care/tasks/${task.id}`,
                      "PATCH",
                      { version: task.version, state: "ACKNOWLEDGED", note },
                      true
                    );
                    if (!ackOk) return false;
                    return write(`/api/care/tasks/${task.id}`, "PATCH", {
                      version: task.version + 1,
                      state: "DONE",
                      note,
                    });
                  }}
                />
              ))}
            </div>
          )}

          <details className={w.learnMoreDrawer} style={{ marginTop: 18 }}>
            <summary className={w.learnMoreSummary}>
              <span>เงื่อนไขการอัปเดตรอบงานดูแลอัตโนมัติ (Learn More)</span>
              <span className={w.learnMoreBadge}>ดูรายละเอียด</span>
            </summary>
            <div className={w.learnMoreBody}>
              <p className={w.muted} style={{ margin: 0, fontSize: 13 }}>
                ระบบจะตรวจสอบรอบเวลาทุก 5 วินาทีขณะใช้งาน หากปิดระบบ งานจะไม่ถูกบันทึกว่าเสร็จเองโดยอัตโนมัติ บุคลากรทางการแพทย์ต้องเป็นผู้บันทึกผลการปฏิบัติข้างเตียงเสมอ
              </p>
            </div>
          </details>
        </section>
      )}

      {/* Tab 2: Saved & Active Protocols */}
      {tab === "plans" && (
        <section className={w.careCard} aria-label="แผนการดูแลที่บันทึกไว้">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 12, marginBottom: 14 }}>
            <div>
              <span className={w.eyebrow}>RECURRING PROTOCOLS · แผนการดูแลที่บันทึกไว้</span>
              <h3 style={{ margin: "4px 0 4px", fontSize: 18 }}>
                แผนการดูแลและเกณฑ์รอบเวลา · เตียง {patient}
              </h3>
              <p className={w.muted} style={{ margin: 0, fontSize: 13.5 }}>
                ตรวจสอบแผนที่กำลังทำงาน พักแผน หรือเร่งรอบงาน (เปิดใช้งาน {activePlansCount} · ร่าง {draftPlansCount})
              </p>
            </div>
            <button type="button" className={w.primary} onClick={() => setTab("create")}>
              สร้างแผนใหม่
            </button>
          </div>

          <label
            style={{
              padding: "12px 16px",
              background: draftPlansCount > 0 && !confirmed ? "#fff9eb" : "#f8faf8",
              borderRadius: 12,
              border: `1px solid ${draftPlansCount > 0 && !confirmed ? "#e8d4ad" : "#dfe7df"}`,
              marginBottom: 16,
              display: "flex",
              alignItems: "center",
              gap: 10,
              cursor: "pointer",
              fontSize: 13.5,
            }}
          >
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
              style={{ width: 17, height: 17 }}
            />
            <span>
              ฉันตรวจแผนสาธิตที่กำลังจะเปิดใช้แล้ว การกดนี้ไม่ใช่การอนุมัติทางการแพทย์ (จำเป็นสำหรับแผนสถานะ DRAFT)
            </span>
          </label>

          {!visible?.plans.length ? (
            <div style={{ padding: "32px 24px", borderRadius: 16, background: "#f8faf9", border: "1px dashed #c9ded4", textAlign: "center" }}>
              <p className={w.muted} style={{ margin: "0 0 14px", fontSize: 14 }}>
                ยังไม่มีแผนการดูแลสำหรับเตียงนี้ — สามารถเลือกแม่แบบด่วนและสร้างแผนได้ทันที
              </p>
              <button type="button" className={w.primary} onClick={() => setTab("create")}>
                สร้างแผนการดูแลแรกสำหรับเตียง {patient}
              </button>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {visible.plans.map((plan) => {
                const hasOpenTask = visible.tasks.some(
                  (t) => t.title === plan.title && ["PENDING", "ACKNOWLEDGED"].includes(t.state)
                );
                return (
                  <article
                    key={plan.id}
                    style={{
                      padding: "18px 20px",
                      borderRadius: 14,
                      border: "1px solid #dce8e2",
                      background: "#fbfdfc",
                      display: "flex",
                      flexDirection: "column",
                      gap: 10,
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                      <b style={{ fontSize: 15.5, color: "#163a2c" }}>
                        {plan.title} · {states[plan.state]}
                      </b>
                      <span className={w.muted} style={{ fontSize: 12.5 }}>
                        ผู้รับผิดชอบ: <b>{plan.assigned_to}</b> · {plan.interval_minutes ? `รอบทุก ${plan.interval_minutes} นาที` : "ทำครั้งเดียว"} · กำหนดถัดไป: {date(plan.next_due)}
                      </span>
                    </div>

                    <p style={{ margin: 0, fontSize: 14, color: "#254a3b", lineHeight: 1.65 }}>
                      {plan.instructions}
                    </p>

                    <div className={w.actions} style={{ margin: "4px 0 0", gap: 8 }}>
                      {["DRAFT", "PAUSED"].includes(plan.state) && (
                        <button
                          type="button"
                          className={w.primary}
                          disabled={busy || !confirmed}
                          onClick={() =>
                            void write(`/api/care/plans/${plan.id}`, "PATCH", {
                              version: plan.version,
                              state: "ACTIVE",
                              demo_review_confirmed: confirmed,
                            }).then((ok) => {
                              if (ok) {
                                setConfirmed(false);
                                setNotice(`เปิดใช้งานแผน "${plan.title}" เรียบร้อยแล้ว`);
                              }
                            })
                          }
                        >
                          ยืนยันและเปิดใช้
                        </button>
                      )}
                      {["DRAFT", "PAUSED"].includes(plan.state) && !confirmed && (
                        <small style={{ color: "#936511", alignSelf: "center", fontSize: 12 }}>
                          ← กรุณาติ๊กช่องยืนยันด้านบนก่อนกดเปิดใช้
                        </small>
                      )}
                      {plan.state === "ACTIVE" && !hasOpenTask && (
                        <button
                          type="button"
                          className={w.secondary}
                          disabled={busy}
                          onClick={() => void triggerPlanNow(plan)}
                          title="สร้างงานรอบถัดไปทันทีโดยไม่ต้องรอหมดเวลารอบ"
                        >
                          เร่งรอบงานให้ถึงกำหนดตอนนี้
                        </button>
                      )}
                      {plan.state === "ACTIVE" && (
                        <button
                          type="button"
                          className={w.secondary}
                          disabled={busy}
                          onClick={() =>
                            void write(`/api/care/plans/${plan.id}`, "PATCH", {
                              version: plan.version,
                              state: "PAUSED",
                            })
                          }
                        >
                          พักแผนและยกเลิกงานรอบที่ค้าง
                        </button>
                      )}
                    </div>
                  </article>
                );
              })}
            </div>
          )}

          <details className={w.learnMoreDrawer} style={{ marginTop: 18 }}>
            <summary className={w.learnMoreSummary}>
              <span>ประวัติการบันทึกและการปรับปรุงแผน (Learn More · {visible?.events.length ?? 0} รายการ)</span>
              <span className={w.learnMoreBadge}>ดูประวัติ</span>
            </summary>
            <div className={w.learnMoreBody}>
              <p className={w.muted} style={{ margin: "0 0 10px", fontSize: 13 }}>
                หากต้องเปลี่ยนรายละเอียด ให้พักแผนเดิมแล้วสร้างใหม่ เพื่อเก็บประวัติเดิมไว้ใน Audit Trail
              </p>
              {visible?.events.map((event) => (
                <div key={event.id} style={{ padding: "6px 0", borderBottom: "1px solid #eef3f0", fontSize: 13 }}>
                  <b>{event.action}</b> · <span className={w.muted}>{date(event.created_at)} โดย {event.actor}</span>
                  <div style={{ color: "#254a3b" }}>{event.detail}</div>
                </div>
              ))}
            </div>
          </details>
        </section>
      )}

      {/* Tab 3: Dedicated Create Care Plan Form */}
      {tab === "create" && (
        <section className={w.careCard} aria-label="สร้างแผนการดูแลใหม่">
          <div style={{ marginBottom: 16 }}>
            <span className={w.eyebrow}>STEP 1-4 · NEW CARE PLAN CREATION</span>
            <h3 style={{ margin: "4px 0 4px", fontSize: 18 }}>สร้างแผนการดูแลใหม่ · เตียง {patient}</h3>
            <p className={w.muted} style={{ margin: 0, fontSize: 13.5 }}>
              กำหนดแผนการดูแลเฉพาะรายโดยผู้ดูแล พร้อมตัวเลือกแม่แบบด่วน 1 คลิก
            </p>
          </div>

          {/* Step 1: Quick Templates */}
          <div
            style={{
              padding: "16px 18px",
              background: "#f4faf7",
              border: "1px solid #cce0d3",
              borderRadius: 14,
              marginBottom: 20,
            }}
          >
            <span style={{ display: "block", fontWeight: 750, color: "#176e53", marginBottom: 8, fontSize: 13.5 }}>
              ขั้นที่ 1: แม่แบบแผนดูแลด่วน (คลิกเพื่อเติมฟอร์มอัตโนมัติ):
            </span>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {templates.map((t) => (
                <button
                  key={t.title}
                  type="button"
                  disabled={busy}
                  onClick={() => applyTemplate(t)}
                  className={w.carePresetBtn}
                  style={{ fontSize: 13, padding: "8px 14px", minHeight: 40 }}
                >
                  + {t.title} ({t.interval} นาที)
                </button>
              ))}
            </div>
          </div>

          <form ref={formRef} key={patient} onSubmit={create}>
            {/* Step 2: Content */}
            <div style={{ marginBottom: 18 }}>
              <span style={{ display: "block", fontSize: 13, fontWeight: 800, color: "#0e6b52", textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 8 }}>
                ขั้นที่ 2: รายละเอียดงานและการปฏิบัติ
              </span>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 14, marginBottom: 12 }}>
                <label style={{ display: "block", fontSize: 13.5, fontWeight: 700, color: "#163a2c" }}>
                  ชื่องานดูแล
                  <input
                    name="title"
                    required
                    minLength={3}
                    maxLength={120}
                    placeholder="เช่น ตรวจอุปกรณ์วัด หรือ พลิกตัวทุก 2 ชม."
                    className={w.input}
                    style={{ width: "100%", boxSizing: "border-box", marginTop: 4, padding: "10px 12px", borderRadius: 10 }}
                  />
                </label>
                <label style={{ display: "block", fontSize: 13.5, fontWeight: 700, color: "#163a2c" }}>
                  ป้ายชื่อผู้รับผิดชอบ
                  <input
                    name="assigned_to"
                    required
                    minLength={2}
                    maxLength={100}
                    defaultValue="ทีมพยาบาลเวร"
                    placeholder="ทีมพยาบาลเวร"
                    className={w.input}
                    style={{ width: "100%", boxSizing: "border-box", marginTop: 4, padding: "10px 12px", borderRadius: 10 }}
                  />
                </label>
              </div>
              <label style={{ display: "block", fontSize: 13.5, fontWeight: 700, color: "#163a2c" }}>
                รายละเอียดและวิธีการดำเนินการ
                <textarea
                  name="instructions"
                  required
                  minLength={3}
                  maxLength={1000}
                  rows={3}
                  placeholder="ระบุวิธีดำเนินการตามแผนที่ได้รับการประเมินแล้ว..."
                  className={w.careTextarea}
                  style={{ marginTop: 4 }}
                />
              </label>
            </div>

            {/* Step 3: Timing */}
            <div style={{ marginBottom: 18 }}>
              <span style={{ display: "block", fontSize: 13, fontWeight: 800, color: "#0e6b52", textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 8 }}>
                ขั้นที่ 3: รอบเวลาและความถี่
              </span>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 14 }}>
                <label style={{ display: "block", fontSize: 13.5, fontWeight: 700, color: "#163a2c" }}>
                  เริ่มอีกกี่นาที (0 = ทันที)
                  <input
                    name="delay"
                    type="number"
                    min={0}
                    max={525600}
                    step={1}
                    defaultValue={0}
                    required
                    className={w.input}
                    style={{ width: "100%", boxSizing: "border-box", marginTop: 4, padding: "10px 12px", borderRadius: 10 }}
                  />
                </label>
                <label style={{ display: "block", fontSize: 13.5, fontWeight: 700, color: "#163a2c" }}>
                  ทำซ้ำหลังจบงานกี่นาที (0 = ครั้งเดียว)
                  <input
                    name="interval"
                    type="number"
                    min={0}
                    max={10080}
                    step={1}
                    defaultValue={0}
                    required
                    className={w.input}
                    style={{ width: "100%", boxSizing: "border-box", marginTop: 4, padding: "10px 12px", borderRadius: 10 }}
                  />
                </label>
              </div>
            </div>

            {/* Step 4: Activation */}
            <div style={{ marginBottom: 16 }}>
              <span style={{ display: "block", fontSize: 13, fontWeight: 800, color: "#0e6b52", textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 8 }}>
                ขั้นที่ 4: ตรวจสอบและเปิดใช้งาน
              </span>
              <label
                style={{
                  padding: "12px 16px",
                  background: autoActivate ? "#eef8f3" : "#f8faf8",
                  borderRadius: 12,
                  border: `1px solid ${autoActivate ? "#9fd4be" : "#dfe7df"}`,
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  cursor: "pointer",
                  fontSize: 13.5,
                }}
              >
                <input
                  type="checkbox"
                  checked={autoActivate}
                  onChange={(e) => setAutoActivate(e.target.checked)}
                  style={{ width: 17, height: 17 }}
                />
                <span>ยืนยันการตรวจแผนสาธิตและเปิดใช้งานทันทีหลังบันทึก (สร้างงานถึงกำหนดในแท็บ &ldquo;งานที่ต้องทำ&rdquo;)</span>
              </label>
            </div>

            <div style={{ marginTop: 16, display: "flex", gap: 10 }}>
              <button
                disabled={busy}
                type="submit"
                className={w.primary}
                style={{
                  flex: 1,
                  fontWeight: 750,
                  minHeight: 46,
                  borderRadius: 12,
                  fontSize: 15,
                }}
              >
                {autoActivate ? "บันทึกและเปิดใช้งานแผนทันที" : "บันทึกร่าง ยังไม่เปิดใช้งาน"}
              </button>
              <button
                type="button"
                className={w.secondary}
                onClick={() => setTab("tasks")}
              >
                ยกเลิก
              </button>
            </div>

            <details className={w.learnMoreDrawer} style={{ marginTop: 18 }}>
              <summary className={w.learnMoreSummary}>
                <span>คำอธิบายขั้นตอนการตั้งความถี่และเปิดใช้งานแผน (Learn More)</span>
                <span className={w.learnMoreBadge}>ดูขั้นตอน</span>
              </summary>
              <div className={w.learnMoreBody}>
                <p className={w.muted} style={{ margin: 0, fontSize: 13 }}>
                  ระบบไม่กำหนดความถี่ทางการแพทย์สำเร็จรูป ต้องให้ผู้ดูแลกำหนดตามแผนเฉพาะราย หากเลือกบันทึกร่างโดยยังไม่เปิดใช้ สามารถตรวจสอบในแท็บ &ldquo;แผนการดูแล&rdquo; เพื่อติ๊กยืนยันและกดเปิดใช้งานในภายหลังได้
                </p>
              </div>
            </details>
          </form>
        </section>
      )}

      {/* Tab 4: Physiological Care Thresholds & Profile */}
      {tab === "profile" && <CareProfilePanel key={patient} patientId={patient} />}

      {/* Tab 5: Shift Daily Summary */}
      {tab === "daily" && <DailySummaryPanel key={patient} patientId={patient} />}
    </div>
  );
}

function TaskCard({
  task,
  busy,
  update,
  completeFromPending,
}: {
  task: Task;
  busy: boolean;
  update: (state: string, note: string) => Promise<boolean>;
  completeFromPending: (note: string) => Promise<boolean>;
}) {
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

  const handleCompleteImmediate = async (n: string) => {
    const ok = await completeFromPending(n);
    if (ok) {
      setHistory(null);
    }
    return ok;
  };

  return (
    <article
      className={`${w.careTaskCard} ${
        isOverdue
          ? w.careTaskOverdue
          : task.state === "PENDING"
            ? w.careTaskPending
            : w.careTaskAcknowledged
      }`}
    >
      <div className={w.careTaskTop}>
        <b className={w.careTaskTitle}>
          {task.title} · {states[task.state]}
        </b>
        <div className={w.careTaskMeta}>
          <span>ผู้รับผิดชอบ: <b>{task.assigned_to}</b></span>
          <span>· ถึงกำหนด: <b>{date(task.scheduled_at)}</b></span>
          {open && (
            <span
              className={w.pill}
              style={{
                borderColor: isOverdue ? "#ad394b" : "#936511",
                color: isOverdue ? "#ad394b" : "#936511",
                fontWeight: 700,
                fontSize: 11.5,
              }}
            >
              {isOverdue ? `เกินกำหนด ${Math.floor(task.overdue_seconds / 60)} นาที` : "รอดำเนินการ"}
            </span>
          )}
        </div>
      </div>

      <p className={w.careTaskInstruction}>{task.instructions}</p>

      {open ? (
        <>
          <div className={w.carePresetBar}>
            <span className={w.carePresetTitle}>
              ข้อความบันทึกด่วน (คลิกเพื่อเติมข้อความ):
            </span>
            <div className={w.carePresetList}>
              {QUICK_TASK_NOTES.map((preset) => (
                <button
                  key={preset}
                  type="button"
                  disabled={busy}
                  onClick={() => setNote(preset)}
                  className={w.carePresetBtn}
                >
                  + {preset}
                </button>
              ))}
            </div>
          </div>

          <label style={{ margin: 0 }}>
            <span style={{ display: "block", fontSize: 13, fontWeight: 700, color: "#163a2c", marginBottom: 4 }}>
              บันทึกผลการปฏิบัติข้างเตียง / เหตุผลที่ข้าม:
            </span>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={1000}
              rows={2}
              className={w.careTextarea}
              placeholder="กรอกผลการดูแลข้างเตียง หรือคลิกข้อความด่วนด้านบน (จำเป็นต้องระบุก่อนกดบันทึกเสร็จหรือข้ามงาน)..."
            />
          </label>

          <div className={w.actions} style={{ margin: 0, gap: 10 }}>
            {task.state === "PENDING" ? (
              <>
                <button type="button" className={w.secondary} disabled={busy} onClick={() => void handleUpdate("ACKNOWLEDGED", note)}>
                  รับงาน
                </button>
                <button
                  type="button"
                  className={w.primary}
                  disabled={busy || !note.trim()}
                  onClick={() => void handleCompleteImmediate(note)}
                >
                  รับงานและบันทึกว่าเสร็จแล้ว
                </button>
              </>
            ) : (
              <button
                type="button"
                className={w.primary}
                disabled={busy || !note.trim()}
                onClick={() => void handleUpdate("DONE", note)}
              >
                บันทึกว่าเสร็จแล้ว
              </button>
            )}
            <button
              type="button"
              className={w.secondary}
              disabled={busy || !note.trim()}
              onClick={() => void handleUpdate("SKIPPED", note)}
            >
              ข้ามพร้อมเหตุผล
            </button>
            {!note.trim() && (
              <small style={{ color: "#936511", alignSelf: "center", fontSize: 12 }}>
                * คลิกข้อความด่วนหรือพิมพ์ผลข้างต้นเพื่อเปิดปุ่มบันทึก
              </small>
            )}
          </div>
        </>
      ) : (
        <p className={w.muted} style={{ margin: 0, fontSize: 13.5 }}>
          บันทึกผล: <b>{task.note || "ไม่มีบันทึกผล"}</b>
        </p>
      )}

      <div className={w.actions} style={{ marginTop: 2 }}>
        <button type="button" className={w.auditToggleBtn} onClick={toggleHistory}>
          {showHistory ? "ซ่อนประวัติสถานะ" : "ดูประวัติสถานะ (Audit Trail)"}
        </button>
      </div>

      {showHistory && (
        <div className={w.auditTrailSection}>
          {historyLoading && <p className={w.auditLoading}>กำลังดึงข้อมูลประวัติสถานะ…</p>}
          {historyError && (
            <p role="alert" className={w.auditError}>
              {historyError}
            </p>
          )}
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
                    <span>
                      ผู้ดำเนินการ: <b>{item.actor}</b>
                    </span>
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
