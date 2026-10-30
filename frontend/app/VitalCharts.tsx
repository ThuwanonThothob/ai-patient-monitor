"use client";

import { useId, useState } from 'react';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { finiteVital, vitalKeys, vitalMeta, vitalSummary, vitalTime, type VitalKey, type VitalPoint } from './vitalView';
import s from './Ward.module.css';

function valueLabel(value: number | null) {
  return value === null ? '—' : Number.isInteger(value) ? String(value) : value.toFixed(1);
}

const normalRangeHint: Record<VitalKey, string> = {
  heart_rate: 'เกณฑ์ปกติ 51–90 bpm',
  spo2: 'เกณฑ์ปกติ ≥96%',
  respiratory_rate: 'เกณฑ์ปกติ 12–20 ครั้ง/นาที',
};

function computeMean(points: VitalPoint[], key: VitalKey): number | null {
  const valid = points.map((p) => finiteVital(p[key])).filter((v): v is number => v !== null);
  if (!valid.length) return null;
  const sum = valid.reduce((acc, v) => acc + v, 0);
  return Number((sum / valid.length).toFixed(1));
}

export default function VitalCharts({ points, compact = false, title = 'แนวโน้มสัญญาณชีพล่าสุด', description }: {
  points?: VitalPoint[];
  compact?: boolean;
  title?: string;
  description?: string;
}) {
  const chartId = useId().replace(/:/g, '');
  const [table, setTable] = useState(false);
  const timed = Boolean(points?.length && points.every(point => typeof point.timestamp === 'number' && Number.isFinite(point.timestamp)));
  const safe = (points ?? []).map((point, index) => ({
    ...point,
    heart_rate: finiteVital(point.heart_rate),
    spo2: finiteVital(point.spo2),
    respiratory_rate: finiteVital(point.respiratory_rate),
    chartTime: vitalTime(point, index),
    chartIndex: index,
    chartPosition: timed ? point.timestamp : index,
  }));
  if (!safe.some((point) => vitalKeys.some((key) => point[key] !== null))) {
    return compact ? <div className="vital-chart-empty">ยังไม่มีข้อมูลแนวโน้ม</div> : <section className="vital-chart-section"><div className="vital-chart-heading"><div><h3>{title}</h3>{description && <p>{description}</p>}</div></div><div className="vital-chart-empty">ยังไม่มีค่าที่ผ่านการตรวจคุณภาพสำหรับสร้างกราฟ</div></section>;
  }
  return <section className={`vital-chart-section ${compact ? 'is-compact' : ''}`} aria-label={title}>
    {!compact && <div className="vital-chart-heading"><div><small className="chart-eyebrow">VITAL TRENDS · 3 สัญญาณชีพแยกหน่วย</small><h3>{title}</h3>{description && <p>{description}</p>}</div><div className="chart-actions"><button type="button" aria-pressed={table} onClick={() => setTable(!table)}>{table ? 'ซ่อนตัวเลข' : 'ดูตาราง'}</button></div></div>}
    <div className="vital-chart-grid">
      {vitalKeys.map((key) => {
        const meta = vitalMeta[key], summary = vitalSummary(safe, key), mean = computeMean(safe, key);
        const domain: [number, number] = summary.min === null || summary.max === null ? [0, 1]
          : key === 'spo2' ? [Math.max(0, summary.min - 2), 100]
            : [Math.max(0, Math.floor(summary.min - 2)), Math.ceil(summary.max + 2)];
        return <article className="vital-chart-card" key={key} style={{ '--vital-color': meta.color, '--vital-soft': meta.soft } as React.CSSProperties}>
          <header>
            <div>
              <span className="vital-short">{meta.short}</span>
              <b>{meta.label}</b>
              {!compact && <small style={{ fontSize: 10.5, color: '#5c7268' }}>{normalRangeHint[key]}</small>}
            </div>
            <strong><span className="chart-latest-label">ล่าสุดที่มีค่า</span>{valueLabel(summary.latest)} <small>{meta.unit}</small></strong>
          </header>
          {!compact && <div className="vital-range"><span>ต่ำสุด <b>{valueLabel(summary.min)}</b></span><span>เฉลี่ย <b>{valueLabel(mean)}</b></span><span>สูงสุด <b>{valueLabel(summary.max)}</b></span><span>{summary.count} จุด</span></div>}
          <div className="vital-chart-canvas">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={safe} margin={compact ? { top: 3, right: 2, bottom: 2, left: 2 } : { top: 10, right: 12, bottom: 4, left: -8 }}>
                <defs><linearGradient id={`${chartId}-${key}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={meta.color} stopOpacity={0.2} /><stop offset="100%" stopColor={meta.color} stopOpacity={0.01} /></linearGradient></defs>
                {!compact && <CartesianGrid stroke="#e4ebe6" strokeDasharray="3 4" vertical={false} />}
                <XAxis dataKey="chartPosition" type="number" domain={['dataMin', 'dataMax']} hide={compact} tickFormatter={(value) => timed ? new Date(Number(value) * 1000).toLocaleTimeString('th-TH', { timeZone: 'Asia/Bangkok', hour: '2-digit', minute: '2-digit' }) : safe[Math.round(Number(value))]?.chartTime ?? ''} minTickGap={42} tick={{ fontSize: 11, fill: '#66776d' }} axisLine={false} tickLine={false} />
                <YAxis hide={compact} width={42} domain={domain} tick={{ fontSize: 11, fill: '#66776d' }} axisLine={false} tickLine={false} allowDataOverflow={false} />
                <Tooltip labelFormatter={(_, payload) => timed && payload?.[0]?.payload?.timestamp ? new Date(payload[0].payload.timestamp * 1000).toLocaleString('th-TH', { timeZone: 'Asia/Bangkok' }) : payload?.[0]?.payload?.chartTime ?? ''} formatter={(value) => [valueLabel(finiteVital(value)), `${meta.label} (${meta.unit})`]} contentStyle={{ borderRadius: 14, borderColor: '#d8e2dc', fontSize: 12, boxShadow: '0 8px 24px #163b2615' }} />
                <Area type="linear" dataKey={key} name={meta.label} stroke={meta.color} fill={`url(#${chartId}-${key})`} strokeWidth={compact ? 2 : 2.5} dot={safe.length === 1 ? { r: 3 } : false} activeDot={{ r: 5, stroke: '#fff', strokeWidth: 2 }} connectNulls={false} isAnimationActive={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </article>;
      })}
    </div>
    {!compact && table && <div className="chart-data-table"><table><caption>ค่าที่แสดงในกราฟ · เวลาไทย</caption><thead><tr><th>เวลา</th>{vitalKeys.map(key => <th key={key}>{vitalMeta[key].label} ({vitalMeta[key].unit})</th>)}</tr></thead><tbody>{safe.map((point, index) => <tr key={index}><td>{timed ? new Date(point.timestamp! * 1000).toLocaleString('th-TH', { timeZone: 'Asia/Bangkok' }) : point.chartTime}</td>{vitalKeys.map(key => <td key={key}>{valueLabel(point[key])}</td>)}</tr>)}</tbody></table></div>}
    {!compact && (
      <details className={s.learnMoreDrawer}>
        <summary className={s.learnMoreSummary}>
          <span>📈 หลักการแสดงผลกราฟแนวโน้มและความปลอดภัยของข้อมูล (Learn More)</span>
          <span className={s.learnMoreBadge}>วิธีอ่านกราฟ</span>
        </summary>
        <div className={s.learnMoreBody}>
          <p className="vital-chart-footnote" style={{ marginTop: 0 }}>
            สเกลแต่ละกราฟต่างกัน · ตัวเลขใหญ่คือค่าล่าสุดที่มีในช่วงนี้ ไม่จำเป็นต้องเป็นค่าปัจจุบัน · ไม่เติมค่าที่หายไป (connectNulls=false) · ผู้ช่วยอ่านย้อนหลัง 24 ชั่วโมงแยกจากช่วงกราฟที่เลือก
          </p>
        </div>
      </details>
    )}
  </section>;
}
