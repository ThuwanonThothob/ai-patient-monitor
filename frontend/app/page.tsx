"use client";

import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

interface PatientProfile {
  name: string;
  age: number;
  gender: string;
  condition: string;
  doctor: string;
}

interface HistoryPoint {
  time: string;
  heart_rate: number;
  spo2: number;
  status?: string;
}

interface PatientData {
  patient_id: string;
  patient_profile?: PatientProfile;
  heart_rate: number;
  spo2: number;
  status: "NORMAL" | "WARNING" | "CRITICAL";
  alert_message: string;
  history: HistoryPoint[];
}

interface DetailedPatientData {
  patient_id: string;
  profile: PatientProfile;
  ai_assessment: {
    risk_score: number;
    risk_level: string;
    summary: string;
    recommendations: string[];
    stats: {
      avg_hr: number;
      max_hr: number;
      min_hr: number;
      avg_spo2: number;
      min_spo2: number;
      total_samples: number;
    };
  };
  history: { heart_rate: number; spo2: number; status: string; timestamp: number }[];
}

export default function Dashboard() {
  const [patients, setPatients] = useState<{ [key: string]: PatientData }>({});
  const [connected, setConnected] = useState(false);
  const [selectedPatientId, setSelectedPatientId] = useState<string | null>(null);
  const [detailedData, setDetailedData] = useState<DetailedPatientData | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  useEffect(() => {
    const ws = new WebSocket("ws://localhost:8000/ws/vitals");

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      const timeStr = new Date(data.timestamp * 1000).toLocaleTimeString([], {
        hour12: false,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });

      const newPoint: HistoryPoint = {
        time: timeStr,
        heart_rate: data.heart_rate,
        spo2: data.spo2,
      };

      setPatients((prev) => {
        const existing = prev[data.patient_id];
        const oldHistory = existing ? existing.history : [];
        const updatedHistory = [...oldHistory, newPoint].slice(-15);

        return {
          ...prev,
          [data.patient_id]: {
            ...data,
            history: updatedHistory,
          },
        };
      });
    };

    return () => ws.close();
  }, []);

  // เปิดดูรายละเอียดฉบับเต็มเมื่อคลิกผู้ป่วย
  const openPatientDetail = async (patientId: string) => {
    setSelectedPatientId(patientId);
    setLoadingDetail(true);
    try {
      const res = await fetch(`http://localhost:8000/api/patient/${patientId}/details`);
      const data = await res.json();
      setDetailedData(data);
    } catch (err) {
      console.error("Failed to fetch patient details:", err);
    } finally {
      setLoadingDetail(false);
    }
  };

  const getStatusColor = (status: string) => {
    if (status === "CRITICAL") return "#ff4d4d";
    if (status === "WARNING") return "#ffaa00";
    return "#4dff4d";
  };

  return (
    <div style={{ padding: "30px", fontFamily: "sans-serif", backgroundColor: "#121212", color: "#fff", minHeight: "100vh" }}>
      <header style={{ marginBottom: "25px", borderBottom: "1px solid #333", paddingBottom: "15px" }}>
        <h1 style={{ margin: "0 0 8px 0" }}>🏥 AI Patient Monitoring Dashboard</h1>
        <p style={{ margin: 0, color: "#aaa" }}>
          สถานะระบบ: {connected ? "🟢 ออนไลน์ (กำลังเชื่อมต่อและประมวลผล Real-time)" : "🔴 ขาดการติดต่อกับเซิร์ฟเวอร์"}
        </p>
      </header>

      {/* Grid การ์ดหน้าแรก */}
      {Object.keys(patients).length === 0 ? (
        <p>⏳ กำลังรอรับสัญญาณชีพจากอุปกรณ์จำลอง...</p>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))", gap: "20px" }}>
          {Object.values(patients)
            .sort((a, b) => a.patient_id.localeCompare(b.patient_id))
            .map((p) => (
              <div
                key={p.patient_id}
                style={{
                  borderRadius: "12px",
                  padding: "20px",
                  backgroundColor: "#1e1e1e",
                  border: `2px solid ${getStatusColor(p.status)}`,
                  boxShadow: p.status === "CRITICAL" ? "0 0 15px rgba(255, 77, 77, 0.4)" : "none",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div>
                    <h2 style={{ margin: "0 0 4px 0", fontSize: "1.3rem" }}>เตียง {p.patient_id}</h2>
                    <div style={{ fontSize: "0.95rem", color: "#64b5f6", fontWeight: "bold" }}>
                      {p.patient_profile?.name || "กำลังโหลด..."}
                    </div>
                    <div style={{ fontSize: "0.8rem", color: "#888" }}>
                      อาการ: {p.patient_profile?.condition || "-"}
                    </div>
                  </div>
                  <span
                    style={{
                      backgroundColor: getStatusColor(p.status),
                      color: "#000",
                      padding: "4px 8px",
                      borderRadius: "4px",
                      fontWeight: "bold",
                      fontSize: "0.8rem",
                    }}
                  >
                    {p.status}
                  </span>
                </div>

                {/* Vitals */}
                <div style={{ display: "flex", justifyContent: "space-around", margin: "15px 0", background: "#141414", padding: "10px", borderRadius: "8px" }}>
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontSize: "0.8rem", color: "#aaa" }}>Heart Rate</div>
                    <div style={{ fontSize: "1.8rem", fontWeight: "bold", color: "#ff6b6b" }}>
                      {p.heart_rate} <span style={{ fontSize: "0.8rem" }}>bpm</span>
                    </div>
                  </div>
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontSize: "0.8rem", color: "#aaa" }}>SpO2</div>
                    <div style={{ fontSize: "1.8rem", fontWeight: "bold", color: "#51cf66" }}>
                      {p.spo2} <span style={{ fontSize: "0.8rem" }}>%</span>
                    </div>
                  </div>
                </div>

                {/* กราฟ */}
                <div style={{ height: "120px", width: "100%", margin: "10px 0", backgroundColor: "#141414", padding: "5px 5px 0 0", borderRadius: "8px" }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={p.history}>
                      <XAxis dataKey="time" stroke="#555" fontSize={9} tickLine={false} />
                      <YAxis domain={[40, 130]} stroke="#555" fontSize={9} tickLine={false} />
                      <Line type="monotone" dataKey="heart_rate" stroke="#ff6b6b" strokeWidth={2} dot={false} isAnimationActive={false} />
                      <Line type="monotone" dataKey="spo2" stroke="#51cf66" strokeWidth={2} dot={false} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>

                {/* ปุ่มเปิดดูรายละเอียด */}
                <button
                  onClick={() => openPatientDetail(p.patient_id)}
                  style={{
                    width: "100%",
                    padding: "10px",
                    marginTop: "10px",
                    borderRadius: "6px",
                    border: "1px solid #444",
                    backgroundColor: "#2c2c2c",
                    color: "#fff",
                    fontWeight: "bold",
                    cursor: "pointer",
                    transition: "0.2s",
                  }}
                >
                  🔍 ดูรายละเอียดเต็ม & บทบาท AI
                </button>
              </div>
            ))}
        </div>
      )}

      {/* 📌 MODAL แสดงรายละเอียดเต็มของผู้ป่วย + วิเคราะห์ AI */}
      {selectedPatientId && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: "rgba(0,0,0,0.85)",
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            zIndex: 1000,
            padding: "20px",
          }}
        >
          <div
            style={{
              backgroundColor: "#1e1e1e",
              borderRadius: "12px",
              width: "100%",
              maxWidth: "850px",
              maxHeight: "90vh",
              overflowY: "auto",
              padding: "25px",
              border: "1px solid #444",
              boxShadow: "0 10px 30px rgba(0,0,0,0.5)",
            }}
          >
            {/* Header Modal */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #333", paddingBottom: "15px" }}>
              <div>
                <h2 style={{ margin: 0, color: "#4fc3f7" }}>
                  📋 แฟ้มประวัติและผลการวิเคราะห์ AI (เตียง {selectedPatientId})
                </h2>
              </div>
              <button
                onClick={() => {
                  setSelectedPatientId(null);
                  setDetailedData(null);
                }}
                style={{
                  background: "none",
                  border: "none",
                  color: "#aaa",
                  fontSize: "1.5rem",
                  cursor: "pointer",
                }}
              >
                ✕
              </button>
            </div>

            {loadingDetail || !detailedData ? (
              <p style={{ padding: "30px 0", textAlign: "center" }}>⏳ AI กำลังรวบรวมข้อมูลและวิเคราะห์อาการ...</p>
            ) : (
              <div style={{ marginTop: "20px" }}>
                {/* 1. ข้อมูลส่วนตัวผู้ป่วย */}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "15px", backgroundColor: "#141414", padding: "15px", borderRadius: "8px", marginBottom: "20px" }}>
                  <div><span style={{ color: "#aaa" }}>ชื่อ-สกุล:</span> <strong>{detailedData.profile.name}</strong></div>
                  <div><span style={{ color: "#aaa" }}>อายุ / เพศ:</span> <strong>{detailedData.profile.age} ปี ({detailedData.profile.gender})</strong></div>
                  <div><span style={{ color: "#aaa" }}>โรคประจำตัว:</span> <strong style={{ color: "#ffb74d" }}>{detailedData.profile.condition}</strong></div>
                  <div><span style={{ color: "#aaa" }}>แพทย์ผู้ดูแล:</span> <strong>{detailedData.profile.doctor}</strong></div>
                </div>

                {/* 2. 🤖 สรุปผลการประเมินโดย AI (Clinical AI Assessment) */}
                <div
                  style={{
                    backgroundColor: "#1b263b",
                    borderLeft: "5px solid #40c4ff",
                    padding: "18px",
                    borderRadius: "8px",
                    marginBottom: "20px",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                    <h3 style={{ margin: 0, color: "#40c4ff" }}>🤖 ผลการประเมินทางคลินิกโดย AI (AI Assessment)</h3>
                    <span
                      style={{
                        backgroundColor: detailedData.ai_assessment.risk_score >= 70 ? "#ff4d4d" : detailedData.ai_assessment.risk_score >= 40 ? "#ffaa00" : "#4dff4d",
                        color: "#000",
                        padding: "4px 10px",
                        borderRadius: "20px",
                        fontWeight: "bold",
                        fontSize: "0.85rem",
                      }}
                    >
                      คะแนนความเสี่ยง: {detailedData.ai_assessment.risk_score}/100 ({detailedData.ai_assessment.risk_level})
                    </span>
                  </div>

                  <p style={{ margin: "0 0 10px 0", fontSize: "1rem", lineHeight: "1.5" }}>
                    {detailedData.ai_assessment.summary}
                  </p>

                  <div style={{ marginTop: "12px", fontSize: "0.9rem" }}>
                    <strong>💡 คำแนะนำจากระบบ AI สำหรับทีมพยาบาล:</strong>
                    <ul style={{ margin: "5px 0 0 0", paddingLeft: "20px", color: "#b0bec5" }}>
                      {detailedData.ai_assessment.recommendations.map((rec, idx) => (
                        <li key={idx} style={{ marginBottom: "3px" }}>{rec}</li>
                      ))}
                    </ul>
                  </div>
                </div>

                {/* 3. สถิติสำคัญย้อนหลัง */}
                <h4 style={{ margin: "0 0 10px 0", color: "#aaa" }}>📊 สถิติสัญญาณชีพย้อนหลัง (จากฐานข้อมูล SQLite)</h4>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "10px", marginBottom: "20px", textAlign: "center" }}>
                  <div style={{ background: "#141414", padding: "10px", borderRadius: "6px" }}>
                    <div style={{ fontSize: "0.75rem", color: "#888" }}>HR เฉลี่ย</div>
                    <div style={{ fontSize: "1.2rem", fontWeight: "bold", color: "#ff6b6b" }}>{detailedData.ai_assessment.stats.avg_hr} bpm</div>
                  </div>
                  <div style={{ background: "#141414", padding: "10px", borderRadius: "6px" }}>
                    <div style={{ fontSize: "0.75rem", color: "#888" }}>HR สูงสุด</div>
                    <div style={{ fontSize: "1.2rem", fontWeight: "bold", color: "#ff6b6b" }}>{detailedData.ai_assessment.stats.max_hr} bpm</div>
                  </div>
                  <div style={{ background: "#141414", padding: "10px", borderRadius: "6px" }}>
                    <div style={{ fontSize: "0.75rem", color: "#888" }}>SpO2 เฉลี่ย</div>
                    <div style={{ fontSize: "1.2rem", fontWeight: "bold", color: "#51cf66" }}>{detailedData.ai_assessment.stats.avg_spo2}%</div>
                  </div>
                  <div style={{ background: "#141414", padding: "10px", borderRadius: "6px" }}>
                    <div style={{ fontSize: "0.75rem", color: "#888" }}>SpO2 ต่ำสุด</div>
                    <div style={{ fontSize: "1.2rem", fontWeight: "bold", color: "#51cf66" }}>{detailedData.ai_assessment.stats.min_spo2}%</div>
                  </div>
                </div>

                {/* 4. ตารางบันทึกประวัติย้อนหลัง */}
                <h4 style={{ margin: "0 0 10px 0", color: "#aaa" }}>📋 บันทึกประวัติย้อนหลัง 15 รายการล่าสุด</h4>
                <div style={{ maxHeight: "180px", overflowY: "auto", border: "1px solid #333", borderRadius: "6px" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left", fontSize: "0.85rem" }}>
                    <thead>
                      <tr style={{ backgroundColor: "#252525", color: "#aaa" }}>
                        <th style={{ padding: "8px 12px" }}>เวลา</th>
                        <th style={{ padding: "8px 12px" }}>Heart Rate</th>
                        <th style={{ padding: "8px 12px" }}>SpO2</th>
                        <th style={{ padding: "8px 12px" }}>สถานะ</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detailedData.history.slice(0, 15).map((row, idx) => (
                        <tr key={idx} style={{ borderBottom: "1px solid #2a2a2a" }}>
                          <td style={{ padding: "8px 12px", color: "#888" }}>
                            {new Date(row.timestamp * 1000).toLocaleTimeString([], { hour12: false })}
                          </td>
                          <td style={{ padding: "8px 12px", color: "#ff6b6b", fontWeight: "bold" }}>{row.heart_rate} bpm</td>
                          <td style={{ padding: "8px 12px", color: "#51cf66", fontWeight: "bold" }}>{row.spo2}%</td>
                          <td style={{ padding: "8px 12px", color: getStatusColor(row.status) }}>{row.status}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}