"use client";

import { useCallback, useEffect, useState } from "react";
import styles from "./Ward.module.css";
import {
  calculateModifiedNews2,
  formatStaleDuration,
  getStaleEscalationTier,
  LatestVitals,
  PatientAnalysis,
  type MonitorData,
} from "./MonitorPanel";
import { isFreshReading } from "./monitorView";
import WorkflowBoard, { type AlertItem } from "./AlertWorkflow";
import StaffTrendPanel from "./StaffTrendPanel";
import BedsidePanel from "./BedsidePanel";

export type CareHubLiveSummary = {
  patient_id: string;
  doctor?: string;
  assigned_staff_id?: string;
  heart_rate: number;
  spo2: number;
  respiratory_rate?: number | null;
  status: string;
  timestamp: number;
  analysis?: { status?: string; abstain?: boolean };
  patient_profile?: {
    name?: string;
    room_number?: string;
    zone?: string;
    condition?: string;
    mobility?: string;
    doctor?: string;
  };
};

type CareHubDetail = {
  patient_id: string;
  monitor?: MonitorData;
  profile: {
    name: string;
    age: number;
    gender: string;
    condition: string;
    doctor: string;
    assigned_staff_id?: string;
    zone?: string;
    room_number?: string;
    bed_number?: number;
    blood_group?: string;
    mobility?: string;
  };
  ai_assessment: {
    summary: string;
    recommendations: string[];
  };
  risk_model: {
    status: string;
    risk_percent: number | null;
    message: string;
  };
};

type SubTab = "vitals" | "alerts" | "trends" | "notes";

const statusLabels: Record<string, string> = {
  CRITICAL: "เร่งด่วน",
  WARNING: "เฝ้าระวัง",
  NORMAL: "ไม่เข้าเกณฑ์เตือน",
  INVALID_DATA: "ข้อมูลไม่ผ่านคุณภาพ",
  STALE_DATA: "ข้อมูลขาดช่วง",
  ABSTAIN: "งดสรุปผล",
  WAITING: "รอข้อมูล",
};

const QUICK_BEDSIDE_NOTES = [
  "ตรวจสัญญาณชีพซ้ำข้างเตียงแล้ว ผู้ป่วยรู้สึกตัวดี",
  "ขยับและตรวจความกระชับของหัววัด SpO₂ เรียบร้อยแล้ว",
  "พลิกตัวจัดท่านอนศีรษะสูง 30 องศา ตามแผนการดูแล",
  "ส่งต่อเวรให้ติดตามแนวโน้มสัญญาณชีพและอาการเหนื่อยหอบใกล้ชิด",
];

export default function CareHubPanel({
  patients,
  initialPatientId,
  clock,
  chatEnabled,
  roleType,
  openFullRecord,
  openChat,
  openCarePlan,
}: {
  patients: CareHubLiveSummary[];
  initialPatientId?: string;
  clock: number;
  chatEnabled: boolean;
  roleType: "doctor" | "central" | "operator";
  openFullRecord: (patientId: string) => void;
  openChat?: (patientId: string) => void;
  openCarePlan?: (patientId: string) => void;
}) {
  const [selectedId, setSelectedId] = useState<string>(initialPatientId || "");
  const [subTab, setSubTab] = useState<SubTab>("vitals");
  const [filterQuery, setFilterQuery] = useState("");
  const [detail, setDetail] = useState<CareHubDetail | null>(null);
  const [detailError, setDetailError] = useState("");
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [openCareTasks, setOpenCareTasks] = useState<number>(0);
  const [loadedPatientId, setLoadedPatientId] = useState<string>("");
  const [alertsLoading, setAlertsLoading] = useState(false);
  const [busyAlert, setBusyAlert] = useState<number | null>(null);
  const [workflowMessage, setWorkflowMessage] = useState("");
  const [notesByPatient, setNotesByPatient] = useState<Record<string, string>>({});
  const [noteSaved, setNoteSaved] = useState(false);
  const [sbarCopied, setSbarCopied] = useState(false);

  const sortedPatients = [...patients].sort((a, b) => {
    const rank = (p: CareHubLiveSummary) => {
      const fresh = isFreshReading(p, clock);
      const stale = !fresh || p.status === "INVALID_DATA" || p.status === "STALE_DATA" || Boolean(p.analysis?.abstain);
      if (fresh && p.status === "CRITICAL") return 4;
      if (stale) return getStaleEscalationTier(p.timestamp, clock) === "critical" || p.status === "INVALID_DATA" ? 3.5 : 3;
      if (fresh && p.status === "WARNING") return 2;
      return 1;
    };
    return rank(b) - rank(a) || a.patient_id.localeCompare(b.patient_id);
  });

  const filteredPatients = filterQuery.trim()
    ? sortedPatients.filter((p) => {
        const q = filterQuery.trim().toLowerCase();
        return (
          p.patient_id.toLowerCase().includes(q) ||
          (p.patient_profile?.name ?? "").toLowerCase().includes(q) ||
          (p.patient_profile?.room_number ?? "").toLowerCase().includes(q) ||
          (p.doctor ?? p.patient_profile?.doctor ?? "").toLowerCase().includes(q)
        );
      })
    : sortedPatients;

  const preferredId = selectedId || initialPatientId || "";
  const activePatientId =
    (preferredId && patients.some((p) => p.patient_id === preferredId) ? preferredId : "") ||
    filteredPatients[0]?.patient_id ||
    sortedPatients[0]?.patient_id ||
    "";

  const clinicalNote =
    notesByPatient[activePatientId] ??
    (() => {
      if (typeof window === "undefined" || !activePatientId) return "";
      try {
        return localStorage.getItem(`smart-ward-care-hub-note-${activePatientId}`) ?? "";
      } catch {
        return "";
      }
    })();

  const loadPatientCareData = useCallback(async (pid: string, initialLoad = false) => {
    if (!pid) return;
    setDetailError("");
    if (initialLoad) setAlertsLoading(true);
    try {
      const [detailRes, alertsRes, careSummaryRes] = await Promise.all([
        fetch(`/api/patient/${encodeURIComponent(pid)}/details`),
        fetch(`/api/alerts?status=open&patient_id=${encodeURIComponent(pid)}&limit=20`),
        fetch(`/api/care/overdue-summary?patient_id=${encodeURIComponent(pid)}`),
      ]);
      if (detailRes.ok) {
        const d = (await detailRes.json()) as CareHubDetail;
        setDetail(d);
      } else {
        setDetailError("ไม่สามารถโหลดข้อมูลผู้ป่วยรายนี้ได้");
      }
      if (alertsRes.ok) {
        const a = (await alertsRes.json()) as { alerts: AlertItem[] };
        setAlerts(a.alerts ?? []);
      }
      if (careSummaryRes.ok) {
        const cs = (await careSummaryRes.json()) as { total_open?: number };
        setOpenCareTasks(cs.total_open ?? 0);
      }
      setLoadedPatientId(pid);
    } catch {
      setDetailError("เกิดข้อผิดพลาดในการโหลดข้อมูลบริบาลผู้ป่วย");
    } finally {
      if (initialLoad) setAlertsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!activePatientId) return;
    const immediate = window.setTimeout(() => {
      setWorkflowMessage("");
      void loadPatientCareData(activePatientId, true);
    }, 0);
    const timer = window.setInterval(() => void loadPatientCareData(activePatientId, false), 6000);
    return () => {
      window.clearTimeout(immediate);
      window.clearInterval(timer);
    };
  }, [activePatientId, loadPatientCareData]);

  const moveAlert = async (
    alertId: number,
    status: "ACKNOWLEDGED" | "ESCALATED" | "RESOLVED",
    note = "",
    version?: number
  ) => {
    if (busyAlert !== null) return;
    setBusyAlert(alertId);
    setWorkflowMessage("");
    try {
      const res = await fetch(`/api/alerts/${alertId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, note, expected_version: version }),
      });
      const data = (await res.json()) as { detail?: string };
      if (!res.ok) throw new Error(data.detail ?? "อัปเดตสถานะไม่สำเร็จ");
      setWorkflowMessage(`บันทึกสถานะ ${status} เรียบร้อยแล้ว (Audit-logged)`);
      if (activePatientId) await loadPatientCareData(activePatientId, false);
    } catch (e) {
      setWorkflowMessage(e instanceof Error ? e.message : "อัปเดตสถานะไม่สำเร็จ");
    } finally {
      setBusyAlert(null);
    }
  };

  const activeLive = patients.find((p) => p.patient_id === activePatientId);
  const currentDetail = detail?.patient_id === activePatientId ? detail : null;
  const monitorState = currentDetail?.monitor;
  const fresh = isFreshReading(monitorState ?? activeLive, clock);
  const isInvalid =
    monitorState?.status === "INVALID_DATA" ||
    activeLive?.status === "INVALID_DATA" ||
    Boolean(monitorState?.analysis?.abstain) ||
    Boolean(activeLive?.analysis?.abstain);
  const isAbstainOrStale =
    !fresh || isInvalid || monitorState?.status === "STALE_DATA" || activeLive?.status === "STALE_DATA";
  const lastTs = monitorState?.timestamp ?? activeLive?.timestamp;
  const staleText = formatStaleDuration(lastTs, clock);
  const staleTier = getStaleEscalationTier(lastTs, clock);

  const fallbackMonitorState: MonitorData | undefined = activeLive
    ? {
        patient_id: activeLive.patient_id,
        status: activeLive.status,
        heart_rate: activeLive.heart_rate,
        spo2: activeLive.spo2,
        respiratory_rate: activeLive.respiratory_rate ?? undefined,
        timestamp: activeLive.timestamp,
        analysis: {
          status: activeLive.analysis?.status ?? activeLive.status,
          abstain: activeLive.analysis?.abstain,
        },
      }
    : undefined;
  const effectiveMonitor = monitorState ?? fallbackMonitorState;
  const news2 = calculateModifiedNews2(effectiveMonitor, fresh && !isInvalid);

  const profile = currentDetail?.profile;
  const responsibleDoctor =
    profile?.doctor ?? activeLive?.doctor ?? activeLive?.patient_profile?.doctor ?? "ไม่ระบุแพทย์";

  function saveNote() {
    if (!activePatientId) return;
    try {
      localStorage.setItem(`smart-ward-care-hub-note-${activePatientId}`, clinicalNote);
      setNoteSaved(true);
      window.setTimeout(() => setNoteSaved(false), 2500);
    } catch {
      /* ignore storage errors */
    }
  }

  function appendQuickBedsideNote(text: string) {
    if (!activePatientId) return;
    setNotesByPatient((prev) => {
      const current = (prev[activePatientId] ?? clinicalNote).trim();
      const updated = !current ? text : current.includes(text) ? current : `${current} · ${text}`;
      try {
        localStorage.setItem(`smart-ward-care-hub-note-${activePatientId}`, updated);
      } catch {
        /* ignore */
      }
      return { ...prev, [activePatientId]: updated };
    });
    setNoteSaved(true);
    window.setTimeout(() => setNoteSaved(false), 2000);
  }

  function copySbarSummary() {
    if (!activePatientId) return;
    const vitalsLine =
      fresh && !isInvalid
        ? `HR ${monitorState?.heart_rate ?? activeLive?.heart_rate ?? "—"} bpm, SpO₂ ${monitorState?.spo2 ?? activeLive?.spo2 ?? "—"}%, RR ${monitorState?.respiratory_rate ?? activeLive?.respiratory_rate ?? "—"} /นาที (Modified NEWS2: ${news2.total ?? "—"})`
        : `สัญญาณชีพงดสรุปผล (${staleText}) — กรุณาตรวจหัววัดข้างเตียง`;
    const sbar = [
      `[Care Hub SBAR — ${activePatientId}]`,
      `S (Situation): ${activePatientId} (${profile?.name ?? activeLive?.patient_profile?.name ?? "—"}) ห้อง ${profile?.room_number ?? activeLive?.patient_profile?.room_number ?? "—"} · ${vitalsLine}`,
      `B (Background): โรคหลัก ${profile?.condition ?? activeLive?.patient_profile?.condition ?? "—"} · การเคลื่อนไหว ${profile?.mobility ?? activeLive?.patient_profile?.mobility ?? "—"} · แพทย์ผู้รับผิดชอบ: ${responsibleDoctor}`,
      `A (Assessment): ${currentDetail?.ai_assessment?.summary ?? "รอผลวิเคราะห์"}`,
      `R (Recommendation): ${currentDetail?.ai_assessment?.recommendations?.join(" · ") || "ติดตามสัญญาณชีพตามรอบและประเมินข้างเตียง"}${clinicalNote ? ` · โน้ตข้างเตียง: ${clinicalNote}` : ""}`,
    ].join("\n");
    void navigator.clipboard?.writeText(sbar).catch(() => {});
    setSbarCopied(true);
    window.setTimeout(() => setSbarCopied(false), 2500);
  }

  return (
    <div className={styles.careHubContainer}>
      {/* Step 1: Compact Roster Switcher Bar (Full Width, Easy to Scan & Select) */}
      <section className={styles.careHubRosterSection} role="region" aria-label="เลือกผู้ป่วยใน Care Hub">
        <div className={styles.careHubRosterHeader}>
          <div>
            <span className={styles.eyebrow}>CARE HUB · ศูนย์บริบาลผู้ป่วยรายบุคคล</span>
            <h2 className={styles.careHubRosterTitle}>
              เลือกเตียงผู้ป่วยในความดูแล ({filteredPatients.length} เตียง)
            </h2>
          </div>
          <div className={styles.careHubRosterSearchWrap}>
            <input
              type="search"
              aria-label="ค้นหาผู้ป่วยใน Care Hub"
              value={filterQuery}
              onChange={(e) => setFilterQuery(e.target.value)}
              className={styles.searchInput}
              style={{ width: "100%", boxSizing: "border-box", margin: 0 }}
              placeholder="ค้นหารหัสเตียง ชื่อผู้ป่วย ห้อง หรือแพทย์..."
            />
          </div>
        </div>

        <div className={styles.careHubPatientStrip}>
          {filteredPatients.map((p) => {
            const pFresh = isFreshReading(p, clock);
            const pAbstain =
              !pFresh ||
              p.status === "INVALID_DATA" ||
              p.status === "STALE_DATA" ||
              Boolean(p.analysis?.abstain);
            const isSelected = p.patient_id === activePatientId;
            const badge = pAbstain
              ? "งดสรุปผล"
              : p.status === "CRITICAL"
                ? "เร่งด่วน"
                : p.status === "WARNING"
                  ? "เฝ้าระวัง"
                  : "ปกติ";
            const leftColor = pAbstain
              ? "#936511"
              : p.status === "CRITICAL"
                ? "#ad394b"
                : p.status === "WARNING"
                  ? "#b17819"
                  : "#247354";
            const docName = p.doctor ?? p.patient_profile?.doctor ?? "—";
            return (
              <button
                key={p.patient_id}
                type="button"
                onClick={() => setSelectedId(p.patient_id)}
                className={`${styles.careHubPatientItem} ${isSelected ? styles.careHubPatientActive : ""}`}
                style={{ borderLeftColor: isSelected ? undefined : leftColor }}
                aria-pressed={isSelected}
              >
                <div className={styles.careHubPatientTop}>
                  <b>
                    {p.patient_id} · ห้อง {p.patient_profile?.room_number ?? "—"}
                  </b>
                  <span className={styles.pill} style={{ borderColor: leftColor, color: leftColor }}>
                    {badge}
                  </span>
                </div>
                <div className={styles.careHubPatientName}>
                  {p.patient_profile?.name ?? p.patient_profile?.condition ?? "ผู้ป่วยในหอผู้ป่วย"}
                </div>
                <div className={styles.careHubPatientSub}>
                  <span>
                    {pFresh && !pAbstain
                      ? `HR ${p.heart_rate} · SpO₂ ${p.spo2}%`
                      : "รอตรวจสอบสัญญาณข้างเตียง"}
                  </span>
                  <span>แพทย์: {docName}</span>
                </div>
              </button>
            );
          })}
        </div>
      </section>

      {/* Step 2: Active Patient Care Workspace (100% Width — Spacious & Uncrowded) */}
      <div className={styles.careHubMain}>
        {!activePatientId ? (
          <div className={styles.empty}>ยังไม่มีผู้ป่วยในขอบเขตการดูแลของบัญชีนี้</div>
        ) : (
          <>
            {/* Unified Patient Hero Card & Visible Abstention Guardrail */}
            <section className={styles.careHubHeroCard} aria-label="สรุปสถานะผู้ป่วยใน Care Hub">
              <div className={styles.careHubHeroTop}>
                <div className={styles.careHubHeroIdentity}>
                  <span className={styles.eyebrow}>
                    PATIENT CARE WORKSPACE · เตียง {activePatientId} · แพทย์ผู้รับผิดชอบ: {responsibleDoctor}
                  </span>
                  <h3 className={styles.careHubHeroName}>
                    {activePatientId} · {profile?.name ?? activeLive?.patient_profile?.name ?? "กำลังโหลดชื่อ"}{" "}
                    <span className={styles.careHubHeroRoom}>
                      (ห้อง {profile?.room_number ?? activeLive?.patient_profile?.room_number ?? "—"})
                    </span>
                  </h3>
                  <div className={styles.careHubMetaBar}>
                    <span className={styles.cardMetaChip}>
                      โรคหลัก: <b>{profile?.condition ?? activeLive?.patient_profile?.condition ?? "—"}</b>
                    </span>
                    <span className={styles.cardMetaChip}>
                      การเคลื่อนไหว: <b>{profile?.mobility ?? activeLive?.patient_profile?.mobility ?? "—"}</b>
                    </span>
                    <span className={styles.cardMetaChip}>
                      Modified NEWS2:{" "}
                      <b>{news2.ready ? `${news2.total} คะแนน (${news2.riskLabel})` : "งดคำนวณ"}</b>
                    </span>
                  </div>
                </div>

                <div className={styles.careHubHeroActions}>
                  <button
                    type="button"
                    className={styles.secondary}
                    onClick={() => void loadPatientCareData(activePatientId, false)}
                    title="รีเฟรชข้อมูลบริบาลล่าสุด"
                  >
                    รีเฟรช
                  </button>
                  <button type="button" className={styles.secondary} onClick={copySbarSummary}>
                    คัดลอก SBAR
                  </button>
                  {openCarePlan && (
                    <button
                      type="button"
                      className={styles.secondary}
                      onClick={() => openCarePlan(activePatientId)}
                      title={`เปิดแผนและงานดูแลของเตียง ${activePatientId} ในโหมดงานดูแล`}
                    >
                      งานดูแล ({openCareTasks})
                    </button>
                  )}
                  {chatEnabled && roleType !== "central" && openChat && (
                    <button
                      type="button"
                      className={styles.secondary}
                      onClick={() => openChat(activePatientId)}
                      title={`เปิดแชทกับผู้ป่วยเตียง ${activePatientId}`}
                    >
                      แชทผู้ป่วย
                    </button>
                  )}
                  <button type="button" className={styles.primary} onClick={() => openFullRecord(activePatientId)}>
                    เปิดเวชระเบียนเต็ม
                  </button>
                  {sbarCopied && (
                    <span className={styles.sbarCopied} role="status">
                      คัดลอก SBAR แล้ว
                    </span>
                  )}
                </div>
              </div>

              {isAbstainOrStale && (
                <div
                  role="alert"
                  className={`${styles.deviceFactBadge} ${
                    staleTier === "critical" || isInvalid ? styles.badgeCritical : styles.badgeWarning
                  }`}
                  style={{ marginTop: 14, padding: "12px 16px", borderRadius: 12, fontWeight: 700, fontSize: 14 }}
                >
                  สถานะงดสรุปผล AI ชัดเจน (
                  {isInvalid ? "INVALID_DATA · ข้อมูลผิดปกติ/หลุดช่วงสรีรวิทยา" : "STALE_DATA · ข้อมูลขาดช่วง"}) ·{" "}
                  {staleText} — ห้ามตีความว่าผู้ป่วยปลอดภัย กรุณาตรวจสอบหัววัดและผู้ป่วยข้างเตียงทันที
                </div>
              )}
            </section>

            {/* Step 3: Clean 4-Tab Bar (Equal-Width Columns, Concise Labels) */}
            <div className={styles.careHubTabBar} role="tablist" aria-label="งานบริบาลผู้ป่วยใน Care Hub">
              <button
                type="button"
                className={`${styles.careHubTabBtn} ${subTab === "vitals" ? styles.careHubTabBtnActive : ""}`}
                aria-pressed={subTab === "vitals"}
                onClick={() => setSubTab("vitals")}
              >
                <span>สัญญาณชีพ &amp; AI</span>
              </button>
              <button
                type="button"
                className={`${styles.careHubTabBtn} ${subTab === "alerts" ? styles.careHubTabBtnActive : ""}`}
                aria-pressed={subTab === "alerts"}
                onClick={() => setSubTab("alerts")}
              >
                <span>การแจ้งเตือน</span>
                <span className={styles.careHubTabCount}>{alerts.length}</span>
              </button>
              <button
                type="button"
                className={`${styles.careHubTabBtn} ${subTab === "trends" ? styles.careHubTabBtnActive : ""}`}
                aria-pressed={subTab === "trends"}
                onClick={() => setSubTab("trends")}
              >
                <span>กราฟและเซนเซอร์</span>
              </button>
              <button
                type="button"
                className={`${styles.careHubTabBtn} ${subTab === "notes" ? styles.careHubTabBtnActive : ""}`}
                aria-pressed={subTab === "notes"}
                onClick={() => setSubTab("notes")}
              >
                <span>โน้ตและ SBAR</span>
              </button>
            </div>

            {detailError && (
              <p className={styles.error} role="alert">
                {detailError}
              </p>
            )}

            {/* Tab 1: Live Vitals, Modified NEWS2, 30s AI Forecast & Clinical Action Plan */}
            {subTab === "vitals" && (
              <div className={styles.careHubTabContent}>
                <LatestVitals state={effectiveMonitor} now={clock} />

                <div className={styles.careHubVitalsBottomGrid}>
                  <PatientAnalysis state={effectiveMonitor} now={clock} />

                  <section className={styles.box} style={{ padding: "22px 24px", margin: 0 }}>
                    <span className={styles.eyebrow}>CLINICAL ASSESSMENT &amp; FOLLOW-UP · แนวทางดูแลต่อเนื่อง</span>
                    <h3 style={{ margin: "6px 0 10px", fontSize: 18 }}>
                      ข้อเสนอแนะทางคลินิกและการติดตามข้างเตียง
                    </h3>
                    <p style={{ margin: "0 0 14px", lineHeight: 1.7, fontSize: 14.5 }}>
                      {currentDetail?.ai_assessment?.summary ?? "กำลังประมวลผลบริบททางคลินิก..."}
                    </p>
                    {currentDetail?.ai_assessment?.recommendations?.length ? (
                      <ul className={styles.clinicalList} style={{ margin: "0 0 16px", paddingLeft: 20, lineHeight: 1.7 }}>
                        {currentDetail.ai_assessment.recommendations.map((rec) => (
                          <li key={rec} style={{ marginBottom: 6 }}>
                            {rec}
                          </li>
                        ))}
                      </ul>
                    ) : null}

                    <div className={styles.actions} style={{ marginTop: 14, gap: 10 }}>
                      <button type="button" className={styles.secondary} onClick={() => setSubTab("alerts")}>
                        จัดการแจ้งเตือน ({alerts.length})
                      </button>
                      <button type="button" className={styles.secondary} onClick={() => setSubTab("notes")}>
                        บันทึกโน้ต &amp; SBAR
                      </button>
                      {openCarePlan && (
                        <button
                          type="button"
                          className={styles.secondary}
                          onClick={() => openCarePlan(activePatientId)}
                        >
                          จัดการแผนและงานดูแล ({openCareTasks}) →
                        </button>
                      )}
                    </div>

                    <p className={styles.disclaimer} style={{ marginTop: 14 }}>
                      ใช้เพื่อสนับสนุนการตัดสินใจทางคลินิกเท่านั้น (Decision Support Only · Not SaMD) ทุกการดำเนินการต้องได้รับการยืนยันจากบุคลากรทางการแพทย์
                    </p>
                  </section>
                </div>
              </div>
            )}

            {/* Tab 2: Active Alerts & Clinician Acknowledgement */}
            {subTab === "alerts" && (
              <div className={styles.careHubTabContent}>
                <section className={styles.box} style={{ padding: "22px 24px", margin: 0 }}>
                  <div style={{ marginBottom: 14 }}>
                    <span className={styles.eyebrow}>ACTIVE ALERTS · รายการแจ้งเตือนเฉพาะเตียง</span>
                    <h3 style={{ margin: "4px 0 6px", fontSize: 18 }}>
                      รายการแจ้งเตือนที่รอจัดการของ {activePatientId} ({statusLabels[effectiveMonitor?.status ?? ""] ?? effectiveMonitor?.status ?? "—"})
                    </h3>
                    <p className={styles.muted} style={{ margin: 0, fontSize: 13.5 }}>
                      ทุกการกดรับทราบ (Acknowledge) ส่งต่อเวร (Escalate) หรือปิดงาน (Resolve) จะถูกบันทึกใน Audit Log อัตโนมัติ
                    </p>
                  </div>

                  {workflowMessage && (
                    <p className={styles.notice} role="status">
                      {workflowMessage}
                    </p>
                  )}
                  {alertsLoading && loadedPatientId !== activePatientId ? (
                    <p className={styles.empty} role="status">
                      กำลังโหลดรายการแจ้งเตือนของ {activePatientId}…
                    </p>
                  ) : (
                    <WorkflowBoard
                      alerts={alerts}
                      busy={busyAlert}
                      openPatient={openFullRecord}
                      move={moveAlert}
                      now={clock}
                    />
                  )}
                </section>
              </div>
            )}

            {/* Tab 3: Trend Summary & Bedside Sensors */}
            {subTab === "trends" && (
              <div className={styles.careHubTabContent}>
                <StaffTrendPanel patientId={activePatientId} />
                <details className={styles.learnMoreDrawer} open style={{ margin: 0 }}>
                  <summary className={styles.learnMoreSummary}>
                    <span>ข้อมูลเซนเซอร์แผ่นแรงกด ท่าทางบนเตียง และสุขภาพอุปกรณ์ข้างเตียง (Learn More)</span>
                    <span className={styles.learnMoreBadge}>ดูเซนเซอร์ข้างเตียง</span>
                  </summary>
                  <div className={styles.learnMoreBody}>
                    <BedsidePanel patientId={activePatientId} />
                  </div>
                </details>
              </div>
            )}

            {/* Tab 4: Patient Notes & SBAR Shift Handoff */}
            {subTab === "notes" && (
              <div className={styles.careHubTabContent}>
                {/* Card 1: Bedside Notes */}
                <section className={styles.box} style={{ padding: "22px 24px", margin: 0 }}>
                  <span className={styles.eyebrow}>CLINICAL BEDSIDE NOTES · บันทึกข้างเตียงและส่งต่อเวร</span>
                  <h3 style={{ margin: "4px 0 6px", fontSize: 18 }}>บันทึกอาการข้างเตียงสำหรับ {activePatientId}</h3>
                  <p className={styles.muted} style={{ margin: "0 0 14px", fontSize: 13.5 }}>
                    คลิกข้อความด่วนหรือพิมพ์ผลการตรวจข้างเตียง ข้อความที่บันทึกจะถูกนำไปรวมในสรุป SBAR ด้านล่างโดยอัตโนมัติ
                  </p>

                  <div className={styles.quickNoteContainer} role="group" aria-label="ข้อความโน้ตข้างเตียงด่วน">
                    <span className={styles.quickNoteLabel}>ข้อความด่วน (คลิกเพื่อเพิ่มในโน้ตข้างเตียง):</span>
                    <div className={styles.quickChips} style={{ display: "flex", flexWrap: "wrap", gap: 8, margin: "8px 0 14px" }}>
                      {QUICK_BEDSIDE_NOTES.map((chip) => (
                        <button
                          key={chip}
                          type="button"
                          className={styles.quickNoteChip}
                          onClick={() => appendQuickBedsideNote(chip)}
                        >
                          + {chip}
                        </button>
                      ))}
                    </div>
                  </div>

                  <textarea
                    aria-label={`บันทึกข้างเตียงของ ${activePatientId}`}
                    rows={3}
                    value={clinicalNote}
                    onChange={(e) =>
                      setNotesByPatient((prev) => ({
                        ...prev,
                        [activePatientId]: e.target.value,
                      }))
                    }
                    className={styles.input}
                    style={{
                      width: "100%",
                      boxSizing: "border-box",
                      padding: "14px 16px",
                      fontSize: "14.5px",
                      lineHeight: 1.65,
                      borderRadius: 12,
                      margin: "4px 0 14px",
                    }}
                    placeholder="พิมพ์ผลการตรวจข้างเตียง การปรับสายวัด หรือข้อสังเกตเพิ่มเติม..."
                  />

                  <div className={styles.actions} style={{ margin: 0, gap: 12 }}>
                    <button type="button" className={styles.primary} onClick={saveNote}>
                      บันทึกโน้ตผู้ป่วย
                    </button>
                    {noteSaved && (
                      <span className={styles.sbarCopied} role="status">
                        บันทึกโน้ตเรียบร้อยแล้ว
                      </span>
                    )}
                  </div>
                </section>

                {/* Card 2: SBAR Shift Handoff Summary */}
                <section className={styles.box} style={{ padding: "22px 24px", margin: 0 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 12, marginBottom: 16 }}>
                    <div>
                      <span className={styles.eyebrow}>SBAR SHIFT HANDOFF · สรุปข้อมูลส่งต่อเวรมาตรฐาน</span>
                      <h3 style={{ margin: "4px 0 4px", fontSize: 18 }}>โครงสร้างข้อมูล SBAR · {activePatientId}</h3>
                      <p className={styles.muted} style={{ margin: 0, fontSize: 13.5 }}>
                        สรุปสถานการณ์ สัญญาณชีพ ภูมิหลัง การประเมิน และข้อเสนอแนะสำหรับคัดลอกส่งเวร
                      </p>
                    </div>
                    <button type="button" className={styles.secondary} onClick={copySbarSummary}>
                      คัดลอก SBAR ส่งเวร
                    </button>
                  </div>

                  <div className={styles.sbarGrid}>
                    <div className={styles.sbarItem}>
                      <span className={styles.sbarLetter}>S</span>
                      <div>
                        <b>Situation · สถานการณ์ปัจจุบัน</b>
                        <p>
                          {activePatientId} ({profile?.name ?? activeLive?.patient_profile?.name ?? "—"}) ห้อง{" "}
                          {profile?.room_number ?? activeLive?.patient_profile?.room_number ?? "—"} ·{" "}
                          {fresh && !isInvalid
                            ? `HR ${monitorState?.heart_rate ?? activeLive?.heart_rate ?? "—"} bpm, SpO₂ ${monitorState?.spo2 ?? activeLive?.spo2 ?? "—"}%, RR ${monitorState?.respiratory_rate ?? activeLive?.respiratory_rate ?? "—"} /นาที (Modified NEWS2: ${news2.total ?? "—"})`
                            : `สัญญาณชีพงดสรุปผล (${staleText})`}
                        </p>
                      </div>
                    </div>
                    <div className={styles.sbarItem}>
                      <span className={styles.sbarLetter}>B</span>
                      <div>
                        <b>Background · ภูมิหลังและแพทย์เจ้าของไข้</b>
                        <p>
                          โรคหลัก: {profile?.condition ?? activeLive?.patient_profile?.condition ?? "—"} · การเคลื่อนไหว:{" "}
                          {profile?.mobility ?? activeLive?.patient_profile?.mobility ?? "—"} · แพทย์: {responsibleDoctor}
                        </p>
                      </div>
                    </div>
                    <div className={styles.sbarItem}>
                      <span className={styles.sbarLetter}>A</span>
                      <div>
                        <b>Assessment · การประเมินทางคลินิก</b>
                        <p>{currentDetail?.ai_assessment?.summary ?? "กำลังประมวลผลข้อมูลทางคลินิก..."}</p>
                      </div>
                    </div>
                    <div className={styles.sbarItem}>
                      <span className={styles.sbarLetter}>R</span>
                      <div>
                        <b>Recommendation · ข้อเสนอแนะและโน้ตข้างเตียง</b>
                        <p>
                          {currentDetail?.ai_assessment?.recommendations?.join(" · ") ||
                            "ติดตามสัญญาณชีพตามรอบและประเมินอาการข้างเตียง"}
                          {clinicalNote ? ` · [โน้ตข้างเตียง]: ${clinicalNote}` : ""}
                        </p>
                      </div>
                    </div>
                  </div>
                </section>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
