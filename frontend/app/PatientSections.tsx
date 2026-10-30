"use client";

import { useRef, useState } from 'react';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { bangkokDay, careTime, careVitals, careVitalLabels, type CareVital } from './careView';
import { careStateLabel, displayValue, sourceLabel } from './patientView';
import { usePatientResource } from './usePatientResource';
import type { MyCare, MyDaily, MyTrends, PatientRecord } from './patientTypes';
import s from './PatientPortal.module.css';
import VitalCharts from './VitalCharts';

export function ResourceStatus({ error, loading, retry }: { error: string; loading: boolean; retry: () => void }) {
  return error ? <div className={s.error} role="alert"><p>{error}</p><button disabled={loading} onClick={retry}>ลองโหลดใหม่</button></div>
    : <p role="status" className={s.empty}>กำลังอ่านข้อมูลของคุณ…</p>;
}

export function PatientSelfCheckGuide() {
  return (
    <div className={s.selfCheckGuide}>
      <strong>คำแนะนำการสังเกตอาการเบื้องต้นสำหรับผู้ป่วยและญาติ</strong>
      <div className={s.selfCheckGrid}>
        <div className={s.selfCheckCard}>
          <div className={s.selfCheckHead}>
            <span className={s.selfCheckIcon}>🚨</span>
            <b>อาการสำคัญที่ควรทักแชทแจ้งพยาบาลทันที</b>
          </div>
          <p>
            หากรู้สึกแน่นหน้าอก หายใจเหนื่อยหอบ วิงเวียนศีรษะ เหงื่อออกตัวเย็น หน้ามืด หรือมีอาการชาหรืออ่อนแรงครึ่งซีกกะทันหัน อย่ารอรอบตรวจเยี่ยมตามตาราง ให้กดปุ่ม <b>&ldquo;แชทกับแพทย์และทีมดูแล&rdquo;</b> หรือกดกริ่งเรียกพยาบาลข้างเตียงทันที
          </p>
        </div>
        <div className={s.selfCheckCard}>
          <div className={s.selfCheckHead}>
            <span className={s.selfCheckIcon}>📟</span>
            <b>วิธีวางตำแหน่งเซนเซอร์วัดออกซิเจนปลายนิ้วเพื่อลดสัญญาณรบกวน</b>
          </div>
          <p>
            สวมเซนเซอร์ที่ปลายนิ้วชี้หรือนิ้วกลางให้แนบกระชับพอดี ไม่บีบแน่นหรือหลวมจนเลื่อนหลุด หลีกเลี่ยงการทาสีเล็บ วางมือให้อยู่นิ่งบนเตียงระดับเดียวกับหัวใจ และไม่เกร็งนิ้วขณะเครื่องกำลังวัด เพื่อให้ระบบอ่านค่า SpO₂ ได้อย่างต่อเนื่องและลดการแจ้งเตือนสัญญาณหลุดรบกวน
          </p>
        </div>
      </div>
    </div>
  );
}

export function PatientTrends({ patientId }: { patientId: string }) {
  const [hours, setHours] = useState(1);
  return <>
    <div className={s.sectionHeading}><div><h2>แนวโน้มสัญญาณชีพย้อนหลัง</h2><p>ดูการเปลี่ยนแปลงจากข้อมูลที่บันทึก ไม่ใช่ค่าจากทะเบียนสมมติ</p></div></div>
    <div className={s.actions} role="group" aria-label="ช่วงเวลาย้อนหลัง">{[[1, '1 ชั่วโมง'], [6, '6 ชั่วโมง'], [24, '24 ชั่วโมง'], [168, '7 วัน']].map(([value, label]) => <button key={value} aria-pressed={hours === value} onClick={() => setHours(Number(value))}>{label}</button>)}</div>
    <TrendData key={`${patientId}-${hours}`} patientId={patientId} hours={hours} />
  </>;
}

function TrendData({ patientId, hours }: { patientId: string; hours: number }) {
  const { data, error, loading, refresh } = usePatientResource<MyTrends>(`/api/me/trends?hours=${hours}`, 60000);
  const [selected, setSelected] = useState('');
  const [metric, setMetric] = useState<CareVital>('heart_rate');
  if (!data || data.patient_id !== patientId) return <ResourceStatus error={error} loading={loading} retry={refresh} />;
  const sources = Object.keys(data.sources);
  const source = sources.includes(selected) ? selected : sources[0];
  const group = data.sources[source];
  return <>
    <div className={s.sectionHeading}><small>ข้อมูล {careTime(data.start)} ถึงก่อน {careTime(data.as_of)}<br />โหลดใหม่อัตโนมัติทุก 1 นาที</small><button onClick={refresh} disabled={loading}>โหลดแนวโน้มล่าสุด</button></div>
    {!group ? <section className={s.card}><div className={s.empty}><h3>ยังไม่มีข้อมูลในช่วงที่เลือก</h3><p>ลองเลือกช่วงเวลาที่ยาวขึ้น หรือรอระบบบันทึกข้อมูล ไม่มีข้อมูลไม่ได้แปลว่าปลอดภัย</p></div></section> : <>
      <section className={s.card}><div className={s.actions} role="group" aria-label="แหล่งข้อมูลย้อนหลัง">{sources.map((key) => <button key={key} aria-pressed={source === key} onClick={() => setSelected(key)}>{sourceLabel(key)}</button>)}</div>
        <p className={s.note}>แยกแต่ละแหล่งข้อมูล ไม่เฉลี่ยรวมกัน {source === 'BIDMC_REPLAY' && 'สัญญาณนี้เป็นการเล่นชุดข้อมูลย้อนหลัง ไม่ใช่การวัดผู้ป่วยจริงในทะเบียน'}</p>
        <VitalCharts points={group.points} title="ภาพรวมย้อนหลังครบทุกค่า" description={`สรุป ${group.snapshot_count} การบันทึกจาก ${sourceLabel(source)}`} />
        <div className={s.detailChartHeading}><div><h3>ดูรายละเอียดทีละค่า</h3><p>เลือกค่าเพื่ออ่านเวลาและตัวเลขบนกราฟขนาดใหญ่</p></div>
        <label>ตัวแปรที่ต้องการดู <select value={metric} onChange={(e) => setMetric(e.target.value as CareVital)}>{careVitals.map((key) => <option key={key} value={key}>{careVitalLabels[key]}</option>)}</select></label>
        </div>
        <div className={s.chart}><ResponsiveContainer width="100%" height="100%"><LineChart data={group.points} margin={{ top: 12, left: 0, right: 14, bottom: 0 }}><CartesianGrid stroke="#e4ebe6" strokeDasharray="3 4" vertical={false} /><XAxis dataKey="timestamp" type="number" domain={[data.start, data.as_of]} tickFormatter={(value) => new Date(value * 1000).toLocaleString('th-TH', hours === 168 ? { timeZone: 'Asia/Bangkok', day: 'numeric', month: 'short' } : { timeZone: 'Asia/Bangkok', hour: '2-digit', minute: '2-digit' })} minTickGap={40} axisLine={false} tickLine={false} /><YAxis width={48} domain={['auto', 'auto']} axisLine={false} tickLine={false} /><Tooltip labelFormatter={(value) => careTime(Number(value))} formatter={(value) => [displayValue(Number(value)), careVitalLabels[metric]]} /><Line dataKey={metric} name={careVitalLabels[metric]} stroke="#176e53" strokeWidth={3} dot={false} activeDot={{ r: 5 }} connectNulls={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></div>
        <small>แต่ละจุด = ค่าเฉลี่ยทุก {data.bucket_seconds / 60} นาที · เว้นว่างเมื่อไม่มีค่าในช่วงนั้น · ช่องว่างสั้นกว่าช่วงเฉลี่ยอาจไม่เห็นในกราฟ ดูความครอบคลุมประกอบ</small>
        <details className={s.learnMoreDrawer}>
          <summary className={s.learnMoreSummary}>
            <span>ℹ️ คำแนะนำการดูแลและข้อมูลเพิ่มเติม (Learn More)</span>
            <span className={s.learnMoreBadge}>คลิกเพื่ออ่านคำแนะนำ</span>
          </summary>
          <div className={s.learnMoreBody}>
            <div className={s.summaryGuide}>
              <strong>คำอธิบายสรุปสถิติอย่างง่าย (สำหรับผู้ป่วยและญาติ)</strong>
              <div className={s.summaryGuideGrid}>
                <div>
                  <b>ค่าเฉลี่ย:</b>
                  <p>ระดับสัญญาณชีพโดยรวมในช่วงเวลานี้ แสดงความสม่ำเสมอของร่างกาย</p>
                </div>
                <div>
                  <b>ค่าต่ำสุด - สูงสุด:</b>
                  <p>ช่วงที่ตัวเลขแกว่งขึ้นลงตามปกติในระหว่างวัน เช่น หลังขยับตัว หรือเปลี่ยนท่านอน</p>
                </div>
                <div>
                  <b>ความครอบคลุมของข้อมูล:</b>
                  <p>สัดส่วนเวลาที่อุปกรณ์บันทึกได้ครบถ้วน หากมีช่วงตัวเลขขาดหาย อาจเกิดจากเซนเซอร์ขยับหรือถอดพัก</p>
                </div>
              </div>
            </div>
            <PatientSelfCheckGuide />
          </div>
        </details>
        <div className={s.table}><table><caption>สถิติเฉพาะค่าที่ผ่านการตรวจคุณภาพ</caption><thead><tr><th>ตัวแปร</th><th>เฉลี่ย</th><th>ต่ำสุด</th><th>สูงสุด</th><th>จำนวนค่า</th></tr></thead><tbody>{careVitals.map((key) => { const m = group.statistics[key]; return <tr key={key}><th scope="row">{careVitalLabels[key]}</th><td>{displayValue(m?.mean)}</td><td>{displayValue(m?.min)}</td><td>{displayValue(m?.max)}</td><td>{m?.count ?? 0}</td></tr>; })}</tbody></table></div>
        <details onKeyDown={(e) => { if (e.key === 'Escape') (e.currentTarget as HTMLDetailsElement).open = false; }}><summary>ดูตัวเลขในกราฟแทนภาพ</summary><div className={s.table}><table><thead><tr><th>เริ่มช่วงเฉลี่ย (เวลาไทย)</th><th>{careVitalLabels[metric]}</th></tr></thead><tbody>{group.points.map((point) => <tr key={point.timestamp}><td>{careTime(point.timestamp)}</td><td>{displayValue(point[metric])}</td></tr>)}</tbody></table></div></details>
      </section>
      <div className={s.stats}><div className={s.stat}><span>จุดเวลาที่บันทึก</span><strong>{group.snapshot_count}</strong></div><div className={s.stat}><span>ความครอบคลุมโดยประมาณ</span><strong>{displayValue(group.coverage.estimated_percent)}%</strong></div><div className={s.stat}><span>ช่องว่างเกิน 15 วินาที</span><strong>{group.coverage.gap_count} ช่วง</strong></div></div>
      <p className={s.note}>ความครอบคลุมคิดจาก snapshot ทุก 5 วินาทีที่มีครบทั้ง 3 ค่า ไม่ใช่เวลาที่อุปกรณ์ออนไลน์จริง ช่วงที่ยังไม่ได้เปิด backend ก็นับเป็นข้อมูลที่ไม่มี</p>
    </>}
  </>;
}

export function PatientCare({ care, error, loading, refresh }: { care: MyCare | null; error: string; loading: boolean; refresh: () => void }) {
  const [filter, setFilter] = useState<'open' | 'closed'>('open');
  if (!care) return <ResourceStatus error={error} loading={loading} retry={refresh} />;
  const tasks = care.tasks.filter((task) => ['PENDING', 'ACKNOWLEDGED'].includes(task.state) === (filter === 'open'));
  return <>
    <div className={s.sectionHeading}><div><h2>แผนดูแลของฉัน</h2><p>ติดตามสถานะที่ทีมดูแลบันทึก โดยไม่แก้ไขแผนหรือรับงานแทนเจ้าหน้าที่</p><small>ข้อมูลเมื่อ {careTime(care.as_of)} · โหลดใหม่อัตโนมัติทุก 15 วินาที</small></div><button onClick={refresh} disabled={loading}>โหลดงานดูแลล่าสุด</button></div>
    <div className={s.stats}><div className={s.stat}><span>งานรอ/กำลังดำเนินการ</span><strong>{care.open_count}</strong></div><div className={s.stat}><span>งานบันทึกเสร็จวันนี้</span><strong>{care.done_today}</strong></div><div className={s.stat}><span>แผนที่เคยยืนยัน</span><strong>{care.plan_count}</strong></div></div>
    <details className={s.learnMoreDrawer}>
      <summary className={s.learnMoreSummary}>
        <span>ℹ️ คำแนะนำการดูแลและข้อมูลเพิ่มเติม (Learn More)</span>
        <span className={s.learnMoreBadge}>คลิกเพื่ออ่านคำแนะนำ</span>
      </summary>
      <div className={s.learnMoreBody}>
        <div className={s.careStateGuide}>
          <strong>ความหมายของสถานะงานดูแล (คลายความกังวลของผู้ป่วยและญาติ)</strong>
          <div className={s.careStateGrid}>
            <div>
              <span className={s.badge}>รอทีมดูแลรับงาน</span>
              <p>งานดูแลนี้บันทึกอยู่ในตารางเวลาประจำวันแล้ว พยาบาลหรือทีมดูแลจะเข้ามารับหน้าที่และดูแลตามรอบการตรวจเยี่ยมตามเวลาที่กำหนด</p>
            </div>
            <div>
              <span className={s.badge}>ทีมดูแลรับงานแล้ว</span>
              <p>มีเจ้าหน้าที่รับทราบงานนี้ในระบบแล้ว และกำลังเตรียมพร้อมหรือกำลังดำเนินการดูแลตามแผน</p>
            </div>
          </div>
        </div>
        <PatientSelfCheckGuide />
      </div>
    </details>
    <div className={s.split}><section className={s.card}><h3>ติดตามงานดูแล</h3><div className={s.actions} role="group" aria-label="สถานะงานดูแล"><button aria-pressed={filter === 'open'} onClick={() => setFilter('open')}>รอ / กำลังดำเนินการ</button><button aria-pressed={filter === 'closed'} onClick={() => setFilter('closed')}>ปิดงานวันนี้</button></div>
      {care.tasks_truncated && <p className={s.warning}>แสดง 50 งานล่าสุดโดยให้งานเปิดมาก่อน จากทั้งหมด {care.task_count} งานในขอบเขตนี้ จำนวนด้านบนคิดจากรายการทั้งหมด</p>}
      {!tasks.length ? <p className={s.empty}>{filter === 'open' ? 'ไม่พบงานเปิดในรายการที่แสดง' : 'ไม่พบงานที่ปิดวันนี้ในรายการที่แสดง'} ไม่ใช่การยืนยันว่าทำการดูแลครบแล้ว</p> : <ol className={s.timeline}>{tasks.map((task) => <li className={s.task} key={task.id}><div className={s.taskHeading}><strong>{task.title}</strong><span className={s.badge}>{careStateLabel(task.state)}</span></div><p>{task.instructions}</p><small>กำหนด {careTime(task.scheduled_at)}{task.overdue ? ' · เกินเวลาที่แผนกำหนด ยังไม่บันทึกว่าจบ' : ''}</small>{task.acknowledged_at && <small>รับงานเมื่อ {careTime(task.acknowledged_at)}</small>}{task.completed_at && <small>บันทึกปิดงานเมื่อ {careTime(task.completed_at)}</small>}</li>)}</ol>}
    </section><section className={s.card}><h3>แผนที่ทีมดูแลยืนยันแล้ว</h3>{care.plans_truncated && <p className={s.warning}>แสดงสูงสุด 50 แผน</p>}{!care.plans.length ? <p className={s.empty}>ยังไม่มีแผนที่ยืนยันแล้ว ฉบับร่างไม่แสดงฝั่งผู้ป่วย</p> : care.plans.map((plan) => <article className={s.task} key={plan.id}><div className={s.taskHeading}><strong>{plan.title}</strong><span className={s.badge}>{careStateLabel(plan.state)}</span></div><p>{plan.instructions}</p><small>{plan.interval_minutes ? `ทำซ้ำ ${plan.interval_minutes} นาทีหลังบันทึกจบรอบก่อน` : 'แผนครั้งเดียว'} · กำหนดโดยคน ไม่ใช่ AI สั่งรักษา</small>{plan.state === 'ACTIVE' && <small>เวลาที่แผนบันทึกไว้ {careTime(plan.next_due)}</small>}</article>)}</section></div>
    <p className={s.note}>หากข้อมูลไม่ตรงกับแผนที่ได้รับ แจ้งทีมดูแลผ่านแบบฟอร์มด้านล่าง สถานะงานแสดงสิ่งที่ทีมบันทึก ไม่ยืนยันว่าเจ้าหน้าที่กำลังอยู่กับผู้ป่วย</p>
  </>;
}

export function PatientReports({ patientId }: { patientId: string }) {
  const [today] = useState(() => bangkokDay());
  const [day, setDay] = useState(today);
  const offsetDay = (daysAgo: number) =>
    bangkokDay(new Date(new Date(`${today}T12:00:00+07:00`).getTime() - daysAgo * 86400000));
  const yesterday = offsetDay(1);
  const twoDaysAgo = offsetDay(2);
  return <><div className={s.sectionHeading}><div><h2>สรุปประจำวันของฉัน</h2><p>เลือกวันที่เพื่อทบทวนสิ่งที่ระบบบันทึกและดาวน์โหลดเก็บไว้</p></div><div className={s.actions}><button type="button" aria-pressed={day === today} onClick={() => setDay(today)}>วันนี้</button><button type="button" aria-pressed={day === yesterday} onClick={() => setDay(yesterday)}>เมื่อวาน</button><button type="button" aria-pressed={day === twoDaysAgo} onClick={() => setDay(twoDaysAgo)}>2 วันก่อน</button><label>วันที่รายงาน <input type="date" min="2000-01-01" max={today} value={day} onChange={(e) => setDay(e.target.value)} /></label></div></div>
    <details className={s.learnMoreDrawer}>
      <summary className={s.learnMoreSummary}>
        <span>ℹ️ คำแนะนำการดูแลและข้อมูลเพิ่มเติม (Learn More)</span>
        <span className={s.learnMoreBadge}>คลิกเพื่ออ่านคำแนะนำ</span>
      </summary>
      <div className={s.learnMoreBody}>
        <div className={s.summaryGuide}>
          <strong>คำแนะนำการใช้รายงานสรุปประจำวัน (สำหรับผู้ป่วยและญาติ)</strong>
          <p>คุณและครอบครัวสามารถใช้หน้านี้อ่านทบทวนภาพรวมการดูแลในแต่ละวัน และกดปุ่ม <b>ดาวน์โหลดสรุปรายวัน · Text</b> เพื่อบันทึกไฟล์เก็บไว้ในโทรศัพท์หรือคอมพิวเตอร์ หรือเปิดให้แพทย์และทีมดูแลดูประกอบการพูดคุยซักถามในรอบตรวจเยี่ยมถัดไปได้สะดวก</p>
        </div>
      </div>
    </details>
    {day ? <ReportData key={`${patientId}-${day}`} patientId={patientId} day={day} /> : <p className={s.empty}>กรุณาเลือกวันที่รายงาน</p>}
  </>;
}

function ReportData({ patientId, day }: { patientId: string; day: string }) {
  const { data, error, loading, refresh } = usePatientResource<MyDaily>(`/api/me/daily?day=${day}`);
  const modalRef = useRef<HTMLDialogElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const openModal = () => {
    const dialog = modalRef.current;
    if (!dialog) return;
    if (!dialog.open) {
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else dialog.setAttribute('open', '');
    }
  };
  const closeModal = () => {
    const dialog = modalRef.current;
    if (dialog) {
      if (dialog.open && typeof dialog.close === 'function') dialog.close();
      dialog.removeAttribute('open');
    }
    triggerRef.current?.focus();
  };
  if (!data || data.patient_id !== patientId) return <ResourceStatus error={error} loading={loading} retry={refresh} />;
  return <>
    <section className={s.card}><span className={s.badge}>สรุปอัตโนมัติ · {data.partial_day ? 'ยังไม่ครบวัน' : 'สิ้นสุดวันแล้ว'}</span><p>ข้อมูลถึงก่อน {careTime(data.as_of)}</p><small>สร้างเมื่อ {careTime(data.generated_at)} · เวลาไทย<br />backend บุคลากรเตรียมร่างทุกประมาณ 5 นาทีเมื่อทำงาน ข้อมูลนี้ไม่ใช่ค่าล่าสุดทุกวินาที</small><div className={s.actions}><button type="button" disabled={loading} onClick={refresh}>โหลดสรุปที่ระบบเตรียมล่าสุด</button><button type="button" ref={triggerRef} onClick={openModal}>เปิดหน้าต่างอ่านสรุปแบบขยาย (Modal Preview)</button><a className={`${s.link} ${s.primary}`} href={`/api/me/daily/report?day=${day}&digest=${data.digest}`}>ดาวน์โหลดสรุปรายวัน · Text</a></div></section>
    <div className={s.stats}><div className={s.stat}><span>งานเสร็จ / ค้างถึงกำหนด</span><strong>{data.care.done_in_period} / {data.care.open_due_as_of_count}</strong></div><div className={s.stat}><span>รายการให้ทีมตรวจใหม่ / ยังไม่ปิด</span><strong>{data.alerts.new_count} / {data.alerts.open_as_of_count}</strong></div><div className={s.stat}><span>ความครอบคลุมโดยประมาณ</span><strong>{displayValue(data.recording.estimated_percent)}%</strong></div></div>
    <section className={s.card}><h3>บันทึกสรุปสำหรับอ่านและส่งต่อ</h3><pre className={s.narrative}>{data.text}</pre></section>
    <p className={s.note}>สรุปด้วยสถิติและผล ML ที่มีหลักฐาน ไม่ได้ให้ Gemini แต่งข้อมูล ไม่แสดงบันทึกภายในของทีมดูแล หากร่างเปลี่ยนก่อนดาวน์โหลด ให้โหลดสรุปล่าสุดใหม่</p>
    <dialog
      ref={modalRef}
      className={s.modalDialog}
      aria-labelledby="modal-report-heading"
      onClick={(e) => { if (e.target === modalRef.current) closeModal(); }}
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.stopPropagation();
          closeModal();
        }
      }}
    >
      <div className={s.modalHeader}>
        <h3 id="modal-report-heading">บันทึกสรุปประจำวัน · {day}</h3>
        <button
          type="button"
          className={s.modalCloseBtn}
          aria-label="ปิดหน้าต่างสรุป (Esc)"
          onClick={closeModal}
        >
          ×
        </button>
      </div>
      <div className={s.modalBody}>
        <pre className={s.narrative}>{data.text}</pre>
        <div className={s.actions}>
          <button
            type="button"
            onClick={closeModal}
          >
            ปิดหน้าต่าง
          </button>
          <a className={`${s.link} ${s.primary}`} href={`/api/me/daily/report?day=${day}&digest=${data.digest}`}>
            ดาวน์โหลดสรุปรายวัน · Text
          </a>
        </div>
      </div>
    </dialog>
  </>;
}

export function PatientProfile({ patient, care, error, loading, refresh }: { patient: PatientRecord; care: MyCare | null; error: string; loading: boolean; refresh: () => void }) {
  const profile = care?.profile;
  return <>
    <div className={s.sectionHeading}><div><h2>ข้อมูลของฉัน</h2><p>แยกข้อมูลที่ทีมดูแลยืนยันออกจากทะเบียนสาธิตอย่างชัดเจน</p></div><button onClick={refresh} disabled={loading}>โหลดข้อมูลการดูแลล่าสุด</button></div>
    <section className={s.card}><h3>ข้อมูลการดูแลที่ยืนยันแล้ว</h3>{!care ? <ResourceStatus error={error} loading={loading} retry={refresh} /> : !profile ? <p className={s.empty}>ยังไม่มีโปรไฟล์ที่ยืนยันแล้ว หรือทีมดูแลพักการใช้งานไว้ ระบบไม่เอาข้อมูลสมมติมาเติมแทน</p> : <><p><span className={s.badge}>ฉบับ {profile.version}</span></p><small>ยืนยันเมื่อ {careTime(profile.reviewed_at)} · บัญชีบุคลากรสาธิต ไม่ใช่ลายเซ็นแพทย์</small><dl className={s.fieldGrid}>{([['โรค/ภาวะที่บันทึก', profile.conditions], ['รายการยาที่มีบันทึก', profile.medications], ['ประวัติแพ้ที่บันทึก', profile.allergies], ['ข้อจำกัดและสิ่งที่ต้องระวัง', profile.limitations]]).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || 'ยังไม่ได้บันทึก ไม่ได้แปลว่าไม่มี'}</dd></div>)}</dl></>}</section>
    <p className={s.warning}>รายการยาข้างต้นเป็นข้อมูลที่บันทึก ไม่ใช่ใบสั่งยาหรือคำแนะนำให้เริ่ม หยุด หรือปรับยา</p>
    <details className={s.learnMoreDrawer}>
      <summary className={s.learnMoreSummary}>
        <span>ℹ️ คำแนะนำการดูแลและข้อมูลเพิ่มเติม (Learn More)</span>
        <span className={s.learnMoreBadge}>คลิกเพื่ออ่านคำแนะนำ</span>
      </summary>
      <div className={s.learnMoreBody}>
        <div className={s.summaryGuide}>
          <strong>ต้องการแจ้งแก้ไขประวัติแพ้ยาหรือรายการยา?</strong>
          <p>หากมีประวัติแพ้ยาหรือรายการยาที่เปลี่ยนแปลง สามารถแจ้งทีมดูแลผ่านหมวด &ldquo;แผนดูแล / แจ้งเรื่อง&rdquo; เพื่อให้บุคลากรตรวจสอบและอัปเดตโปรไฟล์ฉบับถัดไปได้ (ผู้ป่วยไม่ต้องแก้เองเพื่อความปลอดภัย)</p>
        </div>
      </div>
    </details>
    <section className={s.card}><h3>ทะเบียนผู้ป่วยสาธิต</h3><p className={s.note}>ข้อมูลส่วนนี้สร้างขึ้นเพื่อสาธิต ไม่ใช่เวชระเบียนจริง และไม่ได้เป็นโรคกำกับของสัญญาณ BIDMC</p><dl className={s.fieldGrid}>{[
      ['รหัสผู้ป่วย', patient.patient_id], ['ชื่อในทะเบียน', patient.profile.name], ['ตำแหน่ง', `โซน ${patient.profile.zone} · ห้อง ${patient.profile.room_number} · เตียง ${patient.profile.bed_number}`], ['อายุสมมติ', `${patient.profile.age} ปี`], ['กรุ๊ปเลือดสมมติ', patient.profile.blood_group], ['โรคในทะเบียนสมมติ', patient.profile.condition], ['การเคลื่อนไหวในทะเบียน', patient.profile.mobility], ['รูปแบบการดูแล', patient.profile.care_setting ?? 'ยังไม่ได้บันทึก'], ['แพทย์ที่ได้รับมอบหมาย', patient.profile.doctor ?? 'ทีมดูแล Smart Ward'], ['เป้าหมายการดูแล', patient.profile.care_goal ?? 'ยังไม่ได้บันทึก'], ['ผู้ติดต่อฉุกเฉิน', patient.profile.emergency_contact ?? 'ยังไม่ได้บันทึก'],
    ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl><small>ไม่แสดงน้ำตาล ไขมัน การนอน หรือ ECG ที่สุ่มขึ้นเป็นผลตรวจล่าสุด</small></section>
  </>;
}
