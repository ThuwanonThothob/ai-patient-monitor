"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent, RefObject } from "react";
import MonitorPanel, { LatestVitals, PatientAnalysis, type MonitorData } from "./MonitorPanel";
import { isFreshReading } from "./monitorView";
import ResearchPanel from "./ResearchPanel";
import styles from "./Ward.module.css";
import Icon from "./Icon";
import AgentAssistant from './AgentAssistant';
import NotificationPanel from "./NotificationPanel";
import EvidencePanel from "./EvidencePanel";
import CarePanel from "./CarePanel";
import AgentPanel from "./AgentPanel";
import CareMessages from './CareMessages';
import CareChat from './CareChat';
import OperationsPanel from './OperationsPanel';
import WorkflowBoard, { type AlertItem } from "./AlertWorkflow";
import VitalCharts from './VitalCharts';
import StaffTrendPanel from './StaffTrendPanel';
import BedsidePanel from './BedsidePanel';

const API_URL = "";
type Section = "overview" | "chat" | "triage" | "patients" | "alerts" | "ai" | "research" | "reports" | "notifications" | "evidence" | "care";
type Zone = "ALL" | "A" | "B" | "C" | "HOME";
type WorkflowStatus = "open" | "NEW" | "ACKNOWLEDGED" | "ESCALATED" | "RESOLVED";
type ChatItem = { sender: "user" | "ai"; text: string };

type PatientProfile = {
  name: string; age: number; gender: string; condition: string; doctor: string;
  zone?: string; room_number?: string; bed_number?: number; blood_group?: string;
  diagnoses?: string[]; mobility?: string; respiratory_rate?: number; sleep_hours?: number;
  sleep_quality?: string; blood_glucose_mg_dl?: number; cholesterol_mg_dl?: number; ecg_rhythm?: string;
};
type History = { time?: string; heart_rate: number; spo2: number; respiratory_rate?: number | null; blood_glucose?: number | null; ecg_rhythm?: string | null; is_anomaly?: boolean };
type LivePatient = { patient_id: string; patient_profile?: PatientProfile; heart_rate: number; spo2: number; respiratory_rate?: number | null; blood_glucose?: number | null; ecg_rhythm?: string | null; status: string; alert_message: string; risk_percent?: number | null; is_anomaly?: boolean; timestamp: number; history: History[] };
type Snapshot = { generated_at: string; reading_count: number; critical_count: number; warning_count: number; patient_count: number; registered_patient_count?: number; zones?: { zone: string; label: string; registered_patients: number; patients_with_readings: number; critical_count: number }[]; patients: { patient_id: string; zone?: string; room_number?: string; avg_hr: number; min_spo2: number; critical_count: number }[] };
type DirectoryPatient = { patient_id: string; name: string; zone: string; room_number: string; bed_number: number; condition: string; mobility: string; doctor: string };
type Alert = AlertItem;
type TriagePatient = { patient_id: string; zone: string; room_number: string; condition: string; mobility: string; triage_level: "CRITICAL" | "ATTENTION" | "ROUTINE"; monitor_status: string; open_alerts: number; priority_reason: string; latest: { timestamp?: number; status?: string; heart_rate?: number | null; spo2?: number | null; respiratory_rate?: number | null } };
type TimelineEvent = { type: string; timestamp: number; title: string; detail: string; severity: string };
type RiskAssessment = { status: string; risk_percent: number | null; risk_band?: string; threshold?: number; feature_coverage?: number; history_points?: number; missing_parameters?: string[]; model_version?: string; endpoint?: string; research_only: boolean; message: string };
type ModelStatus = { available: boolean; status: string; model_version?: string; endpoint?: string; profile?: string; holdout_test_metrics?: { roc_auc?: number | null; pr_auc?: number | null; brier_score?: number | null; sensitivity?: number; specificity?: number; ppv?: number; npv?: number; threshold?: number }; research_only_notice?: string; message?: string };
type ModelBenchmark = { model_version?: string; profile?: string; feature_count?: number; endpoint?: string; runtime_compatible: boolean; holdout_test_metrics?: ModelStatus["holdout_test_metrics"] };
type Detail = { monitor?: MonitorData; profile: PatientProfile; latest_clinical?: History | null; history: History[]; ai_assessment: { summary: string; recommendations: string[] }; risk_model: RiskAssessment; forecast: { predicted_hr: number | null; predicted_spo2: number | null } };
type Audit = { id: number; patient_id: string; action: string; actor: string; detail?: string; created_at: number };
type Evaluation = { total: number; passed: number; failed: number; clinical_validation: boolean; note: string; results: { id: string; label: string; expected_severity: string | null; actual_severity: string | null; passed: boolean }[] };

const nav: { id: Section; icon: string; label: string; detail: string }[] = [
  { id: "overview", icon: "⌂", label: "ภาพรวม", detail: "สถานะหอผู้ป่วยแบบ real-time" },
  { id: "chat", icon: "chat", label: "แชทแพทย์-ผู้ป่วย", detail: "แชทข้อความสองทางแบบเรียลไทม์ระหว่างแพทย์และผู้ป่วย" },
  { id: "triage", icon: "⌁", label: "ลำดับการดูแล", detail: "เริ่มจากผู้ป่วยที่ต้องตรวจสอบก่อน แล้วเปิดรายละเอียดเพื่อประเมิน" },
  { id: "patients", icon: "♙", label: "ผู้ป่วย", detail: "ค้นหา Patient ID, โซน และห้อง" },
  { id: "care", icon: "✓", label: "แผนดูแล", detail: "แผนเฉพาะรายที่คนกำหนด · งานถึงกำหนด · บันทึกผลและส่งต่อ" },
  { id: "evidence", icon: "✦", label: "พิสูจน์ AI", detail: "ดูข้อมูลเข้า ผลโมเดล เฉลยจริง และข้อผิดพลาดอย่างตรวจสอบได้" },
  { id: "alerts", icon: "!", label: "รายการแจ้งเตือน", detail: "ตรวจสอบข้อมูล → รับทราบ → ส่งต่อประเมิน → ปิดงาน" },
  { id: "notifications", icon: "!", label: "แจ้งเตือนมือถือ", detail: "เชื่อมต่อโทรศัพท์ ทดสอบการแจ้งเตือน และตรวจสถานะการส่ง" },
  { id: "ai", icon: "✦", label: "AI และประวัติระบบ", detail: "ผลวิเคราะห์ ที่มาของโมเดล และประวัติการดำเนินการ" },
  { id: "research", icon: "⌘", label: "AI Research Lab", detail: "ข้อมูลจริง · เทียบโมเดล · ตรวจหลักฐานย้อนหลัง" },
  { id: "reports", icon: "▤", label: "รายงาน", detail: "Text และ Word report" },
];
const navGroups: { label: string; icon: string; sections: Section[] }[] = [
  { label: 'ภาพรวม', icon: 'overview', sections: ['overview'] },
  { label: 'แชทแพทย์-ผู้ป่วย', icon: 'chat', sections: ['chat'] },
  { label: 'ผู้ป่วย', icon: 'patients', sections: ['patients', 'care'] },
  { label: 'งานดูแล', icon: 'alerts', sections: ['triage', 'alerts'] },
  { label: 'AI', icon: 'ai', sections: ['ai', 'evidence', 'research'] },
  { label: 'เพิ่มเติม', icon: 'reports', sections: ['reports', 'notifications'] },
];

function color(level: string) {
  if (level === "critical" || level === "CRITICAL") return "#ad394b";
  if (level === "warning" || level === "WARNING" || level === "ATTENTION") return "#936511";
  if (["NORMAL", "ROUTINE"].includes(level)) return "#247354";
  return "#66766e";
}
const labels: Record<string, string> = { CRITICAL: "เร่งด่วน", WARNING: "เฝ้าระวัง", ATTENTION: "ควรตรวจสอบ", NORMAL: "ไม่เข้าเกณฑ์เตือน", ROUTINE: "ตามรอบ", NEW: "รอรับทราบ", ACKNOWLEDGED: "รับทราบแล้ว", ESCALATED: "ส่งต่อประเมิน", RESOLVED: "ปิดงานแล้ว", STALE_DATA: "ข้อมูลขาดช่วง", WAITING: "รอข้อมูล" };
function timestamp(value?: number | null) {
  return value ? new Date(value * 1000).toLocaleString("th-TH", { hour12: false, month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
}
function url(path: string) { return API_URL + path; }
const SOUND_STORAGE_KEY = "smart-ward-sound-enabled";
const NIGHT_SHIFT_STORAGE_KEY = "smart-ward-night-shift";
let lastChimeAt = 0;
function playCriticalChime(force = false) {
  if (typeof window === "undefined") return;
  const now = Date.now();
  if (!force && now - lastChimeAt < 8000) return;
  lastChimeAt = now;
  try {
    const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(880, ctx.currentTime);
    osc.frequency.setValueAtTime(660, ctx.currentTime + 0.14);
    gain.gain.setValueAtTime(0.001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.18, ctx.currentTime + 0.03);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.34);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.35);
    osc.onended = () => { void ctx.close().catch(() => {}); };
  } catch { /* Browser autoplay policy or unsupported audio device */ }
}

export default function Dashboard() {
  const [active, setActive] = useState<Section>("overview");
  const [showMessages, setShowMessages] = useState(false);
  const [soundEnabled, setSoundEnabled] = useState(() => {
    try { return typeof window !== "undefined" && localStorage.getItem(SOUND_STORAGE_KEY) === "1"; } catch { return false; }
  });
  const [nightShift, setNightShift] = useState(() => {
    try {
      if (typeof window === "undefined") return false;
      const saved = localStorage.getItem(NIGHT_SHIFT_STORAGE_KEY);
      return saved === "1" || saved === "true";
    } catch { return false; }
  });
  const [liveFilter, setLiveFilter] = useState<"ALL" | "CRITICAL" | "WARNING">("ALL");
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [live, setLive] = useState<Record<string, LivePatient>>({});
  const [connected, setConnected] = useState(false);
  const [directory, setDirectory] = useState<DirectoryPatient[]>([]);
  const [directoryTotal, setDirectoryTotal] = useState(0);
  const [directoryLoading, setDirectoryLoading] = useState(false);
  const [directoryPage, setDirectoryPage] = useState(1);
  const [directoryError, setDirectoryError] = useState("");
  const [triageError, setTriageError] = useState("");
  const [alertError, setAlertError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [clock, setClock] = useState(0);
  const [monitorError, setMonitorError] = useState("");
  const [directoryZone, setDirectoryZone] = useState<Zone>("ALL");
  const [search, setSearch] = useState("");
  const [triage, setTriage] = useState<TriagePatient[]>([]);
  const [triageZone, setTriageZone] = useState<Zone>("ALL");
  const [triagePriority, setTriagePriority] = useState("all");
  const [bedboundOnly, setBedboundOnly] = useState(false);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [alertStatus, setAlertStatus] = useState<WorkflowStatus>("open");
  const [alertZone, setAlertZone] = useState<Zone>("ALL");
  const [alertPage, setAlertPage] = useState(0);
  const [alertMore, setAlertMore] = useState(false);
  const [alertPatient, setAlertPatient] = useState("");
  const [alertsLoading, setAlertsLoading] = useState(false);
  const [alertsLoadedFilter, setAlertsLoadedFilter] = useState('');
  const [workflowMessage, setWorkflowMessage] = useState("");
  const [busyAlert, setBusyAlert] = useState<number | null>(null);
  const [audit, setAudit] = useState<Audit[]>([]);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [modelStatus, setModelStatus] = useState<ModelStatus | null>(null);
  const [modelBenchmarks, setModelBenchmarks] = useState<ModelBenchmark[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [chat, setChat] = useState<ChatItem[]>([]);
  const [input, setInput] = useState("");
  const [chatting, setChatting] = useState(false);
  const [careMessage, setCareMessage] = useState("");
  const [careBusy, setCareBusy] = useState<string | null>(null);
  const [workflowRevision, setWorkflowRevision] = useState(0);
  const endRef = useRef<HTMLDivElement>(null);
  const selectedRef = useRef<string | null>(null);
  const soundEnabledRef = useRef(soundEnabled);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const detailRequest = useRef(0);
  const directoryRequest = useRef(0);
  const summaryRequest = useRef(0);
  const alertsRequest = useRef(0);
  const triageRequest = useRef(0);
  useEffect(() => { soundEnabledRef.current = soundEnabled; }, [soundEnabled]);
  useEffect(() => { window.scrollTo({ top: 0, behavior: "instant" }); }, [active]);
  useEffect(() => {
    const timer = setInterval(() => setClock(Date.now() / 1000), 1000);
    const initial = setTimeout(() => {
      const section = new URLSearchParams(location.search).get("section");
      if (nav.some((item) => item.id === section)) setActive(section as Section);
    }, 0);
    return () => { clearInterval(timer); clearTimeout(initial); };
  }, []);
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target && (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || target.isContentEditable)) return;
      event.preventDefault();
      setActive("patients");
      setTimeout(() => searchInputRef.current?.focus(), 40);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
  function toggleSound() {
    setSoundEnabled((prev) => {
      const next = !prev;
      try { localStorage.setItem(SOUND_STORAGE_KEY, next ? "1" : "0"); } catch { /* ignore */ }
      if (next) playCriticalChime(true);
      return next;
    });
  }
  function toggleNightShift() {
    setNightShift((prev) => {
      const next = !prev;
      try { localStorage.setItem(NIGHT_SHIFT_STORAGE_KEY, next ? "1" : "0"); } catch { /* ignore */ }
      return next;
    });
  }
  function closePatient() { selectedRef.current = null; detailRequest.current += 1; setSelected(null); }

  const loadSnapshot = useCallback(async () => {
    const revision = ++summaryRequest.current;
    if (["research", "notifications", "evidence", "care"].includes(active)) return;
    try {
      const response = await fetch(url("/api/dashboard/" + active));
      if (!response.ok) throw new Error("snapshot unavailable");
      const data = await response.json() as { snapshot: Snapshot };
      if (revision === summaryRequest.current) { setSnapshot(data.snapshot); }
    } catch { /* retain current snapshot on transient error */ }
  }, [active]);
  const loadDirectory = useCallback(async () => {
    const revision = ++directoryRequest.current;
    const query = new URLSearchParams({ page: String(directoryPage), page_size: "20" });
    if (directoryZone !== "ALL") query.set("zone", directoryZone);
    if (search.trim()) query.set("search", search.trim());
    setDirectoryLoading(true);
    try {
      const response = await fetch(url("/api/patients?" + query.toString()));
      if (!response.ok) throw new Error("directory unavailable");
      const data = await response.json() as { total: number; patients: DirectoryPatient[] };
      if (revision === directoryRequest.current) { setDirectory(data.patients); setDirectoryTotal(data.total); setDirectoryError(""); }
    } catch { if (revision === directoryRequest.current) { setDirectory([]); setDirectoryError("โหลดทะเบียนไม่สำเร็จ กรุณาลองรีเฟรช ไม่ใช่ผลค้นหาว่าง"); } } finally { if (revision === directoryRequest.current) setDirectoryLoading(false); }
  }, [directoryZone, directoryPage, search]);
  const loadTriage = useCallback(async () => {
    const revision = ++triageRequest.current;
    const query = new URLSearchParams({ priority: triagePriority });
    if (triageZone !== "ALL") query.set("zone", triageZone);
    if (bedboundOnly) query.set("mobility", "bedbound");
    try {
      const response = await fetch(url("/api/triage?" + query.toString()));
      if (!response.ok) throw new Error("triage unavailable");
      const data = await response.json() as { patients: TriagePatient[] };
      if (revision !== triageRequest.current) return;
      setTriage(data.patients);
      setTriageError("");
    } catch { if (revision === triageRequest.current) { setTriage([]); setTriageError("โหลดลำดับการดูแลไม่สำเร็จ กรุณาลองใหม่"); } }
  }, [bedboundOnly, triagePriority, triageZone]);
  const loadAlerts = useCallback(async () => {
    const revision = ++alertsRequest.current;
    setAlertsLoading(true);
    const query = new URLSearchParams({ status: alertStatus, limit: "20", offset: String(alertPage * 20) });
    if (alertPatient.trim()) query.set('patient_id', alertPatient.trim().toUpperCase());
    if (alertZone !== "ALL") query.set("zone", alertZone);
    try {
      const response = await fetch(url("/api/alerts?" + query.toString()));
      if (!response.ok) throw new Error("alerts unavailable");
      const data = await response.json() as { alerts: Alert[]; has_more: boolean };
      if (revision !== alertsRequest.current) return;
      setAlerts(data.alerts); setAlertMore(data.has_more);
      setAlertsLoadedFilter(JSON.stringify([alertStatus, alertZone, alertPage, alertPatient]));
      setAlertError("");
    } catch { if (revision === alertsRequest.current) { setAlerts([]); setAlertError("โหลดแจ้งเตือนไม่สำเร็จ อย่าตีความว่าไม่มีงานค้าง"); } }
    finally { if (revision === alertsRequest.current) setAlertsLoading(false); }
  }, [alertStatus, alertZone, alertPage, alertPatient]);
  const loadAudit = useCallback(async () => {
    try {
      const results = await Promise.all([fetch(url("/api/agent/audit?limit=20")), fetch(url("/api/evaluation/alert-workflow")), fetch(url("/api/ml/model-status")), fetch(url("/api/ml/benchmarks"))]);
      if (results[0].ok) setAudit((await results[0].json() as { events: Audit[] }).events);
      if (results[1].ok) setEvaluation(await results[1].json() as Evaluation);
      if (results[2].ok) setModelStatus(await results[2].json() as ModelStatus);
      if (results[3].ok) setModelBenchmarks((await results[3].json() as { models: ModelBenchmark[] }).models);
    } catch { setAudit([]); setEvaluation(null); setModelStatus(null); setModelBenchmarks([]); }
  }, []);

  useEffect(() => { const timer = window.setTimeout(() => void loadSnapshot(), 0); return () => window.clearTimeout(timer); }, [loadSnapshot]);
  useEffect(() => { const timer = window.setInterval(() => { void loadSnapshot(); if (active === "triage") void loadTriage(); if (active === "alerts") void loadAlerts(); if (active === "ai") void loadAudit(); }, 15000); return () => window.clearInterval(timer); }, [active, loadSnapshot, loadTriage, loadAlerts, loadAudit]);
  useEffect(() => { if (active === "patients") { const timer = window.setTimeout(() => void loadDirectory(), 150); return () => window.clearTimeout(timer); } }, [active, loadDirectory]);
  useEffect(() => { if (active === "triage") { const timer = window.setTimeout(() => void loadTriage(), 0); return () => window.clearTimeout(timer); } }, [active, loadTriage, workflowRevision]);
  useEffect(() => { if (active === "alerts") { const timer = window.setTimeout(() => void loadAlerts(), 0); return () => window.clearTimeout(timer); } }, [active, loadAlerts, workflowRevision]);
  useEffect(() => { if (active === "ai") { const timer = window.setTimeout(() => void loadAudit(), 0); return () => window.clearTimeout(timer); } }, [active, loadAudit, workflowRevision]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [chat]);
  useEffect(() => {
    let stopped = false, attempt = 0;
    let ws: WebSocket | undefined, retry: ReturnType<typeof setTimeout>;
    function connect() {
      if (stopped) return;
      ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/vitals`);
      ws.onopen = () => { attempt = 0; setConnected(true); };
      ws.onclose = () => { if (!stopped) { setConnected(false); retry = setTimeout(connect, Math.min(30000, 1000 * 2 ** attempt++)); } };
      ws.onerror = () => { setConnected(false); ws?.close(); };
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as LivePatient & { type?: string };
          if (data.type === "agent_alert") {
            if (soundEnabledRef.current) playCriticalChime();
            setWorkflowRevision((revision) => revision + 1);
            return;
          }
          if (!/^[ABC](00[1-9]|01[0-9]|020)$/.test(data.patient_id) || !Number.isFinite(data.timestamp)) return;
          const point: History = { time: new Date(data.timestamp * 1000).toLocaleTimeString([], { hour12: false }), heart_rate: data.heart_rate, spo2: data.spo2, respiratory_rate: data.respiratory_rate };
          setLive((current) => {
            if ((current[data.patient_id]?.timestamp ?? 0) > data.timestamp) return current;
            if (data.status === "CRITICAL" && current[data.patient_id]?.status !== "CRITICAL" && soundEnabledRef.current) {
              playCriticalChime();
            }
            return { ...current, [data.patient_id]: { ...data, history: [...(current[data.patient_id]?.history ?? []), point].slice(-30) } };
          });
        } catch { /* Ignore malformed transport messages, not the connection. */ }
      };
    }
    connect();
    return () => { stopped = true; clearTimeout(retry); ws?.close(); };
  }, []);

  const openPatient = async (patientId: string) => {
    selectedRef.current = patientId;
    const revision = ++detailRequest.current;
    setDetailError(""); setChatting(false); setCareBusy(null);
    setSelected(patientId); setDetail(null); setTimeline([]); setInput(""); setCareMessage("");
    setChat([{ sender: "ai", text: "ฉันช่วยสรุปข้อมูลผู้ป่วยรายนี้จากข้อมูลสังเคราะห์ได้ เลือกคำถามด่วนหรือพิมพ์คำถามได้เลย" }]);
    try {
      const responses = await Promise.all([fetch(url("/api/patient/" + patientId + "/details")), fetch(url("/api/patient/" + patientId + "/timeline?limit=50"))]);
      if (!responses[0].ok) throw new Error("detail unavailable");
      const loaded = await responses[0].json() as Detail;
      const events = responses[1].ok ? (await responses[1].json() as { events: TimelineEvent[] }).events : [];
      if (revision === detailRequest.current) { setDetail(loaded); setTimeline(events); }
    } catch { if (revision === detailRequest.current) setDetailError("ไม่สามารถโหลดข้อมูลผู้ป่วยได้ กรุณาปิดแล้วเปิดอีกครั้ง"); }
  };
  const refreshTimeline = async (patientId: string) => {
    const response = await fetch(url("/api/patient/" + patientId + "/timeline?limit=50"));
    if (response.ok) { const data = await response.json() as { events: TimelineEvent[] }; if (selectedRef.current === patientId) setTimeline(data.events); }
  };
  const moveAlert = async (alertId: number, status: "ACKNOWLEDGED" | "ESCALATED" | "RESOLVED", note = "", version?: number) => {
    if (busyAlert !== null) return;
    if (status === "RESOLVED" && !window.confirm("ยืนยันว่าตรวจสอบรายการนี้แล้ว และต้องการปิดงาน? การปิดงานไม่ได้หมายความว่าผู้ป่วยปลอดภัยโดยอัตโนมัติ")) return;
    setBusyAlert(alertId); setWorkflowMessage("");
    try {
      const response = await fetch(url("/api/alerts/" + alertId), { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status, note, expected_version: version }) });
      const data = await response.json() as { message?: string; detail?: string };
      if (!response.ok) throw new Error(data.detail ?? "อัปเดตไม่สำเร็จ");
      setWorkflowMessage(`เปลี่ยนเป็น “${labels[status]}” แล้ว · ไม่มีการติดต่อแพทย์หรือสั่งรถจริง`);
      await Promise.all([loadAlerts(), loadTriage(), loadAudit()]);
      if (selected) await refreshTimeline(selected);
    } catch (e) { setWorkflowMessage(e instanceof Error ? e.message : "ไม่สามารถอัปเดต workflow ได้"); } finally { setBusyAlert(null); }
  };
  const sendChat = async (event: FormEvent) => {
    event.preventDefault();
    if (!selected || !input.trim() || chatting) return;
    const revision = detailRequest.current;
    const message = input.trim(); setInput(""); setChat((items) => [...items, { sender: "user", text: message }]); setChatting(true);
    try {
      const response = await fetch(url("/api/patient/" + selected + "/chat"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message }) });
      const data = await response.json() as { reply?: string };
      if (!response.ok) throw new Error();
      if (revision === detailRequest.current) setChat((items) => [...items, { sender: "ai", text: data.reply ?? "AI ไม่ได้ส่งคำตอบกลับมา" }]);
    } catch { if (revision === detailRequest.current) setChat((items) => [...items, { sender: "ai", text: "ไม่สามารถเชื่อมต่อ AI ได้ในขณะนี้" }]); } finally { if (revision === detailRequest.current) setChatting(false); }
  };
  const createCareRequest = async (type: "doctor" | "ambulance") => {
    if (!selected || careBusy) return;
    const revision = detailRequest.current;
    setCareBusy(type); setCareMessage("");
    try {
      const response = await fetch(url("/api/patient/" + selected + "/care-requests"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ request_type: type }) });
      const data = await response.json() as { message?: string; detail?: string };
      if (!response.ok) throw new Error(data.detail ?? "สร้างคำขอไม่สำเร็จ");
      if (revision === detailRequest.current) setCareMessage(data.message ?? "สร้างคำขอแล้ว");
      await refreshTimeline(selected);
    } catch { if (revision === detailRequest.current) setCareMessage("ไม่สามารถสร้างคำขอได้"); } finally { if (revision === detailRequest.current) setCareBusy(null); }
  };

  useEffect(() => {
    const abort = new AbortController();
    async function refresh() {
      try {
        const response = await fetch("/api/monitor/patients", { signal: abort.signal });
        if (!response.ok) throw new Error();
        const data = await response.json() as { patients: LivePatient[] };
        if (abort.signal.aborted) return;
        setLive((current) => Object.fromEntries(data.patients.map((p) => [p.patient_id, (current[p.patient_id]?.timestamp ?? 0) > (p.timestamp ?? 0) ? current[p.patient_id] : { ...p, history: current[p.patient_id]?.history ?? p.history ?? [] }])));
        setMonitorError("");
        if (selected) {
          const detailResponse = await fetch("/api/patient/" + selected + "/details", { signal: abort.signal });
          if (detailResponse.ok) { const loaded = await detailResponse.json(); if (!abort.signal.aborted && selectedRef.current === selected) { setDetail(loaded); setDetailError(""); } }
        }
      } catch { if (!abort.signal.aborted) setMonitorError("เชื่อมต่อข้อมูลล่าสุดไม่ได้ ค่าที่เกิน 15 วินาทีจะไม่ถูกนับเป็นข้อมูลปัจจุบัน"); }
    }
    void refresh(); const timer = setInterval(refresh, 5000);
    return () => { abort.abort(); clearInterval(timer); };
  }, [selected]);

  const currentNav = nav.find((item) => item.id === active)!;
  const fresh = Object.fromEntries(Object.entries(live).filter(([, patient]) => isFreshReading(patient, clock)));
  const currentCritical = Object.values(fresh).filter((patient) => patient.status === "CRITICAL").length;
  const currentWarning = Object.values(fresh).filter((patient) => patient.status === "WARNING").length;
  const filteredFresh = liveFilter === "ALL" ? fresh : Object.fromEntries(Object.entries(fresh).filter(([, patient]) => patient.status === liveFilter));
  const registeredCount = snapshot?.registered_patient_count;
  const zoneCards = (snapshot?.zones ?? []).map((zone) => ({ ...zone, patients_with_readings: Object.values(fresh).filter(patient => patient.patient_profile?.zone === zone.zone).length, critical_count: Object.values(fresh).filter(patient => patient.patient_profile?.zone === zone.zone && patient.status === "CRITICAL").length }));
  let content: React.ReactNode;
  if (active === "overview") content = <>
    <div className={styles.metrics}>
      <Metric tone="total" label="ผู้ป่วยในความดูแล" value={registeredCount ?? "—"} note="เฉพาะทะเบียนที่บัญชีนี้เข้าถึงได้" />
      <Metric tone="fresh" label="มีข้อมูลล่าสุด" value={Object.keys(fresh).length} note="ได้รับข้อมูลไม่เกิน 15 วินาที" />
      <Metric tone="critical" label="ต้องตรวจสอบเร่งด่วน" value={currentCritical} note="จำนวนเตียงปัจจุบัน ไม่ใช่ยอดสะสม" />
      <Metric tone="warning" label="ควรเฝ้าระวัง" value={currentWarning} note="จากค่าสัญญาณชีพล่าสุด" />
    </div>
    <div className={styles.priorityBanner}><div><b>{currentCritical ? `${currentCritical} เตียงมีค่าเข้าเกณฑ์เร่งด่วน` : "เริ่มต้นเวรด้วยการตรวจลำดับการดูแล"}</b><p>ตรวจทั้งสัญญาณชีพและงานค้าง · {registeredCount === undefined ? 'กำลังตรวจจำนวนผู้ป่วย' : `${Math.max(0, registeredCount - Object.keys(fresh).length)} คนยังไม่มีข้อมูลใหม่`} ข้อมูลขาดไม่ได้แปลว่าปลอดภัย</p></div><button className={styles.secondary} onClick={() => setActive("triage")}>ดูลำดับการดูแล <Icon name="arrow" size={17} /></button></div>
    <OperationsPanel alerts={() => setActive('alerts')} messages={() => { setShowMessages(true); setActive('triage'); }} chat={() => setActive('chat')} />
    <div className={styles.sectionRow}><div><h2 className={styles.h2}>สัญญาณชีพล่าสุดรายเตียง</h2><p className={styles.muted}>แสดงไม่เกิน 12 เตียง เรียงจากระดับที่ควรตรวจสอบก่อน · คลิกที่การ์ดเพื่อเปิดเวชระเบียนและกราฟแนวโน้ม</p></div><button className={styles.link} onClick={() => setActive("patients")}>ดูทะเบียนทั้งหมด →</button></div>
    <div className={styles.filters} role="group" aria-label="กรองระดับความเร่งด่วนหน้าภาพรวม">
      <Choice active={liveFilter === "ALL"} label={`ทั้งหมด (${Object.keys(fresh).length})`} onClick={() => setLiveFilter("ALL")} />
      <Choice active={liveFilter === "CRITICAL"} label={`เร่งด่วน (${currentCritical})`} onClick={() => setLiveFilter("CRITICAL")} />
      <Choice active={liveFilter === "WARNING"} label={`เฝ้าระวัง (${currentWarning})`} onClick={() => setLiveFilter("WARNING")} />
    </div>
    <LiveCards patients={filteredFresh} openPatient={openPatient} />
    <details className={styles.learnMoreDrawer}>
      <summary className={styles.learnMoreSummary}>
        <span>ℹ️ ข้อมูลโซนหอผู้ป่วย ระบบติดตามอัตโนมัติ และคู่มือการใช้งาน (Learn More)</span>
        <span className={styles.learnMoreBadge}>ดูรายละเอียดเพิ่มเติม</span>
      </summary>
      <div className={styles.learnMoreBody}>
        <h3 className={styles.h2}>หอผู้ป่วยแยกตามโซน</h3>
        <p className={styles.muted}>คลิกเลือกโซนเพื่อกรองรายชื่อผู้ป่วยเฉพาะโซน หรือกดปุ่ม `/` บนคีย์บอร์ดเพื่อค้นหาผู้ป่วยด่วนจากทุกหน้า</p>
        <ZoneCards zones={zoneCards} onSelect={(zone) => { setDirectoryZone(zone as Zone); setDirectoryPage(1); setSearch(""); setActive("patients"); }} />
        <MonitorPanel openPatient={openPatient} compact />
      </div>
    </details>
  </>;
  else if (active === "chat") content = <CareChat staff openPatient={openPatient} />;
  else if (active === "triage") content = <>
    <details className={styles.panel} open={showMessages} onToggle={e => setShowMessages(e.currentTarget.open)}><summary>ข้อความจากผู้ป่วยและผู้ดูแล</summary><CareMessages staff /></details>
    <Header title="ใครควรได้รับการตรวจสอบก่อน?" text="รวมค่าสัญญาณชีพล่าสุดกับรายการแจ้งเตือนที่ยังไม่ปิด ไม่ใช่การวินิจฉัยของ AI" refresh={loadTriage} />
    <div className={styles.filters}><ZoneFilter value={triageZone} setValue={setTriageZone} /><Choice active={triagePriority === "all"} label="ทุกระดับ" onClick={() => setTriagePriority("all")} />{["CRITICAL", "ATTENTION", "ROUTINE"].map((item) => <Choice key={item} active={triagePriority === item} label={labels[item]} onClick={() => setTriagePriority(item)} />)}<Choice active={bedboundOnly} label="เฉพาะติดเตียง" onClick={() => setBedboundOnly((value) => !value)} /></div>
    {triageError ? <p role="alert" className={styles.error}>{triageError}</p> : <TriageBoard items={triage} openPatient={openPatient} now={clock} />}
  </>;
  else if (active === "patients") content = <>
    <Header title="ทะเบียนผู้ป่วย" text={`พบ ${directoryTotal} คน · ค้นหาจากรหัส ชื่อ ห้อง หรือโรค`} refresh={loadDirectory} />
    <div className={styles.filters}><ZoneFilter value={directoryZone} setValue={(zone) => { setDirectoryZone(zone); setDirectoryPage(1); }} /><input ref={searchInputRef} aria-label="ค้นหาผู้ป่วย" value={search} onChange={(event) => { setSearch(event.target.value); setDirectoryPage(1); }} className={styles.searchInput} placeholder="ค้นหา เช่น B012 หรือ diabetes (กด / เพื่อค้นหา)" /></div>
    {directoryError ? <p role="alert" className={styles.error}>{directoryError}</p> : <Directory items={directory} loading={directoryLoading} openPatient={openPatient} />}
    <div className={styles.pagination}><button className={styles.secondary} disabled={directoryPage <= 1 || directoryLoading} onClick={() => setDirectoryPage((page) => page - 1)}>← ก่อนหน้า</button><span>หน้า {directoryPage} / {Math.max(1, Math.ceil(directoryTotal / 20))}</span><button className={styles.secondary} disabled={directoryPage * 20 >= directoryTotal || directoryLoading} onClick={() => setDirectoryPage((page) => page + 1)}>ถัดไป →</button></div>
  </>;
  else if (active === "alerts") content = <>
    <Header title="รายการที่ต้องติดตาม" text="สถานะงานแยกจากสถานะส่งมือถือ · การรับทราบและปิดงานต้องให้บุคลากรดำเนินการ" refresh={loadAlerts} />
    <div className={styles.filters}>{(["open", "NEW", "ACKNOWLEDGED", "ESCALATED", "RESOLVED"] as WorkflowStatus[]).map((item) => <Choice key={item} active={alertStatus === item} label={item === "open" ? "งานที่ยังไม่ปิด" : labels[item]} onClick={() => { setAlertStatus(item); setAlertPage(0); }} />)}<ZoneFilter value={alertZone} setValue={zone => { setAlertZone(zone); setAlertPage(0); }} /><input className={styles.searchInput} aria-label="รหัสผู้ป่วยที่ต้องการติดตาม" placeholder="กรองรหัสผู้ป่วย เช่น A001" value={alertPatient} onChange={e => { setAlertPatient(e.target.value); setAlertPage(0); }} /></div>
    <p className={styles.muted}>รวมการเกิดซ้ำเป็นเหตุการณ์เดียว · ยังเก็บประวัติเดิม · การส่งต่อในหน้านี้คือบันทึกสถานะภายในระบบ</p>
    {workflowMessage && <p className={styles.notice} role="status">{workflowMessage}</p>}
    {alertError ? <p role="alert" className={styles.error}>{alertError}</p> : alertsLoadedFilter !== JSON.stringify([alertStatus, alertZone, alertPage, alertPatient]) ? <p role="status" className={styles.empty}>กำลังโหลดเหตุการณ์ตามตัวกรอง…</p> : <WorkflowBoard alerts={alerts} busy={alertsLoading ? -1 : busyAlert} openPatient={openPatient} move={moveAlert} />}
    <div className={styles.pagination}><button className={styles.secondary} disabled={alertPage === 0} onClick={() => setAlertPage(p => p - 1)}>ก่อนหน้า</button><span>หน้า {alertPage + 1} · ไม่เกิน 20 เหตุการณ์ต่อหน้า</span><button className={styles.secondary} disabled={!alertMore} onClick={() => setAlertPage(p => p + 1)}>ถัดไป</button></div>
  </>;
  else if (active === "ai") content = <>
    <MonitorPanel openPatient={openPatient} compact />
    <AgentPanel openPatient={openPatient} openEvidence={() => setActive('evidence')} />
    <details className={styles.learnMoreDrawer}>
      <summary className={styles.learnMoreSummary}>
        <span>🧪 หลักฐานการทดสอบระบบ ประวัติ Audit Trail และโมเดลวิจัยย้อนหลัง (Learn More)</span>
        <span className={styles.learnMoreBadge}>ดูข้อมูลสำหรับผู้พัฒนา</span>
      </summary>
      <div className={styles.learnMoreBody}>
        <div className={styles.titleRow}><p className={styles.muted}>ส่วนนี้ใช้ตรวจสอบระบบและอธิบายการทดลอง ไม่จำเป็นต่อการติดตามผู้ป่วยประจำวัน</p><button className={styles.secondary} onClick={() => void loadAudit()}>↻ โหลดหลักฐานล่าสุด</button></div>
        <EvaluationCard evaluation={evaluation} />
        <AuditTable items={audit} openPatient={openPatient} />
        <details className={styles.panel}><summary>โมเดล ICU รุ่นก่อนหน้า — ใช้วิจัยย้อนหลังเท่านั้น</summary><ModelCard status={modelStatus} benchmarks={modelBenchmarks} /></details>
      </div>
    </details>
  </>;
  else if (active === "research") content = <ResearchPanel />;
  else if (active === "evidence") content = <EvidencePanel />;
  else if (active === "care") content = <CarePanel />;
  else if (active === "notifications") content = <NotificationPanel />;
  else content = <div className={styles.panel}><span className={styles.eyebrow}>HANDOFF & EXPORT</span><h2 className={styles.h2}>สรุปข้อมูล พร้อมส่งต่อ</h2><p className={styles.muted}>ดาวน์โหลดรายงานภาพรวม หรือกดรหัสผู้ป่วยด้านล่างเพื่อส่งออกรายบุคคล</p><div className={styles.actions}><a href={url("/api/reports/reports/text")} target="_blank" rel="noreferrer" className={styles.primary}><Icon name="reports" />เปิดรายงาน Text</a><a href={url("/api/reports/reports/document")} className={styles.secondary}>ดาวน์โหลด Word</a></div><p className={styles.notice}>ตารางนี้เป็นสถิติสะสมในฐานข้อมูล ไม่ใช่ค่าสัญญาณชีพ ณ ขณะนี้ · ตรวจทานก่อนส่งต่อทุกครั้ง</p><SnapshotTable items={snapshot?.patients ?? []} openPatient={openPatient} /></div>;
  return <div className={`${styles.app} ${nightShift ? styles.nightShift : ""}`}>
    <aside className={styles.sidebar}><div className={styles.brand}><span className={styles.logo}>+</span><div><b>ศูนย์ดูแลผู้ป่วย</b><small className={styles.blockSmall}>Care team workspace</small></div></div>
      <nav className={styles.nav} aria-label="หมวดการทำงาน">
        {navGroups.map(group => {
          const isGroupActive = group.sections.includes(active);
          return <div key={group.label} className={styles.sidebarGroup}>
            <button onClick={() => { setActive(group.sections[0]); history.replaceState(null, '', `?section=${group.sections[0]}`); }} className={`${styles.navButton} ${isGroupActive ? styles.activeNav : ''}`} aria-current={isGroupActive ? 'page' : undefined}>
              <Icon name={group.icon} size={20} />
              <span>{group.label}</span>
            </button>
            {group.sections.length > 1 && isGroupActive && (
              <div className={styles.sidebarSubnav} aria-label={`เมนูย่อย ${group.label}`}>
                {group.sections.map(secId => {
                  const subItem = nav.find(n => n.id === secId)!;
                  return <button key={secId} type="button" onClick={() => { setActive(secId); history.replaceState(null, '', `?section=${secId}`); }} className={`${styles.sidebarSubBtn} ${active === secId ? styles.sidebarSubBtnActive : ''}`}>
                    {subItem.label}
                  </button>;
                })}
              </div>
            )}
          </div>;
        })}
      </nav>
      <div className={styles.connection}><span style={{ color: connected ? "#247354" : "#936511" }}>●</span> {connected ? "เชื่อมต่อข้อมูลสด" : "กำลังเชื่อมต่อข้อมูลสดใหม่…"}<small>ข้อมูลเพื่อสาธิตและวิจัย<br />ไม่ใช่ระบบฉุกเฉินทางการแพทย์</small></div>
    </aside>
    <main id="main-content" tabIndex={-1} className={styles.workspace}><header className={styles.pageHeader}><div><p className={styles.eyebrow}>SMART WARD / CARE WORKSPACE</p><h1>{currentNav.label}</h1><p className={styles.muted}>{currentNav.detail}</p></div><div className={styles.headerActions}><button type="button" className={styles.secondary} onClick={() => { setActive("patients"); setTimeout(() => searchInputRef.current?.focus(), 40); }}>🔍 ค้นหาผู้ป่วย (/)</button><button type="button" className={nightShift ? styles.primary : styles.secondary} aria-pressed={nightShift} onClick={toggleNightShift}>{nightShift ? "☀️ โหมดปกติ" : "🌙 โหมดเวรดึก"}</button><button type="button" className={soundEnabled ? styles.primary : styles.secondary} aria-pressed={soundEnabled} onClick={toggleSound}>{soundEnabled ? "🔊 เสียงเตือนวิกฤต: เปิด" : "🔇 เสียงเตือนวิกฤต: ปิด"}</button><button className={styles.secondary} onClick={() => setActive("notifications")}><Icon name="notifications" size={18} />ตั้งค่าแจ้งเตือนมือถือ</button></div></header>
      <nav className={styles.subnav} aria-label="เมนูในหมวด">{(navGroups.find(g => g.sections.includes(active))?.sections ?? []).map(id => <Choice key={id} label={nav.find(n => n.id === id)!.label} active={active === id} onClick={() => { setActive(id); history.replaceState(null, '', `?section=${id}`); }} />)}</nav>
      {!connected && <p className={styles.notice} role="status">การเชื่อมต่อสดยังไม่พร้อม ระบบกำลังลองใหม่และดึงข้อมูลสำรองทุก 5 วินาที</p>}
      {monitorError && <p className={styles.error} role="alert">{monitorError}</p>}{content}
    </main>
    <AgentAssistant key={`${active}-${selected ?? ''}`} section={active} patientId={selected ?? undefined} staff />
    {selected && <PatientModal viewAlerts={() => { setAlertPatient(selected); setAlertPage(0); setAlertStatus('open'); setAlertZone('ALL'); closePatient(); setActive('alerts'); }} key={selected} id={selected} detail={detail} error={detailError} timeline={timeline} chat={chat} input={input} chatting={chatting} setInput={setInput} sendChat={sendChat} endRef={endRef} close={closePatient} careMessage={careMessage} careBusy={careBusy} createCareRequest={createCareRequest} />}
  </div>;
}

function Header({ title, text, refresh }: { title: string; text: string; refresh?: () => void }) { return <div className={styles.titleRow}><div><h2 className={styles.h2}>{title}</h2><p className={styles.muted}>{text}</p></div>{refresh && <button className={styles.secondary} onClick={() => void refresh()}>↻ รีเฟรช</button>}</div>; }
function Metric({ label, value, note, tone }: { label: string; value: number | string; note: string; tone?: "total" | "fresh" | "critical" | "warning" }) { return <div className={styles.metric} data-tone={tone}><span>{label}</span><strong>{value}</strong><small>{note}</small></div>; }
function Choice({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) { return <button onClick={onClick} className={`${styles.choice} ${active ? styles.choiceActive : ""}`} aria-pressed={active}>{label}</button>; }
function ZoneFilter({ value, setValue }: { value: Zone; setValue: (zone: Zone) => void }) { return <>{(["ALL", "A", "B", "C", "HOME"] as Zone[]).map((zone) => <Choice key={zone} active={value === zone} label={zone === "ALL" ? "ทุกโซน" : zone === "HOME" ? "ดูแลที่บ้าน" : "Zone " + zone} onClick={() => setValue(zone)} />)}</>; }
function Pill({ text, tone }: { text: string; tone: string }) { return <span className={styles.pill} style={{ color: tone, borderColor: tone }}>{text}</span>; }
function ZoneCards({ zones, onSelect }: { zones: Snapshot["zones"]; onSelect: (zone: string) => void }) { return <div className={styles.zoneGrid}>{zones?.map((zone) => <button key={zone.zone} onClick={() => onSelect(zone.zone)} className={styles.zoneCard}><b>โซน {zone.zone} ↗</b><small>{zone.label}</small><strong>{zone.registered_patients} เตียง</strong><span>{zone.patients_with_readings} มีข้อมูลใหม่</span><span>{zone.critical_count} เข้าเกณฑ์เร่งด่วน</span></button>)}</div>; }

function LiveCards({ patients, openPatient }: { patients: Record<string, LivePatient>; openPatient: (id: string) => void }) {
  const rank: Record<string, number> = { CRITICAL: 2, WARNING: 1 };
  const items = Object.values(patients).sort((a, b) => (rank[b.status] ?? 0) - (rank[a.status] ?? 0)).slice(0, 12);
  if (!items.length) return <div className={styles.empty}>กำลังรอข้อมูลจาก monitor worker</div>;
  return <div className={styles.grid}>{items.map((patient) => <button key={patient.patient_id} onClick={() => void openPatient(patient.patient_id)} className={styles.liveCard} style={{ borderColor: color(patient.status) }}><div className={styles.cardHead}><div><b>{patient.patient_id} · ห้อง {patient.patient_profile?.room_number ?? "—"}</b><small className={styles.blockSmall}>{patient.patient_profile?.condition ?? "ไม่ระบุโรค"}</small></div><Pill text={labels[patient.status] ?? patient.status} tone={color(patient.status)} /></div><div className={styles.vitals}><span><b style={{ color: "#ad394b" }}>{patient.heart_rate}</b><small>ชีพจร · bpm</small></span><span><b style={{ color: "#247354" }}>{patient.spo2}</b><small>ออกซิเจน · %</small></span><span><b style={{ color: "#366995" }}>{patient.respiratory_rate ?? "—"}</b><small>หายใจ · /นาที</small></span></div><VitalCharts points={patient.history} compact title={`แนวโน้มล่าสุดของ ${patient.patient_id}`} /><span className={styles.cardFooterPrompt}>เปิดเวชระเบียนและกราฟละเอียด →</span></button>)}</div>;
}
function TriageBoard({ items, openPatient, now }: { items: TriagePatient[]; openPatient: (id: string) => void; now: number }) {
  if (!items.length) return <div className={styles.empty}>ยังไม่มีผู้ป่วยตรงกับตัวกรองนี้</div>;
  return <div className={styles.grid}>{items.map(item => { const fresh = isFreshReading(item.latest, now); return <button key={item.patient_id} onClick={() => void openPatient(item.patient_id)} className={styles.liveCard} style={{ borderColor: color(item.triage_level) }}>
    <div className={styles.cardHead}><b>{item.patient_id} · ห้อง {item.room_number}</b><Pill text={labels[item.triage_level]} tone={color(item.triage_level)} /></div>
    <p className={styles.reason}>{item.priority_reason}</p>
    <div className={styles.vitals}><span>ชีพจร <b>{fresh ? item.latest.heart_rate ?? "—" : "—"}</b><small>bpm</small></span><span>ออกซิเจน <b>{fresh ? item.latest.spo2 ?? "—" : "—"}</b><small>%</small></span><span>หายใจ <b>{fresh ? item.latest.respiratory_rate ?? "—" : "—"}</b><small>ครั้ง/นาที</small></span></div>
    <small className={styles.blockSmall}>{fresh ? "ข้อมูลล่าสุด" : "ข้อมูลเก่า / ยังไม่มีข้อมูล"} · วัดเมื่อ {timestamp(item.latest.timestamp)}</small>
    <small>{item.mobility === "Bedbound" ? "ติดเตียง" : "ต้องมีผู้ช่วยเคลื่อนไหว"} · เหตุการณ์ที่ยังไม่ปิด {item.open_alerts}</small>
    <span className={styles.cardFooterPrompt}>คลิกเพื่อประเมินและดูเวชระเบียน →</span>
  </button>; })}</div>;
}
function Directory({ items, loading, openPatient }: { items: DirectoryPatient[]; loading: boolean; openPatient: (id: string) => void }) { if (loading) return <div className={styles.empty}>กำลังค้นหาทะเบียนผู้ป่วย...</div>; if (!items.length) return <div className={styles.empty}>ไม่พบผู้ป่วยตามเงื่อนไข ลองเปลี่ยนโซนหรือคำค้นหา</div>; return <div className={styles.directoryGrid}>{items.map((item) => <button key={item.patient_id} onClick={() => void openPatient(item.patient_id)} className={styles.directoryCard}><div className={styles.cardHead}><b>{item.patient_id}</b><Pill text={"Zone " + item.zone} tone="#366995" /></div><strong>ห้อง {item.room_number} · เตียง {item.bed_number}</strong><p className={styles.condition}>{item.condition}</p><small>{item.mobility} · {item.doctor}</small><span className={styles.cardFooterPrompt}>เปิดข้อมูลผู้ป่วย →</span></button>)}</div>; }
function ModelCard({ status, benchmarks }: { status: ModelStatus | null; benchmarks: ModelBenchmark[] }) { if (!status) return <div className={styles.empty}>ยังโหลดสถานะโมเดลที่เทรนไม่ได้</div>; if (!status.available) return <section className={styles.panel}><h3 style={{ marginTop: 0 }}>Historical ICU benchmark (not live)</h3><Pill text={status.status} tone="#936511" /><p className={styles.muted}>{status.message}</p><p className={styles.disclaimer}>ระบบจะไม่สร้างคะแนนแทนโมเดลที่ยังไม่ได้เทรน</p></section>; const metrics = status.holdout_test_metrics; return <section className={styles.panel}><div className={styles.cardHead}><div><h3 style={{ margin: 0 }}>Historical ICU benchmark (not live)</h3><p className={styles.muted}>{status.model_version} · {status.profile}</p></div><Pill text="Research only" tone="#936511" /></div><p>{status.endpoint}</p>{metrics && <div className={styles.evaluationGrid}><Clinical label="Hold-out ROC-AUC" value={metrics.roc_auc ?? "—"} /><Clinical label="PR-AUC" value={metrics.pr_auc ?? "—"} /><Clinical label="Brier score" value={metrics.brier_score ?? "—"} /><Clinical label="Sensitivity / Specificity" value={(metrics.sensitivity ?? "—") + " / " + (metrics.specificity ?? "—")} /></div>}{benchmarks.length > 1 && <><h4 style={{ marginBottom: 7 }}>Offline profile comparison</h4><div className={styles.evaluationGrid}>{benchmarks.map((benchmark) => <div key={benchmark.model_version} className={styles.evaluationCase} style={{ borderColor: benchmark.runtime_compatible ? "#60a5fa" : "#64748b" }}><b>{benchmark.profile} {benchmark.runtime_compatible ? "· dashboard-compatible" : "· requires additional data"}</b><small>{benchmark.feature_count} features · ROC-AUC {benchmark.holdout_test_metrics?.roc_auc ?? "—"} · PR-AUC {benchmark.holdout_test_metrics?.pr_auc ?? "—"}</small></div>)}</div></>}<p className={styles.disclaimer}>{status.research_only_notice}</p></section>; }
function EvaluationCard({ evaluation }: { evaluation: Evaluation | null }) { if (!evaluation) return <div className={styles.empty}>ยังโหลด evaluation ไม่ได้</div>; return <section className={styles.panel}><div className={styles.cardHead}><div><h3 style={{ margin: 0 }}>Synthetic Alert-Workflow Evaluation</h3><p className={styles.muted}>Passed {evaluation.passed}/{evaluation.total} · failed {evaluation.failed}</p></div><Pill text={evaluation.clinical_validation ? "Clinical validation" : "Not clinical validation"} tone="#475569" /></div><p className={styles.disclaimer}>{evaluation.note}</p><div className={styles.evaluationGrid}>{evaluation.results.map((result) => <div key={result.id} className={styles.evaluationCase} style={{ borderColor: result.passed ? "#247354" : "#ad394b" }}><b>{result.passed ? "✓" : "!"} {result.label}</b><small>Expected: {result.expected_severity ?? "no alert"} · Actual: {result.actual_severity ?? "no alert"}</small></div>)}</div></section>; }
function AuditTable({ items, openPatient }: { items: Audit[]; openPatient: (id: string) => void }) { return <section className={styles.panel}><h3 style={{ marginTop: 0 }}>Recent Agent Audit Trail</h3><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>เวลา</th><th>Patient</th><th>Action</th><th>Actor</th><th>Detail</th></tr></thead><tbody>{items.length ? items.map((item) => <tr key={item.id}><td>{timestamp(item.created_at)}</td><td><button className={styles.link} onClick={() => void openPatient(item.patient_id)}>{item.patient_id}</button></td><td>{item.action}</td><td>{item.actor}</td><td>{item.detail}</td></tr>) : <tr><td colSpan={5}>ยังไม่มี audit event</td></tr>}</tbody></table></div></section>; }
function SnapshotTable({ items, openPatient }: { items: Snapshot["patients"]; openPatient: (id: string) => void }) { return <div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>ID</th><th>Zone/Room</th><th>HR avg</th><th>SpO2 min</th><th>จำนวนการวัดเข้าเกณฑ์เร่งด่วน (สะสม)</th></tr></thead><tbody>{items.length ? items.map((item) => <tr key={item.patient_id}><td><button className={styles.link} onClick={() => void openPatient(item.patient_id)}>{item.patient_id}</button></td><td>{item.zone ?? "—"} / {item.room_number ?? "—"}</td><td>{item.avg_hr}</td><td>{item.min_spo2}%</td><td>{item.critical_count}</td></tr>) : <tr><td colSpan={5}>ยังไม่มีข้อมูล</td></tr>}</tbody></table></div>; }

function PatientModal({ id, detail, error, timeline, chat, input, chatting, setInput, sendChat, endRef, close, careMessage, careBusy, createCareRequest, viewAlerts }: { viewAlerts: () => void; id: string; detail: Detail | null; error: string; timeline: TimelineEvent[]; chat: ChatItem[]; input: string; chatting: boolean; setInput: (value: string) => void; sendChat: (event: FormEvent) => void; endRef: RefObject<HTMLDivElement | null>; close: () => void; careMessage: string; careBusy: string | null; createCareRequest: (type: "doctor" | "ambulance") => void }) {
  const profile = detail?.profile;
  const [tab, setTab] = useState("summary");
  const [clinicalView, setClinicalView] = useState<'nurse' | 'doctor'>('nurse');
  const [sbarCopied, setSbarCopied] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    const previousOverflow = document.body.style.overflow;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    element?.showModal(); document.body.style.overflow = "hidden";
    return () => { element?.close(); document.body.style.overflow = previousOverflow; if (previousFocus?.isConnected) previousFocus.focus(); };
  }, []);
  const sbarSituation = `${id} (${profile?.name ?? "ไม่ระบุชื่อ"}) โซน ${profile?.zone ?? "—"} ห้อง ${profile?.room_number ?? "—"} เตียง ${profile?.bed_number ?? "—"} · สถานะ ${labels[detail?.monitor?.status ?? ""] ?? detail?.monitor?.status ?? "รอประเมิน"} (HR ${detail?.monitor?.heart_rate ?? "—"} bpm, SpO₂ ${detail?.monitor?.spo2 ?? "—"}%, RR ${detail?.monitor?.respiratory_rate ?? "—"} /นาที)`;
  const sbarBackground = `ภาวะหลัก: ${profile?.condition ?? "ไม่ระบุ"} · การเคลื่อนไหว: ${profile?.mobility ?? "—"} · แพทย์ผู้ดูแล: ${profile?.doctor ?? "—"}`;
  const sbarAssessment = `${detail?.ai_assessment?.summary ?? "รอผลวิเคราะห์"}${detail?.risk_model?.risk_percent != null ? ` · คะแนนความเสี่ยงวิจัย ${detail.risk_model.risk_percent}%` : ""}`;
  const sbarRecommendation = detail?.ai_assessment?.recommendations?.length ? detail.ai_assessment.recommendations.join(" · ") : "ตรวจสัญญาณชีพซ้ำตามรอบและประเมินอาการข้างเตียงโดยบุคลากร";
  function copySbar() {
    const text = `[SBAR สรุปส่งต่อเวร/รายงานแพทย์ — ${id}]\nS (Situation): ${sbarSituation}\nB (Background): ${sbarBackground}\nA (Assessment): ${sbarAssessment}\nR (Recommendation): ${sbarRecommendation}`;
    void navigator.clipboard?.writeText(text).catch(() => {});
    setSbarCopied(true);
    window.setTimeout(() => setSbarCopied(false), 2500);
  }
  return <dialog ref={dialog} className={styles.overlay} aria-labelledby="patient-title" onCancel={(event) => { event.preventDefault(); close(); }}>
    <div className={styles.modal}><header className={styles.modalHeader}><div><p className={styles.eyebrow}>PATIENT RECORD · ข้อมูลสาธิต</p><h2 id="patient-title" className={styles.h2}>{id} {profile ? `· โซน ${profile.zone} / ห้อง ${profile.room_number}` : ""}</h2><p className={styles.muted}>{profile?.name ?? "กำลังเตรียมข้อมูล"} {profile?.condition ? `· ${profile.condition}` : ""}</p></div><button className={styles.close} aria-label="ปิดรายละเอียดผู้ป่วย" onClick={close}>×</button></header>
    <div className={styles.modalToolbar}>
      <div className={styles.filters} role="group" aria-label="หมวดรายละเอียดผู้ป่วย">{[["summary", "ข้อมูลและผลโมเดล"], ["chat", "Gemini เพิ่มเติม"], ["timeline", "ประวัติและส่งต่อ"]].map(([value, label]) => <Choice key={value} label={label} active={tab === value} onClick={() => setTab(value)} />)}</div>
      <button className={styles.critical} onClick={viewAlerts}>เปิดเหตุการณ์ที่ต้องติดตามของ {id}</button>
    </div>
    {error && <p className={styles.error} role="alert">{error}</p>}
    {!detail ? !error && <p className={styles.empty} role="status">กำลังโหลดข้อมูล…</p> : <>
      {tab === "summary" && <>
        <div className={styles.roleView}><div><b>จัดข้อมูลตามบทบาทผู้ดูแล</b><small>สลับมุมมองเพื่อเน้นรายการตรวจติดตามทางคลินิกที่ตรงกับบทบาท</small></div><div className={styles.filters}><Choice label="มุมมองพยาบาล" active={clinicalView === 'nurse'} onClick={() => setClinicalView('nurse')} /><Choice label="มุมมองแพทย์" active={clinicalView === 'doctor'} onClick={() => setClinicalView('doctor')} /></div></div>
        <LatestVitals state={detail.monitor} />
        <section className={styles.sbarBox} aria-label="SBAR สรุปส่งต่อเวร/รายงานแพทย์">
          <div className={styles.sbarHead}>
            <div>
              <span className={styles.eyebrow}>SBAR QUICK SUMMARY</span>
              <h3>SBAR สรุปส่งต่อเวร/รายงานแพทย์</h3>
            </div>
            <div className={styles.sbarActions}>
              {sbarCopied && <span className={styles.sbarCopied} role="status">✓ คัดลอก SBAR ลงคลิปบอร์ดแล้ว</span>}
              <button type="button" className={styles.secondary} onClick={copySbar}>📋 คัดลอก SBAR</button>
            </div>
          </div>
          <div className={styles.sbarGrid}>
            <div className={styles.sbarItem}><span className={styles.sbarLetter}>S</span><div><b>Situation (สถานการณ์ปัจจุบัน)</b><p>{sbarSituation}</p></div></div>
            <div className={styles.sbarItem}><span className={styles.sbarLetter}>B</span><div><b>Background (ประวัติและบริบท)</b><p>{sbarBackground}</p></div></div>
            <div className={styles.sbarItem}><span className={styles.sbarLetter}>A</span><div><b>Assessment (ผลการประเมิน)</b><p>{sbarAssessment}</p></div></div>
            <div className={styles.sbarItem}><span className={styles.sbarLetter}>R</span><div><b>Recommendation (ข้อเสนอแนะ)</b><p>{sbarRecommendation}</p></div></div>
          </div>
        </section>
        {clinicalView === 'nurse' ? <div className={styles.modalGrid}><div><section className={styles.box}><span className={styles.eyebrow}>NURSING FOLLOW-UP</span><h3>สิ่งที่ควรตรวจและบันทึก</h3><p>{detail.ai_assessment.summary}</p><ul className={styles.clinicalList}>{detail.ai_assessment.recommendations.map((item) => <li key={item}>{item}</li>)}</ul><p className={styles.disclaimer}>AI เสนอรายการทบทวน ไม่ได้ยืนยันอาการหรือสั่งการพยาบาล</p></section></div><div><section className={styles.box}><span className={styles.eyebrow}>PATIENT CONTEXT</span><h3>ข้อมูลที่ต้องรู้ก่อนดูแล</h3><p><b>{profile?.condition}</b></p><p>การเคลื่อนไหว: {profile?.mobility ?? '—'}</p><small className={styles.blockSmall}>โซน {profile?.zone} · ห้อง {profile?.room_number} · เตียง {profile?.bed_number} · แพทย์ผู้ดูแล: {profile?.doctor ?? '—'}</small><button className={styles.link} onClick={() => setTab('timeline')}>ดูประวัติและสร้างคำขอส่งต่อ →</button></section></div></div>
        : <div className={styles.modalGrid}><div><PatientAnalysis state={detail.monitor} /><section className={styles.box}><span className={styles.eyebrow}>CLINICAL REVIEW</span><h3>ผลประเมินที่ต้องใช้วิจารณญาณแพทย์</h3><p>{detail.ai_assessment.summary}</p><p><b>โมเดลความเสี่ยงวิจัย:</b> {detail.risk_model.risk_percent ?? 'งดให้คะแนน'}{detail.risk_model.risk_percent !== null ? '%' : ''} · {detail.risk_model.message}</p><p className={styles.disclaimer}>คะแนนเป็นงานวิจัยและยังไม่ผ่าน clinical validation ห้ามใช้วินิจฉัยหรือปรับการรักษาโดยลำพัง</p></section></div><div><section className={styles.box}><span className={styles.eyebrow}>SYNTHETIC PROFILE</span><h3>ประวัติผู้ป่วยจำลอง</h3><p><b>{profile?.condition}</b></p><small className={styles.blockSmall}>เตียง {profile?.bed_number} · แพทย์สาธิต: {profile?.doctor}</small><p className={styles.disclaimer}>ข้อมูลส่วนนี้เป็นโปรไฟล์สังเคราะห์ ไม่ใช่ผลตรวจหรือค่าจากเซนเซอร์</p></section><div className={styles.clinicalGrid}><Clinical label="กรุ๊ปเลือด" value={profile?.blood_group} /><Clinical label="การเคลื่อนไหว" value={profile?.mobility} /><Clinical label="การนอน (สมมติ)" value={profile?.sleep_hours === undefined ? undefined : profile.sleep_hours + " ชม."} /><Clinical label="น้ำตาล (สมมติ)" value={profile?.blood_glucose_mg_dl === undefined ? undefined : profile.blood_glucose_mg_dl + " mg/dL"} /><Clinical label="ไขมัน (สมมติ)" value={profile?.cholesterol_mg_dl === undefined ? undefined : profile.cholesterol_mg_dl + " mg/dL"} /><Clinical label="จังหวะหัวใจ (สมมติ)" value={profile?.ecg_rhythm} /></div></div></div>}
        <StaffTrendPanel patientId={id} />
        <details className={styles.learnMoreDrawer}>
          <summary className={styles.learnMoreSummary}>
            <span>🛏️ ข้อมูลเซนเซอร์แผ่นแรงกด ท่าทางบนเตียง และสุขภาพอุปกรณ์ข้างเตียง (Learn More)</span>
            <span className={styles.learnMoreBadge}>ดูเซนเซอร์ข้างเตียง</span>
          </summary>
          <div className={styles.learnMoreBody}>
            <BedsidePanel patientId={id} />
          </div>
        </details>
        <div className={styles.actions}><a href={url("/api/patient/" + id + "/report/text")} target="_blank" rel="noreferrer" className={styles.primary}>เปิดสรุป Text</a><a href={url("/api/patient/" + id + "/report/document")} className={styles.secondary}>ดาวน์โหลด Word</a></div>
      </>}
      {tab === "chat" && <section className={styles.chat}><div><b>ผู้ช่วย AI · {id}</b><p className={styles.disclaimer}>อธิบายข้อมูลผู้ป่วยที่เลือก ไม่ใช่การวินิจฉัยหรือสั่งรักษา</p></div><div className={styles.quick}>{["สรุปรายละเอียดผู้ป่วยและค่าที่สำคัญ", "สรุปแนวโน้มและสิ่งที่ควรตรวจสอบ", "สรุปข้อมูลส่งต่อแพทย์โดยไม่วินิจฉัย"].map((text) => <button key={text} className={styles.quickButton} onClick={() => setInput(text)} disabled={chatting}>{text}</button>)}</div><div className={styles.messages} role="log" aria-label="บทสนทนากับ AI">{chat.map((item, index) => <div key={index} className={`${styles.message} ${item.sender === "user" ? styles.userMessage : ""}`}>{item.text}</div>)}{chatting && <small role="status">กำลังเตรียมคำตอบ…</small>}<div ref={endRef} /></div><form className={styles.chatForm} onSubmit={sendChat}><input aria-label="คำถามถึงผู้ช่วย AI" value={input} onChange={(event) => setInput(event.target.value)} disabled={chatting} className={styles.input} placeholder="พิมพ์คำถามเกี่ยวกับผู้ป่วยรายนี้…" /><button disabled={chatting || !input.trim()} className={styles.send}>ส่ง</button></form></section>}
      {tab === "timeline" && <div className={styles.modalGrid}><section className={styles.box}><h3>ประวัติการติดตาม</h3><div className={styles.timeline}>{timeline.length ? timeline.slice(0, 30).map((event, index) => <div key={event.type + event.timestamp + index} className={styles.timelineRow}><span className={styles.dot} style={{ background: color(event.severity) }} /><div><b>{event.title}</b><small className={styles.blockSmall}>{timestamp(event.timestamp)} · {event.detail}</small></div></div>) : <p className={styles.muted}>ยังไม่มีเหตุการณ์ให้แสดง</p>}</div></section><section className={styles.box}><h3>สร้างคำขอประสานงาน</h3><p className={styles.notice}>บันทึกเป็นคำขอในระบบเท่านั้น ไม่ได้โทรหาแพทย์หรือเรียกรถพยาบาลจริง</p><div className={styles.actions}><button disabled={careBusy !== null} className={styles.warning} onClick={() => createCareRequest("doctor")}>คำขอติดต่อแพทย์</button><button disabled={careBusy !== null} className={styles.critical} onClick={() => createCareRequest("ambulance")}>คำขอรถพยาบาล</button></div>{careMessage && <p className={styles.notice} role="status">{careMessage}</p>}</section></div>}
    </>}</div>
  </dialog>;
}
function Clinical({ label, value }: { label: string; value?: string | number }) { return <div className={styles.clinical}><small>{label}</small><b>{value ?? "—"}</b></div>; }
