"use client";

import { useEffect, useState } from "react";

interface PatientData {
  patient_id: string;
  heart_rate: number;
  spo2: number;
  status: "NORMAL" | "WARNING" | "CRITICAL";
  alert_message: string;
}

//PatientDATA //
export default function Dashboard(){
  const [patients, setPatients] = useState<{[key: string]: PatientData}>({});
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const ws = new WebSocket("ws://localhost:8000/ws/vitals");

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);

    ws.onmessage = (event) => {
      const data: PatientData = JSON.parse(event.data);
      setPatients((prev) => ({
        ...prev,
        [data.patient_id]:data,
      }));
    };

    return () => ws.close();
  }, []);

  const getStatusColor = (status: string) => {
    if (status === "CRITICAL") return "Red";
    if (status === "WARNING") return "Yellow";
    return "Green";
  };

  const getCardBorder = (status: string ) => {
    if (status === "CRITICAL") return "border-red-500";
    if (status === "WARNING") return "border-yellow-500";
    return "border-green-500";
  };

 
  return (
    <div style={{ padding: "50px", fontSmooth: "sans-serif", backgroundColor: "#141414", color: "White", minHeight: "100vh" }}>
      <header style={{ marginBottom: "25px", borderBottom: "1px solid #333", paddingBottom: "15px" }}>
        <h1 style={{ margin: "0 0 20px 0" }}>Central Patient Monitoring Station</h1>
        <p style={{ margin: 0 }}>
          Status: {connected ? "🟢 Online (Reading Real-time)" : "🔴 ขาดการติดต่อกับเซิร์ฟเวอร์"}
        </p>
      </header>

      {Object.keys(patients).length === 0 ? (
        <p>กำลังรอรับสัญญาณชีพจากอุปกรณ์จำลอง...</p>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "20px" }}>
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
                    margin: "20px 0",
                    background: "#1a1a1a",
                    padding: "15px",
                    borderRadius: "8px",
                  }}
                >
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontSize: "0.85rem", color: "#aaa" }}>Heart Rate</div>
                    <div style={{ fontSize: "2rem", fontWeight: "bold", color: "#ff6b6b" }}>
                      {p.heart_rate} <span style={{ fontSize: "0.9rem" }}>bpm</span>
                    </div>
                  </div>
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontSize: "0.85rem", color: "#aaa" }}>SpO2</div>
                    <div style={{ fontSize: "2rem", fontWeight: "bold", color: "#51cf66" }}>
                      {p.spo2} <span style={{ fontSize: "0.9rem" }}>%</span>
                    </div>
                  </div>
                </div>

                {/* สถานะการแจ้งเตือน */}
                <div
                  style={{
                    padding: "12px",
                    borderRadius: "6px",
                    backgroundColor:
                      p.status === "CRITICAL"
                        ? "#ff000022"
                        : p.status === "WARNING"
                        ? "#ffaa0022"
                        : "#00ff0022",
                    color: getStatusColor(p.status),
                    fontSize: "0.95rem",
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
