"use client";

import { useCallback, useEffect, useState } from 'react';
import s from './Ward.module.css';

type Device = {
  device_id: string; kind: 'vital' | 'pressure_mat'; last_seen: number;
  battery_percent: number; signal_quality: number; sensor_attached: boolean;
  calibration_due_at?: number | null; status: 'OK' | 'WARNING' | 'CRITICAL' | 'STALE';
  issues: string[]; source: string;
};
type Posture = {
  id: number; prediction: string; confidence?: number | null; observed_at: number;
  model_version: string; dwell_seconds?: number | null; model_output_blinded?: boolean;
};
type Bedside = {
  patient_id: string; devices: Device[]; posture: Posture | null;
  ground_truth: { id: number; observation_id?: number | null; label_type: string; label: string; notes: string; recorded_by: string; observed_at: number }[];
  posture_model: { status: string; version: string; error?: string | null };
  research_only: boolean;
};

const issueLabel: Record<string, string> = {
  SENSOR_DETACHED: 'เซนเซอร์หลุด', BATTERY_CRITICAL: 'แบตเตอรี่ใกล้หมด', BATTERY_LOW: 'แบตเตอรี่ต่ำ',
  SIGNAL_CRITICAL: 'สัญญาณขาด/อ่อนมาก', SIGNAL_LOW: 'สัญญาณอ่อน', CALIBRATION_DUE: 'ถึงกำหนดสอบเทียบ',
  HEARTBEAT_LOST: 'ไม่ได้รับ heartbeat',
};
const postureLabel: Record<string, string> = { left: 'ตะแคงซ้าย', right: 'ตะแคงขวา', supine: 'นอนหงาย', ABSTAIN: 'AI งดสรุป', HIDDEN_PENDING_GROUND_TRUTH: 'ซ่อนผล AI รอ Ground Truth' };
const kindLabel = { vital: 'อุปกรณ์วัดสัญญาณชีพ (Vital Sensor)', pressure_mat: 'แผ่นวัดแรงกดบนเตียง (Pressure Mat)' };
const time = (value?: number | null) => value ? new Date(value * 1000).toLocaleString('th-TH', { hour12: false }) : '—';

const TURN_INTERVAL_SECONDS = 7200; // 2 hours clinical protocol

function getBatteryStatus(percent: number) {
  if (percent <= 20) {
    return { state: 'critical', text: 'วิกฤต (<20%)', badgeClass: s.badgeCritical, fillClass: s.meterFillCritical };
  }
  if (percent <= 40) {
    return { state: 'warning', text: 'ต่ำ (20-40%)', badgeClass: s.badgeWarning, fillClass: s.meterFillWarning };
  }
  return { state: 'good', text: 'ปกติ (>40%)', badgeClass: s.badgeGood, fillClass: s.meterFillGood };
}

function getSignalStatus(quality: number) {
  const pct = Math.round(quality * 100);
  if (quality < 0.5) {
    return { pct, state: 'critical', text: 'อ่อนมาก (<50%)', badgeClass: s.badgeCritical, fillClass: s.meterFillCritical };
  }
  if (quality < 0.75) {
    return { pct, state: 'warning', text: 'ปานกลาง', badgeClass: s.badgeWarning, fillClass: s.meterFillWarning };
  }
  return { pct, state: 'good', text: 'เสถียร (≥75%)', badgeClass: s.badgeGood, fillClass: s.meterFillGood };
}

function getTurnStatus(dwellSeconds?: number | null) {
  if (dwellSeconds == null) {
    return {
      state: 'unknown',
      badgeClass: s.badgeGood,
      badgeText: 'รอข้อมูล',
      title: 'ยังไม่มีข้อมูลระยะเวลาท่า',
      guidance: 'รอข้อมูลการตรวจจับแรงกดบนเตียงเพื่อคำนวณรอบพลิกตัว',
      minutes: 0,
      percent: 0,
      fillClass: s.meterFillGood,
    };
  }
  const minutes = Math.max(0, Math.round(dwellSeconds / 60));
  const percent = Math.min(100, Math.round((dwellSeconds / TURN_INTERVAL_SECONDS) * 100));

  if (dwellSeconds >= TURN_INTERVAL_SECONDS) {
    return {
      state: 'due',
      badgeClass: s.badgeCritical,
      badgeText: 'ถึงกำหนดพลิกตัวทันที',
      title: `🚨 ถึงเวลาพลิกตัวทันที (อยู่ท่าเดิม ${minutes} นาที / เกิน 2 ชม.)`,
      guidance: 'ผู้ป่วยอยู่ท่าเดิมเกิน 2 ชั่วโมง มีความเสี่ยงต่อแผลกดทับสูง ควรเข้าตรวจประเมินผิวหนังและช่วยพลิกตัวจัดท่านอนใหม่ทันที',
      minutes,
      percent,
      fillClass: s.meterFillCritical,
    };
  }
  if (dwellSeconds >= 5400) {
    const remaining = Math.max(1, Math.round((TURN_INTERVAL_SECONDS - dwellSeconds) / 60));
    return {
      state: 'warning',
      badgeClass: s.badgeWarning,
      badgeText: 'ใกล้ถึงกำหนด',
      title: `⏳ ใกล้ถึงเวลาพลิกตัว (อีกประมาณ ${remaining} นาที)`,
      guidance: `อยู่ท่าเดิมมาแล้ว ${minutes} นาที ควรเตรียมเข้าช่วยจัดท่านอนใหม่ในอีกไม่เกิน ${remaining} นาที`,
      minutes,
      percent,
      fillClass: s.meterFillWarning,
    };
  }
  const remaining = Math.max(1, Math.round((TURN_INTERVAL_SECONDS - dwellSeconds) / 60));
  return {
    state: 'normal',
    badgeClass: s.badgeGood,
    badgeText: 'ตามเกณฑ์รอบเวลา',
    title: `✓ ท่าอยู่ในเกณฑ์เวลา (อยู่ท่านี้ ${minutes} นาที)`,
    guidance: `พลิกตัวตามรอบปกติ รอบถัดไปในอีกประมาณ ${remaining} นาที (เกณฑ์มาตรฐานทุก 2 ชม.)`,
    minutes,
    percent,
    fillClass: s.meterFillGood,
  };
}

export default function BedsidePanel({ patientId }: { patientId: string }) {
  const [data, setData] = useState<Bedside | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [label, setLabel] = useState('supine');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const load = useCallback(async () => {
    try {
      const response = await fetch(`/api/bedside/patients/${patientId}`, { cache: 'no-store' });
      if (!response.ok) throw new Error('bedside unavailable');
      setData(await response.json() as Bedside); setError('');
    } catch { setError('อ่านสถานะอุปกรณ์ข้างเตียงไม่ได้ อย่าตีความว่าอุปกรณ์ปกติ'); }
    finally { setLoading(false); }
  }, [patientId]);
  useEffect(() => {
    const initial = window.setTimeout(() => void load(), 0);
    const timer = window.setInterval(() => void load(), 10000);
    return () => { window.clearTimeout(initial); window.clearInterval(timer); };
  }, [load]);

  async function saveTruth() {
    if (!data?.posture || saving) return;
    setSaving(true); setMessage('');
    try {
      const requestKey = `posture-${patientId}-${data.posture.id}-${crypto.randomUUID()}`;
      const response = await fetch('/api/bedside/ground-truth', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_key: requestKey, patient_id: patientId, observation_id: data.posture.id,
          label_type: 'posture', label, notes, observed_at: data.posture.observed_at }),
      });
      if (!response.ok) throw new Error('save failed');
      setNotes(''); setMessage('บันทึก Ground Truth แล้ว โดยแยกจากผลทำนายของ AI'); await load();
    } catch { setMessage('บันทึกไม่สำเร็จ กรุณาลองใหม่และตรวจสิทธิ์บัญชี'); }
    finally { setSaving(false); }
  }

  return <section className={s.bedsidePanel} aria-labelledby={`bedside-${patientId}`}>
    <div className={s.cardHead}><div><span className={s.eyebrow}>DEVICE HEALTH & BED POSTURE</span><h3 id={`bedside-${patientId}`}>อุปกรณ์และท่าบนเตียง</h3></div><button className={s.secondary} onClick={() => void load()} disabled={loading}>↻ ตรวจอีกครั้ง</button></div>
    <p className={s.disclaimer}>ผลท่าเป็นโมเดลงานวิจัยจาก pressure map 32×64 และไม่ใช่การวินิจฉัยแผลกดทับ ต้องตรวจผู้ป่วยจริงก่อนดำเนินการ</p>
    {error && <p className={s.error} role="alert">{error}</p>}
    {loading && !data ? <p role="status">กำลังอ่านสถานะอุปกรณ์…</p> : data && <>
      <div className={s.deviceGrid}>{data.devices.length ? data.devices.map(device => {
        const bat = getBatteryStatus(device.battery_percent);
        const sig = getSignalStatus(device.signal_quality);
        const isPressureMat = device.kind === 'pressure_mat';
        return (
          <article key={device.kind} className={s.deviceCard} data-status={device.status}>
            <div className={s.cardHead}>
              <div>
                <b>{isPressureMat ? '🛏️ ' : '🩺 '}{kindLabel[device.kind]}</b>
                <small className={s.blockSmall} style={{ fontSize: 11, color: 'var(--muted)' }}>
                  รหัสเครื่อง: {device.device_id}
                </small>
              </div>
              <span className={s.pill} style={{
                borderColor: device.status === 'OK' ? '#247354' : device.status === 'WARNING' ? '#936511' : '#ad394b',
                color: device.status === 'OK' ? '#1b5e46' : device.status === 'WARNING' ? '#80520b' : '#a42c3d',
                background: device.status === 'OK' ? '#eaf5ef' : device.status === 'WARNING' ? '#fff3d9' : '#fff0f1',
              }}>
                {device.status === 'OK' ? 'พร้อมใช้งาน' : device.status === 'STALE' ? 'ข้อมูลขาดช่วง' : 'ต้องตรวจ'}
              </span>
            </div>

            <dl className={s.deviceFacts} style={{ margin: '12px 0 8px' }}>
              <div className={s.deviceFactCard} data-state={bat.state}>
                <div className={s.deviceFactHead}>
                  <dt>แบตเตอรี่</dt>
                  <span className={`${s.deviceFactBadge} ${bat.badgeClass}`}>{bat.text}</span>
                </div>
                <dd style={{ fontSize: 16, margin: '4px 0 2px' }}>{Math.round(device.battery_percent)}%</dd>
                <div className={s.meterTrack}>
                  <div className={`${s.meterFill} ${bat.fillClass}`} style={{ width: `${Math.min(100, Math.max(0, device.battery_percent))}%` }} />
                </div>
              </div>

              <div className={s.deviceFactCard} data-state={sig.state}>
                <div className={s.deviceFactHead}>
                  <dt>คุณภาพสัญญาณ</dt>
                  <span className={`${s.deviceFactBadge} ${sig.badgeClass}`}>{sig.text}</span>
                </div>
                <dd style={{ fontSize: 16, margin: '4px 0 2px' }}>{sig.pct}%</dd>
                <div className={s.meterTrack}>
                  <div className={`${s.meterFill} ${sig.fillClass}`} style={{ width: `${Math.min(100, Math.max(0, sig.pct))}%` }} />
                </div>
              </div>

              <div className={s.deviceFactCard} data-state={device.sensor_attached ? 'good' : 'critical'}>
                <div className={s.deviceFactHead}>
                  <dt>การติดตั้งเซนเซอร์</dt>
                  <span className={`${s.deviceFactBadge} ${device.sensor_attached ? s.badgeGood : s.badgeCritical}`}>
                    {device.sensor_attached ? 'ปกติ' : 'หลุด/ขยับ'}
                  </span>
                </div>
                <dd style={{ fontSize: 13, margin: '4px 0 2px', color: device.sensor_attached ? '#1b5e46' : '#a42c3d' }}>
                  {device.sensor_attached ? '✓ ติดแนบสนิท' : '⚠ เซนเซอร์หลุด'}
                </dd>
              </div>

              <div className={s.deviceFactCard} data-state="good">
                <div className={s.deviceFactHead}>
                  <dt>อัปเดตล่าสุด</dt>
                  <span className={`${s.deviceFactBadge} ${s.badgeGood}`}>สด</span>
                </div>
                <dd style={{ fontSize: 12, margin: '4px 0 2px', fontWeight: 600 }}>{time(device.last_seen)}</dd>
              </div>
            </dl>

            {device.issues.length > 0 ? (
              <div className={s.deviceIssues}>
                {device.issues.map(issue => (
                  <span key={issue} className={s.issuePill}>
                    ⚠ {issueLabel[issue] ?? issue}
                  </span>
                ))}
              </div>
            ) : (
              <small className={s.muted} style={{ display: 'block', fontSize: 11, marginTop: 4 }}>
                ✓ ไม่พบ fault จาก telemetry ล่าสุด · {device.device_id}
              </small>
            )}
          </article>
        );
      }) : <p className={s.empty}>ยังไม่เคยได้รับ heartbeat จากอุปกรณ์ของผู้ป่วยรายนี้</p>}</div>

      {/* แผ่นวัดแรงกดและการเตือนพลิกตัวสำหรับพยาบาลเวร */}
      {(() => {
        const turn = getTurnStatus(data.posture?.dwell_seconds);
        return (
          <div className={s.turnReminderBox} data-turn-state={turn.state}>
            <div className={s.turnHead}>
              <h4 className={s.turnTitle}>
                <span>{turn.title}</span>
              </h4>
              <span className={`${s.deviceFactBadge} ${turn.badgeClass}`} style={{ fontSize: 11, padding: '3px 8px' }}>
                {turn.badgeText}
              </span>
            </div>

            <div className={s.turnProgressWrap}>
              <div className={s.turnProgressInfo}>
                <span>รอบการพลิกตัว (มาตรฐานการพยาบาลทุก 2 ชม. / 120 นาที)</span>
                <b>{turn.minutes} / 120 นาที ({turn.percent}%)</b>
              </div>
              <div className={s.turnProgressBar}>
                <div className={`${s.turnProgressFill} ${turn.fillClass}`} style={{ width: `${turn.percent}%` }} />
              </div>
            </div>

            <p className={s.turnGuidance}>
              <strong>คำแนะนำพยาบาลเวร:</strong> {turn.guidance}
            </p>
          </div>
        );
      })()}

      <div className={s.postureGrid}><article className={s.box}><h3>{data.posture?.model_output_blinded ? 'Blinded evaluation' : 'ผล AI หลังยืนยันเฉลย'}</h3>{data.posture ? <>
        <strong className={s.postureValue}>{postureLabel[data.posture.prediction] ?? data.posture.prediction}</strong>
        {data.posture.model_output_blinded ? <p>ระบบซ่อน prediction และ confidence เพื่อไม่ให้คำตอบ AI ชี้นำผู้บันทึก กรุณาตรวจท่าจริงแล้วบันทึก Ground Truth ก่อน</p> : <p>ความเชื่อมั่นของโมเดล {data.posture.confidence == null ? '—' : `${Math.round(data.posture.confidence * 100)}%`} · อยู่ท่านี้ต่อเนื่อง {data.posture.dwell_seconds == null ? '—' : `${Math.round(data.posture.dwell_seconds / 60)} นาที`}</p>}
        <small>วัดเมื่อ {time(data.posture.observed_at)} · {data.posture.model_version}</small>
      </> : <p>ยังไม่มี pressure map ที่ผ่านการตรวจรูปแบบ</p>}</article>
      <article className={s.box}><h3>บุคลากรยืนยันเฉลยจริง (Ground Truth)</h3><p className={s.muted}>ตรวจท่าจริงก่อนเลือก ค่านี้ใช้ประเมินและปรับปรุงโมเดลภายหลัง ไม่แก้คำตอบ AI ย้อนหลัง</p>
        <label className={s.blockSmall}>ท่าที่ตรวจพบ<select className={s.input} value={label} onChange={event => setLabel(event.target.value)} disabled={!data.posture || saving}><option value="supine">นอนหงาย</option><option value="left">ตะแคงซ้าย</option><option value="right">ตะแคงขวา</option><option value="other">ท่าอื่น</option><option value="empty_bed">ไม่มีผู้ป่วยบนเตียง</option></select></label>
        <label className={s.blockSmall}>หมายเหตุ<input className={s.input} maxLength={500} value={notes} onChange={event => setNotes(event.target.value)} placeholder="เช่น ผู้ดูแลตรวจด้วยตาเวลา 10:30" /></label>
        <button className={s.primary} disabled={!data.posture || saving} onClick={() => void saveTruth()}>{saving ? 'กำลังบันทึก…' : 'ยืนยัน Ground Truth'}</button>
        {message && <p className={message.startsWith('บันทึก Ground') ? s.notice : s.error} role="status">{message}</p>}
      </article></div>

      <details className={s.learnMoreDrawer}>
        <summary className={s.learnMoreSummary}>
          <span>🛏️ รายละเอียดโมเดลแผ่นวัดแรงกด 32×64 การประเมินแบบปกปิด (Blinded) และประวัติเฉลย (Learn More)</span>
          <span className={s.learnMoreBadge}>Ground Truth ({data.ground_truth.length})</span>
        </summary>
        <div className={s.learnMoreBody}>
          <p className={s.muted} style={{ marginTop: 0 }}>
            <b>สถานะโมเดลข้างเตียง:</b> {data.posture_model.status} · รุ่น {data.posture_model.version} {data.posture_model.error ? `· (${data.posture_model.error})` : ''} · สกัด 128 Spatial Features จากตารางแรงกด 32×64
          </p>
          <p className={s.muted}>
            <b>เหตุผลของการปกปิดผลลัพธ์ (Blinded Evaluation):</b> ระบบซ่อนคำทำนายของ AI จนกว่าพยาบาลจะบันทึกท่าจริงของผู้ป่วย เพื่อป้องกัน Confirmation Bias และเก็บข้อมูล Ground Truth คุณภาพสูงสำหรับตรวจสอบความแม่นยำภายหลัง
          </p>
          {data.ground_truth.length > 0 ? (
            <>
              <p className={s.muted}>มีเฉลยที่บุคลากรยืนยันล่าสุด {data.ground_truth.length} รายการ · รายการล่าสุด: {postureLabel[data.ground_truth[0].label] ?? data.ground_truth[0].label} เมื่อ {time(data.ground_truth[0].observed_at)}</p>
              <div className={s.tableWrap} style={{ marginTop: 8 }}>
                <table className={s.table}>
                  <thead>
                    <tr>
                      <th>เวลาที่ตรวจ</th>
                      <th>ท่าจริงที่ยืนยัน</th>
                      <th>ผู้บันทึก</th>
                      <th>หมายเหตุ</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.ground_truth.slice(0, 5).map((item) => (
                      <tr key={item.id}>
                        <td>{time(item.observed_at)}</td>
                        <td><b>{postureLabel[item.label] ?? item.label}</b></td>
                        <td>{item.recorded_by}</td>
                        <td>{item.notes || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <p className={s.muted} style={{ marginBottom: 0 }}>ยังไม่มีรายการยืนยันเฉลยจริงสำหรับผู้ป่วยรายนี้</p>
          )}
        </div>
      </details>
    </>}
  </section>;
}
