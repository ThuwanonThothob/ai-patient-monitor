"use client";

import { useEffect, useRef, useState, type FormEvent } from 'react';
import Icon from './Icon';
import { requestJson } from './apiRequest';
import s from './AgentAssistant.module.css';

type Answer = { answer: string; steps: string[]; patient_id: string | null; as_of: number };
const sections: Record<string, string> = { overview: 'ภาพรวม', patients: 'ทะเบียนผู้ป่วย', triage: 'ติดตามการดูแล', chat: 'แชทแพทย์-ผู้ป่วย', alerts: 'เหตุการณ์แจ้งเตือน', ai: 'การทำงานของ Agent', research: 'งานวิจัย', reports: 'รายงาน', notifications: 'แจ้งเตือนมือถือ', evidence: 'หลักฐานโมเดล', care: 'แผนดูแล', trends: 'แนวโน้มย้อนหลัง', profile: 'ข้อมูลผู้ป่วย' };

export default function AgentAssistant({ patientId, section, staff = false }: { patientId?: string; section: string; staff?: boolean }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const controller = useRef<AbortController | null>(null);
  const [target, setTarget] = useState(patientId ?? '');
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => () => controller.current?.abort(), []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!question.trim() || busy) return;
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setBusy(true); setError(''); setAnswer(null);
    try {
      const data = await requestJson<Answer>('/api/assistant/ask', { method: 'POST', signal: current.signal,
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: question, patient_id: target || null, section }) }, 20000);
      if (!current.signal.aborted) setAnswer(data);
    } catch (e) { if (!current.signal.aborted) setError(e instanceof Error ? e.message : 'โหลดข้อมูลไม่สำเร็จ'); }
    finally { if (!current.signal.aborted) setBusy(false); }
  }
  return <>
    <button type="button" className={s.launcher} aria-label="เปิดผู้ช่วย Agentic" onClick={() => dialog.current?.showModal()}><Icon name="ai" size={24} /><span>ถาม Agentic<small>ผู้ช่วยอ่านข้อมูล</small></span></button>
    <dialog ref={dialog} className={s.dialog} aria-labelledby="agent-title" onClick={e => { if (e.target === dialog.current) dialog.current?.close(); }}>
      <header className={s.header}>
        <button type="button" className={s.close} aria-label="ปิดผู้ช่วย" onClick={() => dialog.current?.close()}>×</button>
        <div className={s.mark}><Icon name="ai" size={26} /></div>
        <div className={s.headerText}><small>SMART WARD · AGENTIC AI</small><h2 id="agent-title">ผู้ช่วยข้อมูลการดูแล</h2></div>
      </header>
      <div className={s.body}>
        <p className={s.context}>บริบท: {sections[section] ?? section} · {patientId || 'เลือกผู้ป่วยเพื่อเริ่มต้น'}</p>
        <p className={s.note}>เลือกเครื่องมืออ่านข้อมูลตามคำถาม พร้อมแสดงขั้นตอน ไม่ใช่แชทกับแพทย์ และไม่ดำเนินการรักษาแทนคน</p>
        <div className={s.suggestions}>{['สรุปค่าล่าสุด', 'อ่านกราฟแนวโน้มย้อนหลัง', 'มีงานดูแลอะไรบ้าง'].map(text => <button key={text} type="button" disabled={busy} onClick={() => setQuestion(text)}>{text}</button>)}</div>
        <form onSubmit={submit} className={s.form}>
          {staff && !patientId && <label>รหัสผู้ป่วย<input value={target} maxLength={20} disabled={busy} placeholder="เช่น A001" onChange={e => { setTarget(e.target.value.toUpperCase()); setAnswer(null); }} /></label>}
          <label>คำถามของคุณ<textarea value={question} onChange={e => setQuestion(e.target.value)} rows={3} maxLength={1000} disabled={busy} placeholder="ถามเกี่ยวกับค่าที่วัด แนวโน้ม หรือรายการดูแล…" /></label>
          <button className={s.send} disabled={busy || !question.trim() || (staff && !target.trim())}>{busy ? 'กำลังอ่านหลักฐาน…' : 'ให้ Agent ตรวจสอบ'}<Icon name="arrow" size={18} /></button>
        </form>
        {error && <p className={s.error} role="alert">{error} · ลองส่งคำถามอีกครั้ง</p>}
        <div aria-live="polite" aria-busy={busy}>{answer && <section className={s.answer}><b>ผลตรวจข้อมูล · {answer.patient_id ?? 'ยังไม่เลือกผู้ป่วย'}</b><p>{answer.answer}</p><details className={s.learnMoreDrawer}><summary className={s.learnMoreSummary}><span>ดูเครื่องมือและขั้นตอน ({answer.steps.length} · Learn More)</span><span className={s.learnMoreBadge}>Audit Steps</span></summary><div className={s.learnMoreBody}><ol>{answer.steps.map(step => <li key={step}>{step}</li>)}</ol><small>อ่านเมื่อ {new Date(answer.as_of * 1000).toLocaleString('th-TH', { timeZone: 'Asia/Bangkok' })} · ผลไม่อัปเดตเอง กดถามใหม่เพื่ออ่านล่าสุด</small></div></details></section>}</div>
      </div>
    </dialog>
  </>;
}

