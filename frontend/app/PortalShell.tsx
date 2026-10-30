"use client";

import { Fragment, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import Brand from "./Brand";
import AccountProfile from './AccountProfile';
import { ApiError, requestJson } from './apiRequest';

export default function PortalShell({ audience, children }: { audience: "staff" | "patient"; children: ReactNode }) {
  const [subject, setSubject] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState<string | null>(null);
  const [checking, setChecking] = useState(true);
  const [credential, setCredential] = useState("");
  const [username, setUsername] = useState('clinician');
  const [patientPassword, setPatientPassword] = useState('');
  const [demoLogin, setDemoLogin] = useState(false);
  const [testAccount, setTestAccount] = useState<{ subject: string; display_name: string; role: string } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [connectionError, setConnectionError] = useState('');
  const [checkVersion, setCheckVersion] = useState(0);
  const sessionVersion = useRef(0);
  useEffect(() => {
    const abort = new AbortController();
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    let inFlight = false;
    async function check() {
      if (stopped || inFlight) return;
      inFlight = true;
      clearTimeout(timer);
      const version = sessionVersion.current;
      try {
        const data = await requestJson<{ subject: string; display_name?: string }>("/api/session", { signal: abort.signal });
        if (!stopped && version === sessionVersion.current) { setSubject(data.subject); setDisplayName(data.display_name ?? data.subject); setConnectionError(''); }
      } catch (error) {
        if (!stopped && version === sessionVersion.current) {
          if (error instanceof ApiError && [401, 403].includes(error.status)) { setSubject(null); setDisplayName(null); setConnectionError(''); }
          else setConnectionError('ยังเชื่อมต่อเซิร์ฟเวอร์ไม่ได้ ข้อมูลอาจไม่อัปเดต ระบบจะลองเชื่อมต่ออีกครั้ง');
        }
      } finally { inFlight = false; if (!stopped) { setChecking(false); timer = setTimeout(check, 30000); } }
    }
    void requestJson<{ demo_login: boolean; test_account: typeof testAccount }>('/api/session/config', { signal: abort.signal }).then(data => { if (!stopped) { setDemoLogin(data.demo_login === true); setTestAccount(data.test_account ?? null); } }).catch(() => {});
    const expired = () => { sessionVersion.current++; setSubject(null); setDisplayName(null); setError('เซสชันหมดอายุ กรุณาเข้าสู่ระบบอีกครั้ง'); };
    const resume = () => { if (!document.hidden) void check(); };
    window.addEventListener('ward:session-expired', expired);
    window.addEventListener('online', resume);
    window.addEventListener('pageshow', resume);
    document.addEventListener('visibilitychange', resume);
    void check();
    return () => { stopped = true; abort.abort(); clearTimeout(timer); window.removeEventListener('ward:session-expired', expired); window.removeEventListener('online', resume); window.removeEventListener('pageshow', resume); document.removeEventListener('visibilitychange', resume); };
  }, [checkVersion]);

  async function login(event: FormEvent) {
    event.preventDefault(); if (busy) return; sessionVersion.current++; setBusy(true); setError("");
    try {
      const data = await requestJson<{ subject: string; display_name?: string }>("/api/session/login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(audience === "patient" ? { patient_id: credential, password: patientPassword } : { username, password: credential }),
      });
      sessionVersion.current++; setSubject(data.subject); setDisplayName(data.display_name ?? data.subject); setCredential(""); setPatientPassword(''); setConnectionError('');
    } catch (e) { setError(e instanceof ApiError && e.status === 401 ? 'ข้อมูลเข้าสู่ระบบไม่ถูกต้อง' : e instanceof Error ? e.message : "เชื่อมต่อไม่ได้"); }
    finally { setBusy(false); }
  }
  async function logout() {
    if (busy) return;
    sessionVersion.current++; setBusy(true); setError('');
    try {
      await requestJson("/api/session/logout", { method: "POST" });
      sessionVersion.current++; setSubject(null); setDisplayName(null); setConnectionError('');
    } catch { setError("ออกจากระบบไม่สำเร็จ กรุณาลองใหม่"); }
    finally { setBusy(false); }
  }
  if (checking) return <main className="login-form-area" style={{ minHeight: "100dvh" }} role="status">กำลังตรวจสอบการเข้าสู่ระบบ…</main>;
  if (!subject) return <main className="portal-login"><section className="login-story"><div className="login-brand"><Brand large /></div><h2>ข้อมูลที่เข้าใจง่าย<br />เพื่อการดูแลที่ใกล้ชิดขึ้น</h2><p>ติดตามสัญญาณชีพ จัดลำดับสิ่งที่ต้องตรวจสอบ และให้ AI ช่วยเตรียมข้อมูลในที่เดียว</p><ul className="login-pillars" aria-label="จุดเด่นระบบคลินิก"><li><b>3-Second Clinical Triage</b><span>จัดลำดับผู้ป่วยวิกฤตและสัญญาณชีพแบบเรียลไทม์ อ่านค่าสำคัญได้ใน 3 วินาที</span></li><li><b>Closed-Loop Care &amp; SBAR</b><span>จัดการแผนดูแล ส่งต่อเวรด้วย SBAR และสื่อสารสองทางระหว่างแพทย์กับผู้ป่วย</span></li><li><b>Explainable AI Guardrails</b><span>ช่วยสรุปแนวโน้มพร้อมหลักฐานตรวจสอบย้อนหลัง โดยมีบุคลากรตัดสินใจเสมอ</span></li></ul><small>60 เตียงสาธิต · 3 โซน · มีบุคลากรตรวจสอบทุกการตัดสินใจ</small></section><div className="login-form-area"><form className="portal-card" onSubmit={login}>
    <span className="portal-kicker">{audience === "patient" ? "PATIENT PORTAL" : "CARE TEAM PORTAL"} · RESEARCH DEMO</span>
    <h1>{audience === "patient" ? "พื้นที่ผู้ป่วย" : "ศูนย์ดูแลผู้ป่วย"}</h1>
    <p>{audience === "patient" ? "เข้าสู่บัญชีเพื่อดูข้อมูลของคุณ ติดต่อทีมดูแล และติดตามผลวิเคราะห์" : "สำหรับแพทย์และพยาบาล · เข้าถึงผู้ป่วยตามสิทธิ์การดูแลของบัญชี"}</p>
    {audience === 'staff' && <><label htmlFor="staff-username">ชื่อบัญชีบุคลากร</label><input id="staff-username" value={username} onChange={e => setUsername(e.target.value)} autoComplete="username" required /></>}
    <label htmlFor="credential">{audience === "patient" ? "รหัสผู้ป่วย" : "รหัสผ่านบุคลากร"}</label>
    <input id="credential" required value={credential} onChange={(e) => setCredential(e.target.value)} type={audience === "patient" ? "text" : "password"} autoComplete={audience === "patient" ? "username" : "current-password"} autoCapitalize="none" spellCheck={false} placeholder={audience === "patient" ? "เช่น A001 หรือ test_p" : "รหัสผ่านของบัญชีบุคลากร"} />
    {audience === 'patient' && <><label htmlFor="patient-password">รหัสผ่าน {demoLogin ? '(บัญชีสาธิตที่ยังไม่ตั้งรหัสผ่านเว้นว่างได้)' : ''}</label><input id="patient-password" type="password" autoComplete="current-password" required={!demoLogin} value={patientPassword} onChange={e => setPatientPassword(e.target.value)} /></>}
    {testAccount && <aside className="test-account"><b>บัญชี TEST สำหรับสาธิต</b><span>{testAccount.role} · {testAccount.display_name}</span><code>ID: {testAccount.subject} · Password: {audience === 'staff' ? 'admin1234' : 'admin4321'}</code><button type="button" onClick={() => { if (audience === 'staff') { setUsername('test_d'); setCredential('admin1234'); } else { setCredential('TEST_P'); setPatientPassword('admin4321'); } }}>กรอกบัญชีทดสอบ</button></aside>}
    <button disabled={busy}>{busy ? "กำลังเข้าสู่ระบบ…" : audience === "patient" ? "ดูข้อมูลของฉัน →" : "เข้าสู่ศูนย์ดูแลผู้ป่วย →"}</button>
    {error && <p role="alert">{error}</p>}
    {connectionError && <p role="status">{connectionError} <button type="button" disabled={busy} onClick={() => setCheckVersion(value => value + 1)}>ตรวจอีกครั้ง</button></p>}
    <small className="login-note">{demoLogin ? 'โหมดสาธิต · ข้อมูลผู้ป่วยสมมติ · ผู้ดูแลระบบสามารถสร้างบัญชีรายบุคคลและปิดการเข้าด้วย ID อย่างเดียวได้' : 'ใช้บัญชีที่ผู้ดูแลระบบออกให้ หากลืมรหัสผ่านให้ติดต่อผู้ดูแลระบบ'}</small>
  </form></div></main>;
  return <><a className="skip-link" href="#main-content">ข้ามไปเนื้อหาหลัก</a><header className="portal-session"><Brand /><span className="demo-badge">RESEARCH DEMO</span><span className="session-user-pill">{audience === "patient" ? "ผู้ป่วย" : "ทีมดูแล"} · {displayName ?? subject} ({subject})</span><AccountProfile key={`${audience}-${subject}`} audience={audience} /><button className="logout-button" disabled={busy} onClick={() => void logout()}>{busy ? 'กำลังออก…' : 'ออกจากระบบ'}</button></header>{connectionError && <div className="connection-banner" role="status">{connectionError} <button onClick={() => setCheckVersion(value => value + 1)}>ลองเชื่อมต่อใหม่</button></div>}{error && <div className="connection-banner" role="alert">{error}</div>}<Fragment key={`${audience}-${subject}`}>{children}</Fragment></>;
}
