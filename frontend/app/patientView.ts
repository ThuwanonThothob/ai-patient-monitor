import type { MonitorData } from './MonitorPanel';

export type PatientSection = 'overview' | 'trends' | 'care' | 'chat' | 'reports' | 'profile';
export const patientSections: { key: PatientSection; title: string; description: string; icon: string }[] = [
  { key: 'overview', title: 'ภาพรวม', description: 'ค่าล่าสุดและสิ่งที่ควรติดตาม', icon: 'overview' },
  { key: 'trends', title: 'แนวโน้มย้อนหลัง', description: 'เปรียบเทียบข้อมูล 1 ชั่วโมงถึง 7 วัน', icon: 'evidence' },
  { key: 'care', title: 'แผนดูแลของฉัน', description: 'งานที่ทีมดูแลยืนยันและสถานะล่าสุด', icon: 'care' },
  { key: 'chat', title: 'แชททีมดูแล', description: 'แชทข้อความกับแพทย์และทีมดูแล (Messenger)', icon: 'chat' },
  { key: 'reports', title: 'สรุปประจำวัน', description: 'เลือกวัน ดูสรุป และดาวน์โหลด', icon: 'reports' },
  { key: 'profile', title: 'ข้อมูลของฉัน', description: 'แยกประวัติที่ยืนยันจากข้อมูลสาธิต', icon: 'patients' },
];
export const sourceLabel = (source: string) => ({ BIDMC_REPLAY: 'BIDMC · ข้อมูลย้อนหลังเพื่อสาธิต', MQTT: 'MQTT · ข้อมูลที่ระบบรับเข้ามา', TEST_SIMULATION: 'TEST Simulation · เซนเซอร์บ้านจำลอง ไม่ใช่ข้อมูลจริง', UNKNOWN: 'ไม่ทราบแหล่งข้อมูล' }[source] ?? 'ยังไม่ทราบแหล่งข้อมูล');
export const careStateLabel = (state: string) => ({ ACTIVE: 'เปิดใช้งาน', PAUSED: 'พักแผน', COMPLETED: 'จบแผนแล้ว', PENDING: 'รอทีมดูแลรับงาน', ACKNOWLEDGED: 'ทีมดูแลรับงานแล้ว', DONE: 'บันทึกว่าเสร็จแล้ว', SKIPPED: 'บันทึกว่าข้าม', CANCELLED: 'ยกเลิกรอบนี้' }[state] ?? 'ยังไม่ทราบสถานะ');
export const displayValue = (value: number | null | undefined) => typeof value === 'number' && Number.isFinite(value) ? new Intl.NumberFormat('th-TH', { maximumFractionDigits: 1 }).format(value) : '—';
export function safeAnalysis(state: MonitorData | undefined, now: number, fresh: boolean) {
  const analysis = state?.analysis;
  const evaluated = analysis?.evaluated_at;
  return fresh && analysis?.status === 'READY' && typeof evaluated === 'number' && Number.isFinite(evaluated)
    && evaluated <= now && now - evaluated <= 30 ? analysis : null;
}

export type { CareTaskHistoryItem, CareTaskHistoryResponse } from './careView';
export { formatTaskTransition } from './careView';

