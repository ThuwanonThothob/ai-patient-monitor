"use client";

import { useEffect, useState } from 'react';
import type { MyTrends } from './patientTypes';
import { vitalKeys, vitalMeta } from './vitalView';
import VitalCharts from './VitalCharts';
import styles from './Ward.module.css';

const sourceNames: Record<string, string> = {
  BIDMC_REPLAY: 'BIDMC · ข้อมูลย้อนหลังสาธิต',
  MQTT: 'อุปกรณ์ MQTT',
  UNKNOWN: 'ไม่ทราบแหล่งข้อมูล',
};

function fmtStat(val?: number | null) {
  if (val === null || val === undefined || !Number.isFinite(val)) return '—';
  return Number.isInteger(val) ? String(val) : val.toFixed(1);
}

export default function StaffTrendPanel({ patientId }: { patientId: string }) {
  const [hours, setHours] = useState(1);
  const [data, setData] = useState<MyTrends | null>(null);
  const [source, setSource] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const abort = new AbortController();
    const start = window.setTimeout(() => {
      setLoading(true); setError(''); setData(null);
      fetch(`/api/patient/${patientId}/trends?hours=${hours}`, { signal: abort.signal, cache: 'no-store' })
        .then(async (response) => { if (!response.ok) throw new Error(); return response.json() as Promise<MyTrends>; })
        .then((next) => { setData(next); const keys = Object.keys(next.sources); setSource((current) => keys.includes(current) ? current : keys[0] ?? ''); })
        .catch(() => { if (!abort.signal.aborted) setError('โหลดกราฟย้อนหลังไม่สำเร็จ กรุณาลองเปิดข้อมูลผู้ป่วยใหม่'); })
        .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    }, 0);
    return () => { window.clearTimeout(start); abort.abort(); };
  }, [hours, patientId]);
  const group = data?.sources[source];
  return <section className={styles.panel} aria-label="กราฟสัญญาณชีพย้อนหลัง">
    <div className={styles.titleRow}><div><span className={styles.eyebrow}>HISTORICAL VITAL REVIEW</span><h3 className={styles.h2}>กราฟย้อนหลังเพื่อทบทวน</h3><p className={styles.muted}>แยก HR, SpO₂ และ RR คนละหน่วย · ไม่เติมค่าในช่วงข้อมูลขาด</p></div><div className={styles.filters} role="group" aria-label="ช่วงเวลากราฟย้อนหลัง">{[[1, '1 ชม.'], [6, '6 ชม.'], [24, '24 ชม.'], [168, '7 วัน']].map(([value, label]) => <button className={`${styles.choice} ${hours === value ? styles.choiceActive : ''}`} aria-pressed={hours === value} key={value} onClick={() => setHours(Number(value))}>{label}</button>)}</div></div>
    {data && Object.keys(data.sources).length > 1 && <div className={styles.filters} role="group" aria-label="แหล่งข้อมูลกราฟ">{Object.keys(data.sources).map((key) => <button className={`${styles.choice} ${source === key ? styles.choiceActive : ''}`} aria-pressed={source === key} key={key} onClick={() => setSource(key)}>{sourceNames[key] ?? key}</button>)}</div>}
    {loading ? <p className={styles.empty} role="status">กำลังเตรียมกราฟย้อนหลัง…</p> : error ? <p className={styles.error} role="alert">{error}</p> : !group ? <p className={styles.empty}>ยังไม่มีข้อมูลในช่วงเวลานี้ ลองเลือกช่วงที่ยาวขึ้น ข้อมูลว่างไม่ได้แปลว่าปลอดภัย</p> : <>
      <div className={styles.historyStats} style={{ marginTop: 4, marginBottom: 14 }}>
        <span>ความครอบคลุมโดยประมาณ <b>{group.coverage.estimated_percent}%</b></span>
        <span>ช่วงขาดเกิน 15 วินาที <b>{group.coverage.gap_count}</b></span>
        <span>ช่วงขาดนานที่สุด <b>{Math.round(group.coverage.longest_gap_seconds / 60)} นาที</b></span>
        <span>บันทึกผ่านเกณฑ์ <b>{group.snapshot_count} จุด</b></span>
      </div>
      <VitalCharts points={group.points} title={`${sourceNames[source] ?? source} · ย้อนหลัง ${hours === 168 ? '7 วัน' : `${hours} ชั่วโมง`}`} description={`บันทึก ${group.snapshot_count} จุด · ค่าในกราฟเป็นค่าเฉลี่ยตามช่วงเวลา`} />
      <details className={styles.learnMoreDrawer}>
        <summary className={styles.learnMoreSummary}>
          <span>📊 ตารางสรุปค่าสถิติย้อนหลังรายตัวแปรและข้อจำกัดของข้อมูล (Learn More)</span>
          <span className={styles.learnMoreBadge}>สถิติเชิงลึก</span>
        </summary>
        <div className={styles.learnMoreBody}>
          <div className={styles.tableWrap} style={{ marginTop: 0 }}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>สัญญาณชีพ</th>
                  <th>ค่าเฉลี่ย (Mean)</th>
                  <th>ต่ำสุด (Min)</th>
                  <th>สูงสุด (Max)</th>
                  <th>ค่าแรก → ค่าล่าสุด</th>
                  <th>จำนวนจุด</th>
                </tr>
              </thead>
              <tbody>
                {vitalKeys.map((key) => {
                  const st = group.statistics?.[key];
                  const meta = vitalMeta[key];
                  return (
                    <tr key={key}>
                      <td><b>{meta.short}</b> · {meta.label} ({meta.unit})</td>
                      <td>{fmtStat(st?.mean)}</td>
                      <td>{fmtStat(st?.min)}</td>
                      <td>{fmtStat(st?.max)}</td>
                      <td>{st ? `${fmtStat(st.first)} → ${fmtStat(st.last)}` : '—'}</td>
                      <td>{st?.count ?? 0}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className={styles.disclaimer} style={{ marginBottom: 0 }}>
            ความครอบคลุมเป็นค่าประมาณจาก snapshot ไม่ใช่เวลาที่อุปกรณ์ออนไลน์จริง และกราฟ BIDMC เป็นข้อมูลเล่นย้อนหลัง ไม่ใช่การวัดผู้ป่วยในทะเบียน
          </p>
        </div>
      </details>
    </>}
  </section>;
}
