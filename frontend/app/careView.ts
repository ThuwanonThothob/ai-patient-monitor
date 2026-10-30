export const careVitals = ["heart_rate", "spo2", "respiratory_rate"] as const;
export type CareVital = typeof careVitals[number];
export const careVitalLabels: Record<CareVital, string> = { heart_rate: "ชีพจร (bpm)", spo2: "SpO₂ (%)", respiratory_rate: "การหายใจ (ครั้ง/นาที)" };
export function bangkokDay(date = new Date()) { return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Bangkok", year: "numeric", month: "2-digit", day: "2-digit" }).format(date); }
export function careTime(seconds: number) { return new Date(seconds * 1000).toLocaleString("th-TH", { timeZone: "Asia/Bangkok", hour12: false }); }
export function formRanges(form: FormData) {
  const result: Partial<Record<CareVital, { low: number; high: number }>> = {};
  for (const key of careVitals) {
    const low = String(form.get(key + "_low") ?? "").trim(), high = String(form.get(key + "_high") ?? "").trim();
    if (!low && !high) continue;
    if (!low || !high || !Number.isFinite(Number(low)) || !Number.isFinite(Number(high)) || Number(low) <= 0 || Number(low) >= Number(high)) throw new Error("กรอกขอบเขตต่ำ/สูงเป็นคู่ โดยค่าต่ำต้องน้อยกว่าค่าสูง");
    const ceiling = key === "heart_rate" ? 250 : key === "spo2" ? 100 : 80;
    if (Number(high) > ceiling) throw new Error("ขอบเขตเกินช่วงค่าที่ระบบรองรับ");
    result[key] = { low: Number(low), high: Number(high) };
  }
  return result;
}

export interface CareTaskHistoryItem {
  id?: number;
  task_id: number;
  plan_id?: number;
  patient_id?: string;
  previous_state: string;
  new_state: string;
  actor: string;
  skip_reason?: string | null;
  timestamp: number;
  created_at: number;
}

export interface CareTaskHistoryResponse {
  task_id: number;
  patient_id?: string;
  history: CareTaskHistoryItem[];
}

export const careTaskStateLabel = (state: string) => ({
  PENDING: 'รอดำเนินการ',
  ACKNOWLEDGED: 'รับทราบแล้ว',
  DONE: 'เสร็จสิ้น',
  COMPLETED: 'เสร็จสิ้น',
  SKIPPED: 'ข้ามงาน',
  CANCELLED: 'ยกเลิก',
}[state] ?? state);

export function formatTaskTransition(entry: {
  previous_state?: string;
  new_state: string;
  actor?: string;
  skip_reason?: string | null;
  timestamp?: number;
  created_at?: number;
}): string {
  const prev = entry.previous_state ? (careTaskStateLabel(entry.previous_state) || entry.previous_state) : 'เริ่มต้น';
  const curr = careTaskStateLabel(entry.new_state) || entry.new_state;
  const actor = entry.actor ? ` โดย ${entry.actor}` : '';
  const reason = entry.skip_reason ? ` (เหตุผล: ${entry.skip_reason})` : '';
  return `${prev} → ${curr}${actor}${reason}`;
}

