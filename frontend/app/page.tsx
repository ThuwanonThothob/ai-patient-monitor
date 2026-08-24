"use client";

import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

interface HistoryPoint {
  time: string;
  heart_rate: number;
  spo2: number;
}

interface PatientData {
  patient_id: string;
  heart_rate: number;
  spo2: number;
  status: "NORMAL" | "WARNING" | "CRITICAL";
  alert_message: string;
  history: HistoryPoint[];
}

export default function Dashboard() {
  const [patients, setPatients] = useState<{ [key: string]: PatientData }>({});
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const ws = new WebSocket("ws://localhost:8000/ws/vitals");

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      const timeStr = new Date(data.timestamp * 1000).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });

      const newPoint: HistoryPoint = {
        time: timeStr,
        heart_rate: data.heart_rate,
        spo2: data.spo2,
      };

      setPatients((prev) => {
        const existing = prev[data.patient_id];
        const oldHistory = existing ? existing.history : [];
        // เก็บประวัติสูงสุด 15 จุดย้อนหลัง
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

  const getStatusColor = (status: string) => {
    if (status === "CRITICAL") return "#ff4d4d";
    if (status === "WARNING") return "#ffaa00";
    return "#4dff4d";
  };

  const getCardBorder = (status: string) => {
    if (status === "CRITICAL") return "4px solid #ff4d4d";
    if (status === "WARNING") return "4px solid #ffaa00";
    return "2px solid #333";
  };

  return (
    <div style={{ padding: "30px", fontFamily: "sans-serif", backgroundColor: "#141414", color: "#fff", minHeight: "100vh" }}>
      <header style={{ marginBottom: "25px", borderBottom: "1px solid #333", paddingBottom: "15px" }}>
        <h1 style={{ margin: "0 0 10px 0" }}>🏥 Central Patient Vital Monitor (With Database & Charts)</h1>
        <p style={{ margin: 0 }}>
          สถานะระบบ: {connected ? "🟢 ออนไลน์ (กำลังดักฟัง Real-time & บันทึก DB)" : "🔴 ขาดการติดต่อกับเซิร์ฟเวอร์"}
        </p>
      </header>

      {Object.keys(patients).length === 0 ? (
        <p>⏳ กำลังรอรับสัญญาณชีพจากอุปกรณ์จำลอง...</p>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))", gap: "20px" }}>
          {Object.values(patients)
            .sort((a, b) => a.patient_id.localeCompare(b.patient_id))
            .map((p) => (
              <div
                key={p.patient_id}
                style={{
                  borderRadius: "12px",
                  padding: "20px",
                  backgroundColor: "#222",
                  border: getCardBorder(p.status),
                  boxShadow: p.status === "CRITICAL" ? "0 0 15px rgba(255, 77, 77, 0.4)" : "none",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <h2 style={{ margin: 0 }}>เตียงผู้ป่วย: {p.patient_id}</h2>
                  <span
                    style={{
                      backgroundColor: getStatusColor(p.status),
                      color: "#000",
                      padding: "4px 8px",
                      borderRadius: "4px",
                      fontWeight: "bold",
                      fontSize: "0.85rem",
                    }}
                  >
                    {p.status}
                  </span>
                </div>

                {/* ค่าสัญญาณชีพ Real-time */}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-around",
                    margin: "15px 0",
                    background: "#1a1a1a",
                    padding: "10px",
                    borderRadius: "8px",
                  }}
                >
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

                {/* 📈 กราฟ Real-time */}
                <div style={{ height: "140px", width: "100%", margin: "15px 0", backgroundColor: "#181818", padding: "10px 5px 0 0", borderRadius: "8px" }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={p.history}>
                      <XAxis dataKey="time" stroke="#666" fontSize={10} tickLine={false} />
                      <YAxis domain={[40, 130]} stroke="#666" fontSize={10} tickLine={false} />
                      <Tooltip contentStyle={{ backgroundColor: "#333", border: "none", borderRadius: "4px" }} />
                      <Line type="monotone" dataKey="heart_rate" name="Heart Rate" stroke="#ff6b6b" strokeWidth={2} dot={false} isAnimationActive={false} />
                      <Line type="monotone" dataKey="spo2" name="SpO2" stroke="#51cf66" strokeWidth={2} dot={false} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>

                {/* กล่องแจ้งเตือน */}
                <div
                  style={{
                    padding: "10px",
                    borderRadius: "6px",
                    backgroundColor:
                      p.status === "CRITICAL"
                        ? "#ff000022"
                        : p.status === "WARNING"
                        ? "#ffaa0022"
                        : "#00ff0022",
                    color: getStatusColor(p.status),
                    fontSize: "0.85rem",
                    fontWeight: "bold",
                  }}
                >
                  {p.alert_message}
                </div>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}