"use client";
import { useRef, useState } from 'react';
import { usePatientResource } from './usePatientResource';
import s from './Ward.module.css';

type Message = {
  id: number;
  patient_id?: string;
  topic: string;
  message: string;
  state: string;
  reply: string;
  created_at: number;
  assigned_to?: string;
};

const topics: Record<string, string> = {
  symptom: 'อาการที่ต้องการแจ้ง',
  device: 'ปัญหาอุปกรณ์',
  care: 'คำถามเรื่องการดูแล',
};

const labels: Record<string, string> = {
  NEW: 'บันทึกแล้ว · ยังไม่มีผู้รับเรื่อง',
  ACKNOWLEDGED: 'ทีมดูแลรับเรื่องแล้ว',
  RESOLVED: 'ทีมดูแลตอบและปิดรายการแล้ว',
};

const quickPresets = [
  { topic: 'care', label: 'ขอช่วยปรับท่าทางบนเตียง', text: 'ขอความช่วยเหลือปรับท่าทางหรือพลิกตัวบนเตียงตามรอบการดูแลครับ/ค่ะ' },
  { topic: 'device', label: 'เซนเซอร์หลวม / สัญญาณขาด', text: 'อุปกรณ์วัดสัญญาณชีพที่นิ้วหรือเตียงหลวม รบกวนช่วยตรวจสอบอุปกรณ์ให้ด้วยครับ/ค่ะ' },
  { topic: 'symptom', label: 'แจ้งอาการอ่อนเพลีย / ไม่สบายตัว', text: 'รู้สึกอ่อนเพลียหรือไม่สบายตัวเล็กน้อย รบกวนทีมดูแลช่วยประเมินในรอบถัดไปครับ/ค่ะ' },
  { topic: 'care', label: 'สอบถามแผนดูแลวันนี้', text: 'ต้องการสอบถามตารางเวลาและแผนการดูแลของวันนี้เพิ่มเติมครับ/ค่ะ' },
];

export default function CareMessages({ staff = false }: { staff?: boolean }) {
  const endpoint = staff ? '/api/care-messages' : '/api/me/messages';
  const { data, error, refresh } = usePatientResource<{ messages: Message[] }>(endpoint, 15000);
  const [topic, setTopic] = useState('care');
  const [message, setMessage] = useState('');
  const [replies, setReplies] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const requestKey = useRef<string | null>(null);

  async function submit(id?: number, state?: string) {
    if (busy) return;
    setBusy(true);
    setNotice('');
    try {
      if (!staff && !requestKey.current) requestKey.current = crypto.randomUUID();
      const response = await fetch(id ? `${endpoint}/${id}` : endpoint, {
        method: id ? 'PATCH' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(id ? { state, reply: replies[id] ?? '' } : { topic, message, request_key: requestKey.current }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'บันทึกไม่สำเร็จ');
      if (!staff) {
        setMessage('');
        requestKey.current = null;
      }
      setNotice(staff ? 'บันทึกแล้ว ผู้ป่วยสามารถดูสถานะล่าสุดได้' : 'บันทึกแล้ว กรุณารอสถานะรับเรื่องจากทีมดูแล');
      refresh();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : 'เชื่อมต่อไม่สำเร็จ');
    } finally {
      setBusy(false);
    }
  }

  const openCount = data?.messages.filter(m => m.state !== 'RESOLVED').length ?? 0;

  return (
    <section className={s.panel}>
      <div className={s.titleRow} style={{ marginBottom: 10 }}>
        <div>
          <div className={s.eyebrow}>ASYNCHRONOUS CARE REQUESTS · TRIAGE QUEUE</div>
          <h2 className={s.h2}>{staff ? 'ข้อความจากผู้ป่วยและผู้ดูแล' : 'แจ้งเรื่องให้ทีมดูแล'}</h2>
        </div>
        {data && (
          <span className={`${s.pill} ${openCount > 0 ? s.warning : s.resolve}`}>
            รอดำเนินการ {openCount} · ทั้งหมด {data.messages.length}
          </span>
        )}
      </div>

      <details className={s.learnMoreDrawer}>
        <summary className={s.learnMoreSummary}>
          <span>ℹ️ ขอบเขตการแจ้งเรื่องและการติดตามสถานะจากทีมดูแล (Learn More)</span>
          <span className={s.learnMoreBadge}>ดูคำแนะนำ</span>
        </summary>
        <div className={s.learnMoreBody}>
          <p className={s.muted} style={{ margin: 0 }}>
            ช่องทางติดตามทั่วไป · ไม่มีการเฝ้าตอบรับฉุกเฉิน หากต้องการความช่วยเหลือทันทีให้ติดต่อทีมดูแลโดยตรง
          </p>
        </div>
      </details>

      {!staff && (
        <form
          onSubmit={e => {
            e.preventDefault();
            void submit();
          }}
          style={{ marginBottom: 18, paddingBottom: 16, borderBottom: '1px solid var(--line)' }}
        >
          <p className={s.muted} style={{ margin: '8px 0 4px', fontSize: '14px' }}>
            แตะเลือกข้อความด่วนที่พบบ่อยได้ทันที โดยไม่ต้องพิมพ์เอง:
          </p>
          <div className={s.actions} role="group" aria-label="ข้อความด่วนสำหรับผู้ป่วย">
            {quickPresets.map(preset => (
              <button
                type="button"
                key={preset.label}
                className={s.quickButton}
                disabled={busy}
                onClick={() => {
                  setTopic(preset.topic);
                  setMessage(preset.text);
                  requestKey.current = null;
                }}
              >
                {preset.label}
              </button>
            ))}
          </div>
          <label>
            เรื่องที่ต้องการแจ้ง
            <select
              className={s.workNote}
              value={topic}
              onChange={e => {
                setTopic(e.target.value);
                requestKey.current = null;
              }}
              disabled={busy}
            >
              {Object.entries(topics).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label style={{ display: 'block', marginTop: 10 }}>
            รายละเอียด
            <textarea
              className={s.workNote}
              value={message}
              onChange={e => {
                setMessage(e.target.value);
                requestKey.current = null;
              }}
              maxLength={1000}
              minLength={5}
              required
              rows={3}
              disabled={busy}
            />
          </label>
          <div className={s.actions} style={{ marginBottom: 0 }}>
            <button className={s.primary} disabled={busy || message.trim().length < 5}>
              บันทึกเรื่องให้ทีมดูแล
            </button>
          </div>
        </form>
      )}

      {notice && <p className={s.notice} role="status">{notice}</p>}
      {error && <p role="alert" className={s.error}>{error}</p>}
      {!data && !error && <p role="status">กำลังโหลดข้อความ…</p>}
      {data?.messages.length === 0 && <p className={s.muted}>ยังไม่มีข้อความที่ต้องติดตาม</p>}

      {data?.messages.map(m => {
        const stateClass = m.state === 'RESOLVED' ? s.resolve : m.state === 'NEW' ? s.critical : s.warning;
        return (
          <article className={s.messageRow} key={m.id}>
            <div className={s.cardHead} style={{ marginBottom: 6 }}>
              <b>{staff ? `${m.patient_id} · ` : ''}{topics[m.topic]}</b>
              <span className={`${s.pill} ${stateClass}`}>
                {labels[m.state]}
              </span>
            </div>
            <p style={{ margin: '6px 0 8px' }}>{m.message}</p>
            <small className={s.muted}>
              {new Date(m.created_at * 1000).toLocaleString('th-TH')} · {labels[m.state]}
              {staff ? ` · ผู้รับผิดชอบ: ${m.assigned_to ?? 'ยังไม่มี'}` : ''}
            </small>
            {m.reply && (
              <p className={s.notice} style={{ marginTop: 10, marginBottom: 8 }}>
                ทีมดูแล: {m.reply}
              </p>
            )}
            {staff && m.state !== 'RESOLVED' && (
              <div style={{ marginTop: 10 }}>
                <label>
                  คำตอบที่ผู้ป่วยจะเห็น
                  <textarea
                    className={s.workNote}
                    value={replies[m.id] ?? ''}
                    onChange={e => setReplies(v => ({ ...v, [m.id]: e.target.value }))}
                    maxLength={1000}
                    rows={2}
                  />
                </label>
                <div className={s.actions} style={{ marginBottom: 0 }}>
                  {m.state === 'NEW' ? (
                    <button className={s.primary} disabled={busy} onClick={() => void submit(m.id, 'ACKNOWLEDGED')}>
                      รับเรื่อง
                    </button>
                  ) : (
                    <button
                      className={s.resolve}
                      disabled={busy || (replies[m.id]?.trim().length ?? 0) < 5}
                      onClick={() => void submit(m.id, 'RESOLVED')}
                    >
                      ส่งคำตอบและปิดรายการ
                    </button>
                  )}
                </div>
              </div>
            )}
          </article>
        );
      })}
    </section>
  );
}
