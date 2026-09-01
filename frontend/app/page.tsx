"use client";

import { useEffect, useState, useRef } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

// ... (interface เดิม) ...
interface PatientProfile { name: string; age: number; gender: string; condition: string; doctor: string; }
interface HistoryPoint { time: string; heart_rate: number; spo2: number; is_anomaly?: boolean; }
interface PatientData { patient_id: string; patient_profile?: PatientProfile; heart_rate: number; spo2: number; status: "NORMAL" | "WARNING" | "CRITICAL"; alert_message: string; is_anomaly?: boolean; risk_percent?: number; history: HistoryPoint[]; }
interface DetailedPatientData { patient_id: string; profile: PatientProfile; ai_assessment: any; forecast: { predicted_hr: number | null; predicted_spo2: number | null; }; history: { heart_rate: number; spo2: number; status: string; timestamp: number }[]; }

export default function Dashboard() {
  const [patients, setPatients] = useState<{ [key: string]: PatientData }>({});
  const [connected, setConnected] = useState(false);
  
  const [selectedPatientId, setSelectedPatientId] = useState<string | null>(null);
  const [detailedData, setDetailedData] = useState<DetailedPatientData | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  
  // 💬 สถานะสำหรับระบบแชท
  const [chatHistory, setChatHistory] = useState<{sender: "user"|"ai", text: string}[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [isChatting, setIsChatting] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // เลื่อนหน้าจอแชทลงล่างสุดอัตโนมัติ
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory]);

  useEffect(() => {
    const ws = new WebSocket("ws://localhost:8000/ws/vitals");
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      const timeStr = new Date(data.timestamp * 1000).toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
      const newPoint: HistoryPoint = { time: timeStr, heart_rate: data.heart_rate, spo2: data.spo2, is_anomaly: data.is_anomaly };
      
      setPatients((prev) => {
        const existing = prev[data.patient_id];
        const updatedHistory = [...(existing ? existing.history : []), newPoint].slice(-15);
        return { ...prev, [data.patient_id]: { ...data, history: updatedHistory } };
      });
    };
    return () => ws.close();
  }, []);

  const openPatientDetail = async (patientId: string) => {
    setSelectedPatientId(patientId);
    setLoadingDetail(true);
    // รีเซ็ตแชทและให้ AI ทักทาย
    setChatHistory([{ sender: "ai", text: `สวัสดีค่ะ มีอะไรให้ AI ช่วยวิเคราะห์ข้อมูลของเตียง ${patientId} ไหมคะ? (เช่น "คนไข้มีโรคประจำตัวอะไร", "สรุปอาการให้หน่อย")` }]);
    setChatInput("");
    
    try {
      const res = await fetch(`http://localhost:8000/api/patient/${patientId}/details`);
      setDetailedData(await res.json());
    } catch (err) {
      console.error("Fetch error:", err);
    } finally {
      setLoadingDetail(false);
    }
  };

  // 💬 ฟังก์ชันส่งข้อความแชท
  const sendChatMessage = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!chatInput.trim() || !selectedPatientId) return;

    const userMsg = chatInput.trim();
    setChatHistory(prev => [...prev, { sender: "user", text: userMsg }]);
    setChatInput("");
    setIsChatting(true);

    try {
      const res = await fetch(`http://localhost:8000/api/patient/${selectedPatientId}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMsg })
      });
      const data = await res.json();
      setChatHistory(prev => [...prev, { sender: "ai", text: data.reply }]);
    } catch (err) {
      setChatHistory(prev => [...prev, { sender: "ai", text: "❌ เกิดข้อผิดพลาด ไม่สามารถเชื่อมต่อกับเซิร์ฟเวอร์ได้" }]);
    } finally {
      setIsChatting(false);
    }
  };

  const getStatusColor = (status: string) => status === "CRITICAL" ? "#ff4d4d" : status === "WARNING" ? "#ffaa00" : "#4dff4d";
  const getRiskColor = (risk: number) => risk >= 70 ? "#ff4d4d" : risk >= 40 ? "#ffaa00" : "#4dff4d";

  return (
    <div style={{ padding: "30px", fontFamily: "sans-serif", backgroundColor: "#121212", color: "#fff", minHeight: "100vh" }}>
      <header style={{ marginBottom: "25px", borderBottom: "1px solid #333", paddingBottom: "15px" }}>
        <h1 style={{ margin: "0 0 8px 0" }}>🏥 AI Patient Monitoring Dashboard</h1>
        <p style={{ margin: 0, color: "#aaa" }}>สถานะระบบ: {connected ? "🟢 ออนไลน์" : "🔴 ขาดการติดต่อ"}</p>
      </header>

      {/* หน้าการ์ดผู้ป่วย (เหมือนเดิม) */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))", gap: "20px" }}>
        {Object.values(patients).map((p) => (
          <div key={p.patient_id} style={{ borderRadius: "12px", padding: "20px", backgroundColor: "#1e1e1e", border: p.is_anomaly ? "2px solid #ffcc00" : `2px solid ${getStatusColor(p.status)}` }}>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <div>
                <h2 style={{ margin: "0 0 4px 0" }}>เตียง {p.patient_id}</h2>
                <div style={{ color: "#64b5f6" }}>{p.patient_profile?.name || "กำลังโหลด..."}</div>
              </div>
              <div style={{ textAlign: "right" }}>
                <span style={{ fontSize: "0.75rem", color: "#aaa" }}>Risk Score</span>
                <div style={{ backgroundColor: p.risk_percent !== undefined ? getRiskColor(p.risk_percent) : "#555", color: "#000", padding: "4px 8px", borderRadius: "4px", fontWeight: "bold" }}>
                  {p.risk_percent !== undefined ? `${p.risk_percent}%` : "--%"}
                </div>
              </div>
            </div>
            
            <div style={{ display: "flex", justifyContent: "space-around", margin: "15px 0", background: "#141414", padding: "10px", borderRadius: "8px" }}>
              <div style={{ textAlign: "center", color: "#ff6b6b", fontSize: "1.8rem", fontWeight: "bold" }}>{p.heart_rate}</div>
              <div style={{ textAlign: "center", color: "#51cf66", fontSize: "1.8rem", fontWeight: "bold" }}>{p.spo2}</div>
            </div>

            <div style={{ height: "120px", width: "100%", margin: "10px 0" }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={p.history}>
                  <Line type="monotone" dataKey="heart_rate" stroke="#ff6b6b" strokeWidth={2} dot={false} isAnimationActive={false} />
                  <Line type="monotone" dataKey="spo2" stroke="#51cf66" strokeWidth={2} dot={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <button onClick={() => openPatientDetail(p.patient_id)} style={{ width: "100%", padding: "10px", borderRadius: "6px", backgroundColor: "#2c2c2c", color: "#fff", cursor: "pointer" }}>
              🔍 ดูรายละเอียดเต็ม & พยากรณ์อาการ
            </button>
          </div>
        ))}
      </div>

      {/* 📌 MODAL */}
      {selectedPatientId && (
        <div style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, backgroundColor: "rgba(0,0,0,0.85)", display: "flex", justifyContent: "center", alignItems: "center", zIndex: 1000, padding: "20px" }}>
          <div style={{ backgroundColor: "#1e1e1e", borderRadius: "12px", width: "100%", maxWidth: "850px", maxHeight: "90vh", overflowY: "auto", padding: "25px" }}>
            
            <div style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid #333", paddingBottom: "15px" }}>
              <h2 style={{ margin: 0, color: "#4fc3f7" }}>📋 เตียง {selectedPatientId}</h2>
              <button onClick={() => setSelectedPatientId(null)} style={{ background: "none", border: "none", color: "#aaa", fontSize: "1.5rem", cursor: "pointer" }}>✕</button>
            </div>

            {loadingDetail || !detailedData ? (
              <p style={{ textAlign: "center", padding: "30px 0" }}>⏳ AI กำลังรวบรวมข้อมูล...</p>
            ) : (
              <div style={{ marginTop: "20px", display: "flex", gap: "20px", flexWrap: "wrap" }}>
                
                {/* ฝั่งซ้าย: ข้อมูลคนไข้ และพยากรณ์ */}
                <div style={{ flex: "1 1 300px" }}>
                  <div style={{ backgroundColor: "#141414", padding: "15px", borderRadius: "8px", marginBottom: "15px" }}>
                    <div><span style={{ color: "#aaa" }}>ชื่อ:</span> <strong>{detailedData.profile.name}</strong></div>
                    <div><span style={{ color: "#aaa" }}>โรคประจำตัว:</span> <strong style={{ color: "#ffb74d" }}>{detailedData.profile.condition}</strong></div>
                  </div>

                  <div style={{ backgroundColor: "#1b3a24", borderLeft: "5px solid #51cf66", padding: "15px", borderRadius: "8px" }}>
                    <h3 style={{ margin: "0 0 10px 0", color: "#51cf66" }}>📈 พยากรณ์ (3 นาที)</h3>
                    <div>HR: {detailedData.forecast.predicted_hr} | SpO2: {detailedData.forecast.predicted_spo2}</div>
                  </div>
                </div>

                {/* 💬 ฝั่งขวา: ระบบแชท AI */}
                <div style={{ flex: "1 1 400px", display: "flex", flexDirection: "column", backgroundColor: "#252525", borderRadius: "12px", border: "1px solid #444", height: "450px" }}>
                  <div style={{ backgroundColor: "#3a2a5d", padding: "12px", borderRadius: "12px 12px 0 0", fontWeight: "bold" }}>
                    ✨ ถาม-ตอบ กับ AI ผู้ช่วยแพทย์
                  </div>
                  
                  {/* พื้นที่แสดงข้อความ */}
                  <div style={{ flex: 1, padding: "15px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "10px" }}>
                    {chatHistory.map((msg, idx) => (
                      <div key={idx} style={{ alignSelf: msg.sender === "user" ? "flex-end" : "flex-start", maxWidth: "80%" }}>
                        <div style={{ fontSize: "0.75rem", color: "#888", marginBottom: "2px", textAlign: msg.sender === "user" ? "right" : "left" }}>
                          {msg.sender === "user" ? "คุณ" : "AI Assistant"}
                        </div>
                        <div style={{ backgroundColor: msg.sender === "user" ? "#4fc3f7" : "#333", color: msg.sender === "user" ? "#000" : "#fff", padding: "10px 14px", borderRadius: msg.sender === "user" ? "12px 12px 0 12px" : "12px 12px 12px 0", lineHeight: "1.4" }}>
                          {msg.text}
                        </div>
                      </div>
                    ))}
                    {isChatting && <div style={{ color: "#888", fontSize: "0.85rem" }}>กำลังพิมพ์...</div>}
                    <div ref={chatEndRef} />
                  </div>

                  {/* ช่องพิมพ์ข้อความ */}
                  <form onSubmit={sendChatMessage} style={{ display: "flex", padding: "10px", borderTop: "1px solid #444", backgroundColor: "#1e1e1e", borderRadius: "0 0 12px 12px" }}>
                    <input
                      type="text"
                      placeholder="พิมพ์คำถามที่นี่..."
                      value={chatInput}
                      onChange={(e) => setChatInput(e.target.value)}
                      disabled={isChatting}
                      style={{ flex: 1, padding: "10px", borderRadius: "6px", border: "1px solid #555", backgroundColor: "#141414", color: "#fff", outline: "none" }}
                    />
                    <button type="submit" disabled={isChatting || !chatInput.trim()} style={{ marginLeft: "10px", padding: "10px 20px", borderRadius: "6px", border: "none", backgroundColor: "#b388ff", color: "#000", fontWeight: "bold", cursor: "pointer" }}>
                      ส่ง
                    </button>
                  </form>
                </div>

              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}