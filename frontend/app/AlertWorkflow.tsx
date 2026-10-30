"use client";
import { useState } from 'react';
import s from './Ward.module.css';

export type AlertItem = {
  id: number; patient_id: string; zone: string; room_number: string; severity: 'warning' | 'critical';
  reason: string; recommended_next_step: string; status: 'NEW' | 'ACKNOWLEDGED' | 'ESCALATED' | 'RESOLVED';
  vitals: { heart_rate: number | null; spo2: number | null }; assigned_to?: string | null;
  created_at: number; resolved_at?: number | null; last_seen_at?: number; occurrences?: number;
  recovered_at?: number | null; version?: number; episode_key?: string; resolution_note?: string | null;
};

const labels = {
  NEW: 'รอรับผิดชอบ',
  ACKNOWLEDGED: 'มีผู้รับผิดชอบแล้ว',
  ESCALATED: 'รอประเมินเพิ่มเติม',
  RESOLVED: 'ปิดงานแล้ว',
};

const when = (t?: number | null) => t ? new Date(t * 1000).toLocaleString('th-TH', { hour12: false }) : '—';

const reasons: Record<string, string> = {
  spo2_low: 'ค่าออกซิเจนเข้าเกณฑ์แจ้งเตือน',
  heart_rate: 'ชีพจรเข้าเกณฑ์แจ้งเตือน',
  model_review: 'โมเดลเสนอให้ตรวจรูปแบบสัญญาณเพิ่มเติม',
  device_vital: 'อุปกรณ์วัดสัญญาณชีพต้องตรวจสอบ',
  device_pressure_mat: 'แผ่นวัดแรงกดต้องตรวจสอบ',
  posture_turn_due: 'AI เสนอให้ตรวจท่าและแผนพลิกตัว',
};

const QUICK_CLINICAL_NOTES = [
  'ตรวจสัญญาณชีพซ้ำที่เตียงแล้ว',
  'ปรับตำแหน่งเซนเซอร์และติดตามต่อ',
  'แจ้งแพทย์เวรรับทราบข้อมูลแล้ว',
  'ผู้ป่วยรู้สึกตัวดี สัญญาณชีพคงที่',
  'จัดท่านอนใหม่และดูแลทางเดินหายใจแล้ว',
  'เฝ้าระวังอาการใกล้ชิดตามรอบเวร',
];

export default function AlertWorkflow({ alerts, busy, openPatient, move }: {
  alerts: AlertItem[]; busy: number | null; openPatient: (id: string) => void;
  move: (id: number, status: 'ACKNOWLEDGED' | 'ESCALATED' | 'RESOLVED', note?: string, version?: number) => void;
}) {
  const [notes, setNotes] = useState<Record<number, string>>({});

  function addQuickNote(id: number, text: string) {
    setNotes(prev => {
      const current = (prev[id] ?? '').trim();
      if (!current) return { ...prev, [id]: text };
      if (current.includes(text)) return prev;
      return { ...prev, [id]: `${current} · ${text}` };
    });
  }

  if (!alerts.length) return <div className={s.empty}>ไม่มีเหตุการณ์ตรงกับตัวกรองนี้</div>;

  return (
    <div className={s.workflowList}>
      {alerts.map(a => {
        const isCritical = a.severity === 'critical';
        const pillTone = a.status === 'RESOLVED' ? s.resolve : isCritical ? s.critical : s.warning;
        return (
          <article
            key={a.id}
            className={s.workflowCard}
            style={{ borderColor: isCritical ? '#ad394b' : '#936511' }}
          >
            <div className={s.cardHead}>
              <button className={s.link} onClick={() => openPatient(a.patient_id)}>
                {a.patient_id} · โซน {a.zone} · ห้อง {a.room_number}
              </button>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span className={s.pill} style={{ borderColor: '#cbd9d2', color: '#2b4c3f', background: '#f7fbf9' }}>
                  ผู้รับผิดชอบ: {a.assigned_to ?? 'ยังไม่มีผู้รับผิดชอบ'}
                </span>
                <span className={`${s.pill} ${pillTone}`}>
                  {isCritical ? 'เร่งด่วน' : 'เฝ้าระวัง'} · {labels[a.status]}
                </span>
              </div>
            </div>

            <h3 style={{ margin: '10px 0 8px', fontSize: 17, fontWeight: 700 }}>
              {reasons[a.episode_key ?? ''] ?? a.reason}
            </h3>

            {(a.vitals.heart_rate != null || a.vitals.spo2 != null) && (
              <div className={s.vitals} style={{ margin: '8px 0 10px', alignItems: 'center', flexWrap: 'wrap' }}>
                <p style={{ margin: 0, fontWeight: 650, color: 'var(--ink)' }}>
                  ชีพจร {a.vitals.heart_rate ?? '—'} bpm · ออกซิเจน {a.vitals.spo2 ?? '—'}%{' '}
                  <small style={{ display: 'inline', marginLeft: 6, fontWeight: 450 }}>
                    ณ เหตุการณ์ล่าสุด ไม่ใช่ค่าวัดปัจจุบัน
                  </small>
                </p>
              </div>
            )}

            {a.recovered_at && a.status !== 'RESOLVED' && (
              <p className={s.notice} style={{ marginBottom: 10 }}>
                ค่าสัญญาณนี้ไม่เข้าเกณฑ์เดิมเมื่อ {when(a.recovered_at)} · ยังต้องตรวจสอบก่อนปิดงาน
              </p>
            )}

            <p className={s.next}>
              {a.recommended_next_step || 'ตรวจความถูกต้องของการวัดและประเมินผู้ป่วยตามแผนที่ทีมดูแลกำหนด'}
            </p>

            <details className={s.learnMoreDrawer}>
              <summary className={s.learnMoreSummary}>
                <span>🕒 ประวัติเวลาเกิดเหตุการณ์และรายละเอียดการติดตาม (Learn More)</span>
                <span className={s.learnMoreBadge}>ดูเวลา ({a.occurrences ?? 1} ครั้ง)</span>
              </summary>
              <div className={s.learnMoreBody}>
                <p className={s.muted} style={{ margin: 0 }}>
                  เริ่ม {when(a.created_at)}
                  <br />
                  พบครั้งล่าสุด {when(a.last_seen_at ?? a.created_at)} · รวม {a.occurrences ?? 1} ครั้ง
                  <br />
                  ผู้รับผิดชอบ: {a.assigned_to ?? 'ยังไม่มีผู้รับผิดชอบ'}
                </p>
              </div>
            </details>

            {a.status !== 'RESOLVED' && (
              <div className={s.blockSmall} style={{ marginTop: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                  <label htmlFor={`work-note-${a.id}`} style={{ fontWeight: 650, color: 'var(--ink)' }}>
                    ผลตรวจสอบ / เหตุผลส่งต่อ
                  </label>
                  <span className={s.muted} style={{ fontSize: 11 }}>บันทึกด่วนสำหรับพยาบาลเวร</span>
                </div>
                <div className={s.quickNoteContainer} role="group" aria-label="ข้อความบันทึกด่วนสำหรับพยาบาล">
                  <span className={s.quickNoteLabel}>ข้อความด่วน (คลิกเพื่อเพิ่มข้อความ):</span>
                  <div className={s.quickChips}>
                    {QUICK_CLINICAL_NOTES.map(chip => (
                      <button
                        key={chip}
                        type="button"
                        className={s.quickNoteChip}
                        onClick={() => addQuickNote(a.id, chip)}
                        title={`คลิกเพื่อใส่: ${chip}`}
                      >
                        + {chip}
                      </button>
                    ))}
                  </div>
                </div>
                <textarea
                  id={`work-note-${a.id}`}
                  className={s.workNote}
                  maxLength={500}
                  rows={2}
                  value={notes[a.id] ?? ''}
                  onChange={e => setNotes(v => ({ ...v, [a.id]: e.target.value }))}
                  placeholder="บันทึกสิ่งที่ตรวจพบและการดำเนินการ (อย่างน้อย 5 ตัวอักษรเมื่อส่งต่อหรือปิดงาน)"
                />
              </div>
            )}

            <div className={s.actions} style={{ marginTop: 12, marginBottom: 0 }}>
              {a.status === 'NEW' && (
                <button
                  className={s.primary}
                  disabled={busy !== null}
                  onClick={() => move(a.id, 'ACKNOWLEDGED', notes[a.id], a.version)}
                >
                  รับผิดชอบงานนี้
                </button>
              )}
              {['NEW', 'ACKNOWLEDGED'].includes(a.status) && (
                <button
                  className={s.critical}
                  disabled={busy !== null || (notes[a.id]?.trim().length ?? 0) < 5}
                  onClick={() => move(a.id, 'ESCALATED', notes[a.id], a.version)}
                >
                  บันทึกส่งต่อประเมิน
                </button>
              )}
              {['ACKNOWLEDGED', 'ESCALATED'].includes(a.status) && (
                <button
                  className={s.resolve}
                  disabled={busy !== null || (notes[a.id]?.trim().length ?? 0) < 5}
                  onClick={() => move(a.id, 'RESOLVED', notes[a.id], a.version)}
                >
                  บันทึกผลและปิดงาน
                </button>
              )}
              {a.status === 'RESOLVED' && (
                <p style={{ margin: 0, fontWeight: 600, color: 'var(--teal)' }}>
                  ปิดเมื่อ {when(a.resolved_at)} · {a.resolution_note}
                </p>
              )}
            </div>
          </article>
        );
      })}
    </div>
  );
}
