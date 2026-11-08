"use client";

import { useCallback, useEffect, useState } from "react";
import s from "./Ward.module.css";
import { requestJson } from "./apiRequest";

type LineStatus = {
  configured: boolean;
  channel: string;
  token_len: number;
  token_preview: string;
  is_secret_only: boolean;
  quota: string;
  target_bed?: string;
  audience_mode?: "family" | "staff";
  bed_isolation?: boolean;
  events: string[];
};

export default function NotificationPanel({
  patient = false,
  patientId,
}: {
  patient?: boolean;
  patientId?: string;
}) {
  const [status, setStatus] = useState<LineStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [testingType, setTestingType] = useState<string | null>(null);
  const [selectedBed, setSelectedBed] = useState<string>(() => patientId || "A001");
  const [selectedAudience, setSelectedAudience] = useState<"family" | "staff">("family");
  const [previewMode, setPreviewMode] = useState<"family" | "staff">("family");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const loadStatus = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const data = await requestJson<LineStatus>("/api/notifications/line/status", { signal });
        setStatus(data);
        if (patientId) {
          setSelectedBed(patientId);
        } else if (data.target_bed) {
          setSelectedBed(data.target_bed);
        }
        if (data.audience_mode) {
          setSelectedAudience(data.audience_mode);
          setPreviewMode(data.audience_mode);
        }
        setError("");
      } catch {
        setError("ไม่สามารถโหลดสถานะการแจ้งเตือน LINE ได้");
      } finally {
        setLoading(false);
      }
    },
    [patientId]
  );

  useEffect(() => {
    const abort = new AbortController();
    const timer = setTimeout(() => void loadStatus(abort.signal), 0);
    return () => {
      clearTimeout(timer);
      abort.abort();
    };
  }, [loadStatus]);

  async function handleUpdateSettings(bed: string, aud: "family" | "staff") {
    setSelectedBed(bed);
    setSelectedAudience(aud);
    setPreviewMode(aud);
    try {
      await requestJson<{ status: string; target_bed: string; audience_mode: string }>("/api/notifications/line/settings", {
        method: "POST",
        body: JSON.stringify({ target_bed: bed, audience_mode: aud }),
      });
      setMessage(`บันทึกการตั้งค่าเรียบร้อย: เตียง ${bed} · โหมด${aud === "family" ? "ฝั่งญาติผู้ป่วย" : "เจ้าหน้าที่"}`);
    } catch {
      setError("ไม่สามารถบันทึกการตั้งค่าเตียงได้");
    }
  }

  async function handleTest(type: "test" | "vital" | "posture") {
    setTestingType(type);
    setMessage("");
    setError("");
    try {
      const res = await requestJson<{ status: string; message: string }>("/api/notifications/line/test", {
        method: "POST",
        body: JSON.stringify({
          patient_id: selectedBed,
          type,
          audience: selectedAudience,
        }),
      });
      setMessage(`สำเร็จ: ${res.message} (ตรวจดูข้อความที่เด้งบนโทรศัพท์ของคุณใน LINE ได้เลยครับ)`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "ส่งการแจ้งเตือนทดสอบไม่สำเร็จ");
    } finally {
      setTestingType(null);
    }
  }

  const isConnected = Boolean(status?.configured && !status?.is_secret_only);

  return (
    <section aria-label="ศูนย์จัดการการแจ้งเตือนมือถือผ่าน LINE">
      <div className={s.panel} style={{ padding: "26px 28px", borderRadius: 16 }}>
        {/* Header with Clear Visual Hierarchy */}
        <div className={s.cardHead} style={{ alignItems: "flex-start", marginBottom: 20 }}>
          <div style={{ maxWidth: 720 }}>
            <span className={s.eyebrow}>
              {patient ? "FAMILY MOBILE ALERTS · BED ISOLATION ACTIVE" : "LINE MOBILE NOTIFICATION · BED ISOLATION ACTIVE"}
            </span>
            <h3 className={s.h2} style={{ fontSize: 20, margin: "4px 0 6px" }}>
              {patient
                ? "ศูนย์การแจ้งเตือน LINE สำหรับฝั่งญาติผู้ป่วย (Family Care Mobile Alerts)"
                : "ศูนย์จัดการการแจ้งเตือนมือถือผ่าน LINE (Mobile Care Alerts)"}
            </h3>
            <p className={s.muted} style={{ fontSize: 13, lineHeight: 1.6, margin: 0 }}>
              ระบบแจ้งเตือนหลักส่งตรงเข้ามือถือผ่าน LINE Official Account พร้อมระบบแยกเตียง (Bed Isolation) ชัดเจน ไม่ปะปนกับเตียงอื่น และให้ AI สังเคราะห์ข้อมูลเพื่อความอุ่นใจของครอบครัว
            </p>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <span
              className={s.pill}
              style={{
                borderColor: "#0e6b52",
                color: "#0e6b52",
                background: "#eaf5ef",
                fontSize: 12,
                fontWeight: 600,
                padding: "4px 10px",
              }}
            >
              🔒 แยกข้อมูลรายเตียง (Bed Isolation)
            </span>
            <span
              className={s.pill}
              style={{
                borderColor: isConnected ? "#247354" : status?.is_secret_only ? "#b97f16" : "#ad394b",
                color: isConnected ? "#1b5e46" : status?.is_secret_only ? "#80520b" : "#a42c3d",
                background: isConnected ? "#eaf5ef" : status?.is_secret_only ? "#fff3d9" : "#fff0f1",
                fontSize: 12,
                fontWeight: 600,
                padding: "4px 10px",
              }}
            >
              {isConnected
                ? "🟢 LINE Bot พร้อมใช้งาน"
                : status?.is_secret_only
                ? "⚠️ ต้องการ Channel Access Token"
                : "⚪ ยังไม่ได้เชื่อมต่อ"}
            </span>
          </div>
        </div>

        {/* Feedback Messages */}
        {error && <p className={s.error} role="alert" style={{ margin: "14px 0" }}>{error}</p>}
        {message && <p className={s.notice} role="status" style={{ margin: "14px 0" }}>{message}</p>}

        {status?.is_secret_only && (
          <div
            style={{
              margin: "16px 0",
              padding: "14px 16px",
              background: "#fff9eb",
              border: "1.5px solid #f1dfbc",
              borderRadius: 10,
              fontSize: 13,
              lineHeight: 1.6,
            }}
          >
            <b style={{ color: "#85550a", display: "block", marginBottom: 4 }}>
              💡 ตรวจพบ Channel Secret (32 ตัวอักษร): ระบบต้องการ Channel Access Token เพื่อส่งข้อความ
            </b>
            <span>
              รหัสที่คุณใส่มามีความยาว 32 ตัวอักษรซึ่งคือ <b>Channel secret</b> ครับ! เพื่อให้บอทส่งข้อความเข้ามือถือได้ ให้ไปที่เว็บ{" "}
              <a href="https://developers.line.biz/console/" target="_blank" rel="noopener noreferrer" style={{ textDecoration: "underline", color: "#176e53", fontWeight: 600 }}>
                LINE Developers Console
              </a>{" "}
              $\rightarrow$ คลิกที่แท็บ <b>Messaging API</b> $\rightarrow$ เลื่อนลงล่างสุดแล้วกดปุ่ม <b>Issue</b> ตรงหัวข้อ <b>Channel access token (long-lived)</b> แล้วนำรหัสยาวๆ นั้นมาใส่ใน <code>backend/.env</code> แทนครับ
            </span>
          </div>
        )}

        {/* 1. Unified Settings & Channel Status Card */}
        <div
          style={{
            background: "#ffffff",
            border: "1px solid #d9e6e0",
            borderRadius: 12,
            padding: "18px 20px",
            marginBottom: 20,
            boxShadow: "0 1px 3px rgba(15, 41, 34, 0.02)",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10, marginBottom: 14 }}>
            <h4 style={{ margin: 0, fontSize: 14.5, fontWeight: 700, color: "var(--ink)", display: "flex", alignItems: "center", gap: 8 }}>
              <span>⚙️</span> การจัดระเบียบเตียงและกลุ่มเป้าหมาย (Bed Isolation & Audience Settings)
            </h4>
            <span style={{ fontSize: 12, color: "var(--muted)" }}>
              ช่องทาง: <b>{status?.channel ?? "กำลังโหลด…"}</b> · โควตา: <b>{status?.quota ?? "ฟรี 500 ข้อความ/เดือน"}</b>
            </span>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 16, alignItems: "start" }}>
            {/* Bed Isolation Lock / Selector */}
            <div style={{ background: "#f8faf9", border: "1px solid #e1ece6", borderRadius: 10, padding: "14px 16px" }}>
              <span style={{ display: "block", fontSize: 12.5, fontWeight: 700, color: "var(--ink)", marginBottom: 8 }}>
                1. เตียงผู้ป่วยเป้าหมาย (Target Bed & Privacy Lock):
              </span>
              {patient || patientId ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <div
                    style={{
                      padding: "8px 12px",
                      borderRadius: 8,
                      background: "#eaf5ef",
                      border: "1.5px solid #0e6b52",
                      color: "#0e6b52",
                      fontWeight: 700,
                      fontSize: 13.5,
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 8,
                    }}
                  >
                    🔒 เตียง {selectedBed} (เฉพาะเตียงนี้เท่านั้น · ข้อมูลไม่รั่วไหล)
                  </div>
                  <small style={{ fontSize: 11.5, color: "var(--muted)", lineHeight: 1.4 }}>
                    ระบบล็อกอัตโนมัติตาม ID ผู้ป่วยที่ล็อกอิน เพื่อความเป็นส่วนตัวสูงสุดตามมาตรฐาน PDPA
                  </small>
                </div>
              ) : (
                <div>
                  <select
                    value={selectedBed}
                    onChange={(e) => void handleUpdateSettings(e.target.value, selectedAudience)}
                    style={{
                      width: "100%",
                      padding: "9px 12px",
                      borderRadius: 8,
                      border: "1.5px solid #c8dcd2",
                      fontSize: 13,
                      fontWeight: 600,
                      background: "#fff",
                      color: "var(--ink)",
                    }}
                  >
                    <option value="A001">เตียง A001 (ห้อง A101 · โซนอายุรกรรม A)</option>
                    <option value="A002">เตียง A002 (ห้อง A102 · โซนอายุรกรรม A)</option>
                    <option value="A003">เตียง A003 (ห้อง A103 · โซนอายุรกรรม A)</option>
                    <option value="A004">เตียง A004 (ห้อง A104 · โซนอายุรกรรม A)</option>
                    <option value="TEST_P">เตียงสาธิต (คุณธุวานนธ์ ตอบโต้)</option>
                    <option value="ALL">ทุกลู่เตียง (สำหรับเจ้าหน้าที่ดูแลหอผู้ป่วย)</option>
                  </select>
                  <small style={{ display: "block", fontSize: 11.5, color: "var(--muted)", marginTop: 6, lineHeight: 1.4 }}>
                    เลือกเตียงเพื่อกำหนดให้ LINE ส่งเฉพาะเหตุการณ์ของเตียงนี้เท่านั้น
                  </small>
                </div>
              )}
            </div>

            {/* Target Audience Mode Toggle */}
            <div style={{ background: "#f8faf9", border: "1px solid #e1ece6", borderRadius: 10, padding: "14px 16px" }}>
              <span style={{ display: "block", fontSize: 12.5, fontWeight: 700, color: "var(--ink)", marginBottom: 8 }}>
                2. กลุ่มเป้าหมายผู้รับข้อความ (Audience Mode):
              </span>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                <button
                  type="button"
                  onClick={() => void handleUpdateSettings(selectedBed, "family")}
                  style={{
                    padding: "10px 12px",
                    borderRadius: 8,
                    border: selectedAudience === "family" ? "2px solid #0e6b52" : "1px solid #c8dcd2",
                    background: selectedAudience === "family" ? "#eaf5ef" : "#ffffff",
                    color: selectedAudience === "family" ? "#0e6b52" : "var(--muted)",
                    fontWeight: selectedAudience === "family" ? 750 : 550,
                    fontSize: 12.5,
                    cursor: "pointer",
                    textAlign: "center",
                    transition: "all 0.15s ease",
                  }}
                >
                  👨‍👩‍👧 ฝั่งญาติผู้ป่วย
                  <span style={{ display: "block", fontSize: 11, fontWeight: 400, marginTop: 2, opacity: 0.85 }}>
                    AI ภาษาเข้าใจง่าย อบอุ่น
                  </span>
                </button>

                <button
                  type="button"
                  onClick={() => void handleUpdateSettings(selectedBed, "staff")}
                  style={{
                    padding: "10px 12px",
                    borderRadius: 8,
                    border: selectedAudience === "staff" ? "2px solid #a42c3d" : "1px solid #c8dcd2",
                    background: selectedAudience === "staff" ? "#fff0f1" : "#ffffff",
                    color: selectedAudience === "staff" ? "#a42c3d" : "var(--muted)",
                    fontWeight: selectedAudience === "staff" ? 750 : 550,
                    fontSize: 12.5,
                    cursor: "pointer",
                    textAlign: "center",
                    transition: "all 0.15s ease",
                  }}
                >
                  🩺 แพทย์/เจ้าหน้าที่
                  <span style={{ display: "block", fontSize: 11, fontWeight: 400, marginTop: 2, opacity: 0.85 }}>
                    Modified NEWS2 & STAT
                  </span>
                </button>
              </div>
              <small style={{ display: "block", fontSize: 11.5, color: "var(--muted)", marginTop: 6, lineHeight: 1.4 }}>
                ระบบจะเลือกรูปแบบข้อความและคำแนะนำข้างเตียงให้ตรงกับบทบาทผู้รับโดยอัตโนมัติ
              </small>
            </div>
          </div>
        </div>

        {/* 2. Interactive Test Suite Cards */}
        <div
          style={{
            background: "#ffffff",
            border: "1px solid #d9e6e0",
            borderRadius: 12,
            padding: "18px 20px",
            marginBottom: 20,
            boxShadow: "0 1px 3px rgba(15, 41, 34, 0.02)",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10, marginBottom: 14 }}>
            <div>
              <h4 style={{ margin: 0, fontSize: 14.5, fontWeight: 700, color: "var(--ink)" }}>
                🧪 ทดสอบการส่งข้อความเข้า LINE มือถือจริง (Interactive Live Test Suite)
              </h4>
              <p style={{ margin: "2px 0 0", fontSize: 12, color: "var(--muted)" }}>
                กดทดสอบเพื่อตรวจสอบข้อความจริงที่จะเด้งบนหน้าจอล็อกของโทรศัพท์มือถือ
              </p>
            </div>
            <button
              type="button"
              className={s.secondary}
              disabled={loading}
              onClick={() => void loadStatus()}
              style={{ fontSize: 12, padding: "5px 12px", minHeight: 32 }}
            >
              ↻ ตรวจสอบสถานะการเชื่อมต่อ
            </button>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
            {/* Test 1: Welcome & Bed Isolation Test */}
            <div style={{ background: "#f8faf9", border: "1px solid #e1ece6", borderRadius: 10, padding: "14px", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
              <div>
                <b style={{ display: "block", color: "#0e6b52", fontSize: 13, marginBottom: 4 }}>
                  📱 ข้อความเชื่อมต่อเตียง {selectedBed}
                </b>
                <p style={{ margin: 0, fontSize: 11.5, color: "var(--muted)", lineHeight: 1.5 }}>
                  ทดสอบส่งข้อความต้อนรับและยืนยันระบบแยกเตียง (Bed Isolation) เข้า LINE
                </p>
              </div>
              <button
                type="button"
                className={s.primary}
                disabled={Boolean(testingType) || loading || !status?.configured}
                onClick={() => void handleTest("test")}
                style={{ marginTop: 12, width: "100%", minHeight: 38, fontSize: 12.5 }}
              >
                {testingType === "test" ? "กำลังส่งข้อความ…" : `ทดสอบเชื่อมต่อเตียง ${selectedBed}`}
              </button>
            </div>

            {/* Test 2: Vital Alert Test */}
            <div style={{ background: "#f8faf9", border: "1px solid #e1ece6", borderRadius: 10, padding: "14px", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
              <div>
                <b style={{ display: "block", color: "#a42c3d", fontSize: 13, marginBottom: 4 }}>
                  🫁 สัญญาณชีพวิกฤต (Vital Alert)
                </b>
                <p style={{ margin: 0, fontSize: 11.5, color: "var(--muted)", lineHeight: 1.5 }}>
                  จำลอง SpO₂ ตก (87%) ชีพจรเร็ว (112 bpm) เพื่อตรวจดูคำอธิบายที่ AI ส่งให้
                </p>
              </div>
              <button
                type="button"
                className={s.secondary}
                disabled={Boolean(testingType) || loading || !status?.configured}
                onClick={() => void handleTest("vital")}
                style={{ marginTop: 12, width: "100%", minHeight: 38, fontSize: 12.5 }}
              >
                {testingType === "vital" ? "กำลังส่งข้อความ…" : "ทดสอบเตือนสัญญาณชีพ"}
              </button>
            </div>

            {/* Test 3: Posture & Turn Due Test */}
            <div style={{ background: "#f8faf9", border: "1px solid #e1ece6", borderRadius: 10, padding: "14px", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
              <div>
                <b style={{ display: "block", color: "#b97f16", fontSize: 13, marginBottom: 4 }}>
                  🛏️ รอบพลิกตัว (Turn Due & 30° Tilt)
                </b>
                <p style={{ margin: 0, fontSize: 11.5, color: "var(--muted)", lineHeight: 1.5 }}>
                  จำลองนอนท่าเดิมครบ 2 ชม. (125 นาที) ตรวจสอบจุดรับแรงกดก้นกบและคำแนะนำจัดท่า
                </p>
              </div>
              <button
                type="button"
                className={s.secondary}
                disabled={Boolean(testingType) || loading || !status?.configured}
                onClick={() => void handleTest("posture")}
                style={{ marginTop: 12, width: "100%", minHeight: 38, fontSize: 12.5 }}
              >
                {testingType === "posture" ? "กำลังส่งข้อความ…" : "ทดสอบเตือนรอบพลิกตัว"}
              </button>
            </div>
          </div>
        </div>

        {/* 3. Realistic Smartphone LINE Notification Mockup Card */}
        <div
          style={{
            background: "#ffffff",
            border: "1px solid #d9e6e0",
            borderRadius: 12,
            padding: "18px 20px",
            marginBottom: 20,
            boxShadow: "0 1px 3px rgba(15, 41, 34, 0.02)",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10, marginBottom: 14 }}>
            <div>
              <h4 style={{ margin: 0, fontSize: 14.5, fontWeight: 700, color: "var(--ink)" }}>
                📲 พรีวิวหน้าจอการแจ้งเตือนจริงใน LINE (Smartphone Mockup Preview)
              </h4>
              <p style={{ margin: "2px 0 0", fontSize: 12, color: "var(--muted)" }}>
                สลับดูความแตกต่างระหว่างข้อความที่ส่งถึงญาติผู้ป่วย กับข้อความส่งถึงทีมแพทย์
              </p>
            </div>

            {/* Preview Switch Tabs */}
            <div style={{ display: "inline-flex", gap: 4, background: "#f0f4f2", padding: "3px 4px", borderRadius: 8 }}>
              <button
                type="button"
                onClick={() => setPreviewMode("family")}
                style={{
                  padding: "5px 12px",
                  borderRadius: 6,
                  border: "none",
                  fontSize: 12,
                  fontWeight: 650,
                  cursor: "pointer",
                  background: previewMode === "family" ? "#0e6b52" : "transparent",
                  color: previewMode === "family" ? "#fff" : "var(--ink)",
                  transition: "all 0.15s ease",
                }}
              >
                👨‍👩‍👧 ฝั่งญาติผู้ป่วย (Family Mode)
              </button>
              <button
                type="button"
                onClick={() => setPreviewMode("staff")}
                style={{
                  padding: "5px 12px",
                  borderRadius: 6,
                  border: "none",
                  fontSize: 12,
                  fontWeight: 650,
                  cursor: "pointer",
                  background: previewMode === "staff" ? "#a42c3d" : "transparent",
                  color: previewMode === "staff" ? "#fff" : "var(--ink)",
                  transition: "all 0.15s ease",
                }}
              >
                🩺 แพทย์และเจ้าหน้าที่ (Doctor Mode)
              </button>
            </div>
          </div>

          {/* Smartphone Chat Bubble Container */}
          <div
            style={{
              background: "#7998b6",
              borderRadius: 14,
              padding: "16px",
              maxWidth: 640,
              boxShadow: "inset 0 1px 3px rgba(0, 0, 0, 0.12)",
            }}
          >
            {/* Top Bar inside Phone */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", color: "#ffffff", fontSize: 12, fontWeight: 700, marginBottom: 12, padding: "0 4px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ background: "#06c755", color: "#fff", width: 22, height: 22, borderRadius: "50%", display: "grid", placeItems: "center", fontSize: 11 }}>💬</span>
                <span>Smart Ward Official Bot</span>
              </div>
              <span style={{ fontSize: 11, opacity: 0.85 }}>LINE Messaging API · 18:45 น.</span>
            </div>

            {previewMode === "staff" ? (
              /* Doctor STAT Alert Bubble */
              <div
                style={{
                  background: "#ffffff",
                  borderLeft: "5px solid #a42c3d",
                  borderRadius: "4px 14px 14px 14px",
                  padding: "16px 18px",
                  fontSize: 12.5,
                  lineHeight: 1.65,
                  color: "#2d3748",
                  boxShadow: "0 2px 8px rgba(0, 0, 0, 0.08)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #edf2f7", paddingBottom: 8, marginBottom: 10 }}>
                  <b style={{ color: "#a42c3d", fontSize: 13.5 }}>🔴 [DOCTOR STAT ALERT · เตียง {selectedBed}]</b>
                  <span style={{ background: "#fff0f1", color: "#a42c3d", border: "1px solid #f5c2c7", borderRadius: 4, padding: "2px 6px", fontSize: 11, fontWeight: 700 }}>
                    NEWS2: 7 (HIGH RISK)
                  </span>
                </div>

                <div style={{ margin: "4px 0", fontSize: 12 }}>
                  <div>🛏️ <b>เตียง:</b> เตียง {selectedBed} (ห้อง A101 · โซน A) · <b>แพทย์:</b> นพ. วิชัย ใจดี (Dr. Wichai)</div>
                  <div>👤 <b>ผู้ป่วย:</b> ผู้ป่วยเตียง {selectedBed} (68 ปี, ชาย) · <b>Dx:</b> COPD with Acute Exacerbation</div>
                </div>

                <div style={{ background: "#fff5f5", border: "1px solid #fed7d7", borderRadius: 8, padding: "10px 12px", margin: "10px 0" }}>
                  <b style={{ color: "#9b2c2c", display: "block", fontSize: 12, marginBottom: 4 }}>📊 สัญญาณชีพวิกฤต & คะแนน NEWS2:</b>
                  <div>• SpO₂: <b>87%</b> [Hypoxemia / NEWS2 Score: 3] (ลดลง -5% ใน 30 นาที)</div>
                  <div>• HR: <b>112 bpm</b> [Sinus Tachycardia / NEWS2 Score: 2]</div>
                  <div>• RR: <b>24 ครั้ง/นาที</b> [Tachypnea / NEWS2 Score: 2]</div>
                  <div>• <b>Modified NEWS2 Total: 7/9 คะแนน [HIGH RISK TIER]</b></div>
                </div>

                <div style={{ background: "#fffaf0", border: "1px solid #feebc8", borderRadius: 8, padding: "10px 12px", margin: "10px 0" }}>
                  <b style={{ color: "#975a16", display: "block", fontSize: 12, marginBottom: 4 }}>🛏️ ท่าทาง & แผลกดทับ (EPUAP Protocol):</b>
                  <div>• ท่าทาง: <b>นอนหงาย</b> ต่อเนื่อง <b>135 นาที</b> [OVERDUE &gt; 120 นาที]</div>
                  <div>• จุดรับแรงกดวิกฤต: ก้นกบ (Sacrum) &gt; 42 mmHg [Capillary Ischemia Risk]</div>
                  <div>• ความเสี่ยง: Braden Scale 11/23 (กลุ่มเสี่ยงสูง - High Risk)</div>
                </div>

                <div style={{ background: "#f7fafc", border: "1px solid #e2e8f0", borderRadius: 8, padding: "10px 12px", margin: "10px 0" }}>
                  <b style={{ color: "#2d3748", display: "block", fontSize: 12, marginBottom: 4 }}>💡 คำแนะนำทางคลินิก (Clinical Decision Support):</b>
                  <div>1. <b>ทางเดินหายใจ/ออกซิเจน:</b> ตรวจความกระชับสาย O₂ / ปรับ Titration เป้าหมาย 88–92% (สำหรับ COPD)</div>
                  <div>2. <b>พลิกตัว EPUAP:</b> จัดท่านอนตะแคงกึ่งหงาย 30° Lateral Tilt ทันทีเพื่อ offload ก้นกบ และยกส้นเท้าลอย</div>
                  <div>3. <b>การเฝ้าระวัง:</b> ยกระดับการวัดสัญญาณชีพเป็น q15m และพิจารณาเจาะ ABG หาก SpO₂ ไม่ฟื้นตัว</div>
                </div>

                <div style={{ fontSize: 11, color: "#718096", borderTop: "1px solid #edf2f7", paddingTop: 8, marginTop: 8 }}>
                  ⏰ เวลาที่บันทึก: 18:45:10 น. · Decision Support Only · ตรวจสอบผู้ป่วยจริงก่อนสั่งการ
                </div>
              </div>
            ) : (
              /* Family Care Alert Bubble */
              <div
                style={{
                  background: "#ffffff",
                  borderLeft: "5px solid #0e6b52",
                  borderRadius: "4px 14px 14px 14px",
                  padding: "16px 18px",
                  fontSize: 12.5,
                  lineHeight: 1.65,
                  color: "#2d3748",
                  boxShadow: "0 2px 8px rgba(0, 0, 0, 0.08)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #edf2f7", paddingBottom: 8, marginBottom: 10 }}>
                  <b style={{ color: "#0e6b52", fontSize: 13.5 }}>🏥 SMART WARD · รายงานสถานะผู้ป่วยสำหรับญาติ</b>
                  <span style={{ background: "#eaf5ef", color: "#0e6b52", border: "1px solid #b7e3ca", borderRadius: 4, padding: "2px 6px", fontSize: 11, fontWeight: 700 }}>
                    รายงานเฉพาะเตียง {selectedBed}
                  </span>
                </div>

                <div style={{ margin: "4px 0", fontSize: 12 }}>
                  <div>🛏️ <b>เตียงผู้ป่วย:</b> เตียง {selectedBed} (ห้อง A101 · โซนอายุรกรรม A)</div>
                  <div>👤 <b>ผู้ป่วย:</b> คุณผู้ป่วยเตียง {selectedBed} · <b>แพทย์เจ้าของไข้:</b> นพ. วิชัย ใจดี</div>
                </div>

                <div style={{ background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: 8, padding: "10px 12px", margin: "10px 0" }}>
                  <b style={{ color: "#166534", display: "block", fontSize: 12, marginBottom: 4 }}>📊 สัญญาณชีพล่าสุด:</b>
                  <div>• ออกซิเจนในเลือด (SpO₂): <b>88%</b> (ลดลงต่ำกว่าเกณฑ์ปกติชั่วคราว)</div>
                  <div>• อัตราการเต้นของหัวใจ: <b>110 ครั้ง/นาที</b> (ค่อนข้างเร็ว)</div>
                </div>

                <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 8, padding: "10px 12px", margin: "10px 0" }}>
                  <b style={{ color: "#1e293b", display: "block", fontSize: 12, marginBottom: 2 }}>🤖 AI วิเคราะห์และสรุปข้อมูล:</b>
                  <div style={{ color: "#334155" }}>
                    ระบบ AI ตรวจพบระดับออกซิเจนในเลือดลดลงเล็กน้อย ซึ่งอาจเกิดจากท่านอนกดทับหรือสายวัดที่นิ้วมือขยับเลื่อนหลุด ระบบได้ส่งข้อมูลประสานงานกับทีมพยาบาลเวรเรียบร้อยแล้วโดยอัตโนมัติ
                  </div>
                </div>

                <div style={{ background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: 8, padding: "10px 12px", margin: "10px 0" }}>
                  <b style={{ color: "#166534", display: "block", fontSize: 12, marginBottom: 2 }}>🩺 การดูแลของทีมพยาบาล:</b>
                  <div style={{ color: "#15803d" }}>
                    พยาบาลประจำเวรได้รับทราบสัญญาณเตือนและกำลังเข้าดูแลที่เตียงทันที เพื่อปรับสายออกซิเจนและตรวจวัดสัญญาณชีพซ้ำ
                  </div>
                </div>

                <div style={{ background: "#fffbeb", border: "1px solid #fef3c7", borderRadius: 8, padding: "10px 12px", margin: "10px 0" }}>
                  <b style={{ color: "#92400e", display: "block", fontSize: 12, marginBottom: 2 }}>💡 คำแนะนำสำหรับญาติ:</b>
                  <div style={{ color: "#78350f" }}>
                    ญาติไม่ต้องตื่นตระหนก สามารถพักผ่อนหรืออยู่เป็นกำลังใจข้างเตียงได้ตามปกติ หากมีข้อสงสัยสามารถกดปุ่มแชทติดต่อพยาบาลผ่านระบบได้ตลอด 24 ชั่วโมง
                  </div>
                </div>

                <div style={{ fontSize: 11, color: "#718096", borderTop: "1px solid #edf2f7", paddingTop: 8, marginTop: 8 }}>
                  ⏰ เวลาที่บันทึก: 18:45:10 น. · ระบบ AI Smart Ward เพื่อความอุ่นใจของครอบครัวผู้ป่วย
                </div>
              </div>
            )}
          </div>
        </div>

        {/* 4. Monitored Events Highlights in Clean 2x2 Grid */}
        <div style={{ marginBottom: 20 }}>
          <h4 style={{ fontSize: 14, fontWeight: 700, margin: "0 0 12px", color: "var(--ink)" }}>
            📋 เหตุการณ์ที่ระบบ AI จะคัดกรองและส่งการแจ้งเตือนเตียง {selectedBed} เข้า LINE:
          </h4>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 12 }}>
            <div style={{ padding: 14, background: "#ffffff", border: "1px solid #e1ece6", borderRadius: 10, boxShadow: "0 1px 2px rgba(15, 41, 34, 0.02)" }}>
              <b style={{ display: "flex", alignItems: "center", gap: 6, color: "#a42c3d", fontSize: 13, marginBottom: 4 }}>
                <span>🚨</span> สัญญาณชีพผิดปกติ (Vitals Alert)
              </b>
              <span style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.5 }}>
                SpO₂ ลดลงฉับพลัน หรือชีพจรเต้นเร็วผิดปกติ AI จะสรุปอาการ อธิบายสาเหตุที่เป็นไปได้ และแจ้งให้ทราบว่าพยาบาลกำลังเข้าดูแลข้างเตียงทันที
              </span>
            </div>

            <div style={{ padding: 14, background: "#ffffff", border: "1px solid #e1ece6", borderRadius: 10, boxShadow: "0 1px 2px rgba(15, 41, 34, 0.02)" }}>
              <b style={{ display: "flex", alignItems: "center", gap: 6, color: "#b97f16", fontSize: 13, marginBottom: 4 }}>
                <span>🛏️</span> รอบพลิกตัวผู้ป่วยติดเตียง (EPUAP Turn Due)
              </b>
              <span style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.5 }}>
                ผู้ป่วยนอนท่าเดิมเกิน 2 ชั่วโมง พร้อมรายงานจุดรับแรงกดก้นกบ (Sacrum) และคำแนะนำจัดท่า 30° Lateral Tilt เพื่อให้ญาติช่วยสังเกตได้อย่างถูกต้อง
              </span>
            </div>

            <div style={{ padding: 14, background: "#ffffff", border: "1px solid #e1ece6", borderRadius: 10, boxShadow: "0 1px 2px rgba(15, 41, 34, 0.02)" }}>
              <b style={{ display: "flex", alignItems: "center", gap: 6, color: "#85550a", fontSize: 13, marginBottom: 4 }}>
                <span>⚠️</span> สายวัดเลื่อนหลุดชั่วคราว (Sensor Disconnect)
              </b>
              <span style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.5 }}>
                สายวัดที่ปลายนิ้วเลื่อนหลุด ระบบจะสั่งงดแปลผลเพื่อความแม่นยำ พร้อมแจ้งให้ญาติหรือพยาบาลช่วยสวมคลิปหนิ้วมือให้กระชับ
              </span>
            </div>

            <div style={{ padding: 14, background: "#ffffff", border: "1px solid #e1ece6", borderRadius: 10, boxShadow: "0 1px 2px rgba(15, 41, 34, 0.02)" }}>
              <b style={{ display: "flex", alignItems: "center", gap: 6, color: "#176e53", fontSize: 13, marginBottom: 4 }}>
                <span>🆘</span> ปุ่มขอความช่วยเหลือข้างเตียง (Bedside SOS)
              </b>
              <span style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.5 }}>
                ผู้ป่วยแตะปุ่มด่วน 1-Tap จากแท็บเล็ตข้างเตียง (เช่น ขอน้ำดื่ม หรือเรียกพยาบาล) ส่งเข้ามือถือญาติและทีมพยาบาลทันที
              </span>
            </div>
          </div>
        </div>

        {/* 5. Progressive Disclosure Drawer */}
        <details className={s.learnMoreDrawer}>
          <summary className={s.learnMoreSummary}>
            <span>คู่มือการเชื่อมต่อ LINE สำหรับญาติและขั้นตอนการรับ Token (Learn More)</span>
            <span className={s.learnMoreBadge}>ดูวิธีเชื่อมต่อ</span>
          </summary>
          <div className={s.learnMoreBody} style={{ fontSize: 12.5, lineHeight: 1.65 }}>
            <p className={s.muted} style={{ marginTop: 0 }}>
              <b>1. การจัดระเบียบแยกเตียง (Bed Isolation):</b> ระบบนี้ออกแบบมาตามหลัก PDPA และมาตรฐานความปลอดภัยทางคลินิก โดยญาติของแต่ละเตียงจะได้รับเฉพาะข้อมูลของเตียงตนเองเท่านั้น ข้อมูลผู้ป่วยเตียงอื่นจะไม่รั่วไหลมายังโทรศัพท์ของท่าน
            </p>
            <p className={s.muted}>
              <b>2. AI จัดการข้อมูล:</b> ข้อมูลทางการแพทย์ (เช่น Modified NEWS2, Braden Score, PaO2) จะถูก AI ถอดรหัสและเรียบเรียงใหม่เป็นภาษาที่กระชับ อบอุ่น และเข้าใจง่าย พร้อมคำแนะนำที่ญาติสามารถนำไปปฏิบัติได้จริง
            </p>
            <p className={s.muted}>
              <b>3. วิธีเพิ่มเพื่อน:</b> ในหน้าแท็บ Messaging API ของ LINE Developers จะมี <b>QR Code</b> ให้ใช้แอป LINE บนโทรศัพท์สแกนเพื่อเพิ่มเพื่อน เมื่อเพิ่มเพื่อนแล้ว ท่านจะได้รับการแจ้งเตือนอัตโนมัติทันที
            </p>
          </div>
        </details>
      </div>
    </section>
  );
}
