export const vitalKeys = ['heart_rate', 'spo2', 'respiratory_rate'] as const;
export type VitalKey = typeof vitalKeys[number];
export type VitalPoint = {
  timestamp?: number;
  time?: string;
  heart_rate?: number | null;
  spo2?: number | null;
  respiratory_rate?: number | null;
};

export const vitalMeta: Record<VitalKey, { short: string; label: string; unit: string; color: string; soft: string }> = {
  heart_rate: { short: 'HR', label: 'ชีพจร', unit: 'bpm', color: '#b63f51', soft: '#fff1f3' },
  spo2: { short: 'SpO₂', label: 'ออกซิเจนในเลือด', unit: '%', color: '#17745a', soft: '#edf8f3' },
  respiratory_rate: { short: 'RR', label: 'อัตราการหายใจ', unit: 'ครั้ง/นาที', color: '#2f69a1', soft: '#eef5fb' },
};

export function finiteVital(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function vitalSummary(points: VitalPoint[], key: VitalKey) {
  const values = points.map((point) => finiteVital(point[key])).filter((value): value is number => value !== null);
  return {
    count: values.length,
    latest: values.length ? values[values.length - 1] : null,
    min: values.length ? Math.min(...values) : null,
    max: values.length ? Math.max(...values) : null,
  };
}

export function vitalTime(point: VitalPoint, index: number): string {
  if (typeof point.timestamp === 'number' && Number.isFinite(point.timestamp)) {
    return new Date(point.timestamp * 1000).toLocaleTimeString('th-TH', { timeZone: 'Asia/Bangkok', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  }
  return point.time || `จุดที่ ${index + 1}`;
}
