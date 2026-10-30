"use client";
import { useState } from 'react';
import { usePatientResource } from './usePatientResource';
import s from './Ward.module.css';

type Status = {
  fresh_beds: number;
  total_beds: number;
  new_alerts: number;
  unclaimed_messages: number;
  chat_unread: number;
  push_ready: boolean;
  named_login: boolean;
  secure_cookie: boolean;
  worker: string;
  bedside?: {
    devices: Record<string, number>;
    ground_truth_labels: number;
    posture_observations: number;
    posture_model: string;
  };
};

const handoffItems = [
  "ตรวจสอบและจัดการเหตุการณ์รอรับผิดชอบ (Critical Alerts) ครบถ้วน",
  "ตรวจสอบและตอบกลับข้อความแจ้งเรื่อง / แชทผู้ป่วยที่ยังไม่มีผู้รับ",
  "ยืนยันสถานะการทำงานของเซนเซอร์ข้างเตียง แบตเตอรี่ และสัญญาณชีพ",
];

export default function OperationsPanel({
  alerts,
  messages,
  chat,
}: {
  alerts: () => void;
  messages: () => void;
  chat?: () => void;
}) {
  const { data, error } = usePatientResource<Status>('/api/operations/status', 15000);
  const [handoffChecks, setHandoffChecks] = useState<Record<number, boolean>>({});

  if (error) return <p role="alert" className={s.error}>อ่านสถานะการทำงานไม่สำเร็จ</p>;
  if (!data) return <p role="status">กำลังตรวจระบบ…</p>;

  const checkedCount = handoffItems.filter((_, idx) => Boolean(handoffChecks[idx])).length;
  const allChecked = checkedCount === handoffItems.length;

  return (
    <section className={s.panel}>
      <div className={s.titleRow} style={{ marginBottom: 10 }}>
        <div>
          <div className={s.eyebrow}>CLINICAL OPERATIONS · 3-SECOND TRIAGE</div>
          <h2 className={s.h2}>งานที่รอทีมดูแล</h2>
        </div>
        <span className={s.pill} style={{ borderColor: '#c9dfd3', background: '#f2f9f5', color: '#155d44' }}>
          เตียงออนไลน์ {data.fresh_beds}/{data.total_beds} · เช็กลิสต์ส่งเวร {checkedCount}/{handoffItems.length}
        </span>
      </div>

      <div className={s.actions} style={{ margin: '10px 0 12px' }}>
        <button className={s.critical} onClick={alerts}>🚨 เหตุการณ์รอรับผิดชอบ {data.new_alerts}</button>
        <button className={s.secondary} onClick={messages}>⚠️ ข้อความแจ้งเรื่องใหม่ {data.unclaimed_messages}</button>
        <button className={s.primary} onClick={chat ?? messages}>แชทแพทย์-ผู้ป่วยยังไม่อ่าน {data.chat_unread}</button>
      </div>

      <details className={s.learnMoreDrawer}>
        <summary className={s.learnMoreSummary}>
          <span>📋 ข้อมูลส่งต่อเวร เช็กลิสต์ และสถานะความพร้อมระบบ (Learn More)</span>
          <span className={s.learnMoreBadge}>ดูรายละเอียด</span>
        </summary>
        <div className={s.learnMoreBody}>
          <p className={s.notice}>
            คำแนะนำการส่งต่อเวรอย่างปลอดภัย (Shift Handoff Reminder): ตรวจสอบเหตุการณ์รอรับผิดชอบ ข้อความที่ยังไม่มีผู้รับ และยืนยันสถานะเซนเซอร์ข้างเตียงก่อนส่งมอบเวรทุกครั้ง
          </p>
          <div className={s.handoffChecklistBox}>
            <div className={s.handoffHead}>
              <h3 className={s.handoffTitle}>📋 เช็กลิสต์ส่งต่อเวร (Shift Handoff Checklist)</h3>
              <span className={allChecked ? s.handoffProgressDone : s.handoffProgress}>
                {allChecked ? "✅ ตรวจครบแล้ว 3/3 รายการ พร้อมส่งมอบเวร" : `ตรวจแล้ว ${checkedCount}/3 รายการ`}
              </span>
            </div>
            <ul className={s.handoffList}>
              {handoffItems.map((text, idx) => (
                <li key={idx} className={s.handoffItem}>
                  <label className={s.handoffLabel}>
                    <input
                      type="checkbox"
                      checked={Boolean(handoffChecks[idx])}
                      onChange={(e) => setHandoffChecks((prev) => ({ ...prev, [idx]: e.target.checked }))}
                      className={s.handoffCheckbox}
                    />
                    <span className={handoffChecks[idx] ? s.handoffDoneText : undefined}>{text}</span>
                  </label>
                </li>
              ))}
            </ul>
            <div className={s.handoffPrintBar}>
              <button type="button" className={s.printBtn} onClick={() => window.print()}>
                🖨️ สั่งพิมพ์ใบสรุปส่งเวร
              </button>
              <small className={s.printTip}>โหมดพิมพ์จะจัดรูปแบบกระดาษสีขาวคมชัดและซ่อนปุ่มระบบอัตโนมัติ</small>
            </div>
          </div>

          <details>
            <summary>สถานะระบบและการตั้งค่าก่อนทดลองใช้</summary>
            <ul className={s.operationalList}>
              <li>
                ตัวรับข้อมูล: {data.worker === 'RUNNING' ? '🟢 ทำงานอยู่' : '⚠️ ยังไม่พร้อม'} · มีข้อมูลเตียงใหม่ 🛏️ {data.fresh_beds}/{data.total_beds}
              </li>
              <li>
                บัญชีรายบุคคล: {data.named_login ? '🔒 ปิดการเข้าด้วย ID อย่างเดียวแล้ว' : '⚠️ ยังเปิดโหมดสาธิต'}
              </li>
              <li>
                Cookie ผ่าน HTTPS: {data.secure_cookie ? '🔒 เปิด' : '⚠️ ยังปิด เหมาะกับการทดสอบในเครื่อง'}
              </li>
              <li>
                Web Push: {data.push_ready ? '🔔 ตั้งค่าครบ ต้องทดสอบรับจริงบนโทรศัพท์' : '⚠️ ยังตั้งค่าไม่ครบ / ปิดอยู่'}
              </li>
              <li>
                เซนเซอร์ข้างเตียง: {Object.entries(data.bedside?.devices ?? {}).map(([key, value]) => `📟 ${key} ${value}`).join(' · ') || '⚠️ ยังไม่มี heartbeat'} · โมเดลท่า {data.bedside?.posture_model ?? 'UNAVAILABLE'}
              </li>
              <li>
                Pressure map {data.bedside?.posture_observations ?? 0} ครั้ง · Ground Truth ที่ยืนยันแล้ว {data.bedside?.ground_truth_labels ?? 0} รายการ
              </li>
            </ul>
            <p className={s.muted}>
              สถานะนี้แสดงความพร้อมทางเทคนิค การใช้งานกับผู้ป่วยจริงต้องผ่านการตรวจระบบและกระบวนการดูแลของหน่วยงาน
            </p>
          </details>
        </div>
      </details>
    </section>
  );
}
