"use client";

import { useEffect, useState } from 'react';
import { LatestVitals, PatientAnalysis } from './MonitorPanel';
import { isFreshReading } from './monitorView';
import Icon from './Icon';
import AgentAssistant from './AgentAssistant';
import CareMessages from './CareMessages';
import CareChat from './CareChat';
import { careTime } from './careView';
import { patientSections, safeAnalysis, sourceLabel, type PatientSection } from './patientView';
import { usePatientResource } from './usePatientResource';
import { PatientCare, PatientProfile, PatientReports, PatientTrends, ResourceStatus } from './PatientSections';
import type { MyCare, PatientRecord } from './patientTypes';
import VitalCharts from './VitalCharts';
import s from './PatientPortal.module.css';

export default function PatientPortal() {
  const live = usePatientResource<PatientRecord>('/api/me', 3000, true);
  return <main id="main-content" tabIndex={-1} className={s.page}>
    {live.data && live.error && <div className={s.error} role="alert">{live.error} · ข้อมูลด้านล่างเป็นข้อมูลที่โหลดสำเร็จครั้งล่าสุด <button onClick={live.refresh}>ลองใหม่</button></div>}
    {!live.data ? <><h1>การดูแลของฉัน</h1><ResourceStatus error={live.error} loading={live.loading} retry={live.refresh} /></>
      : <PatientWorkspace key={live.data.patient_id} patient={live.data} refresh={live.refresh} loading={live.loading} />}
    <footer className={s.footer}>ข้อมูลเพื่อสาธิตและวิจัยเท่านั้น · AI ช่วยจัดข้อมูล ไม่ใช้แทนการประเมินของบุคลากร · หน้านี้ไม่ใช่ช่องทางฉุกเฉินและไม่ได้ติดต่อทีมดูแลหรือเรียกรถพยาบาลอัตโนมัติ</footer>
  </main>;
}

function PatientWorkspace({ patient, refresh, loading }: { patient: PatientRecord; refresh: () => void; loading: boolean }) {
  const [active, setActive] = useState<PatientSection>(() => typeof window !== 'undefined'
    && new URLSearchParams(window.location.search).get('section') === 'chat' ? 'chat' : 'overview');
  const [now, setNow] = useState(() => Date.now() / 1000);
  const careResource = usePatientResource<MyCare>('/api/me/care', 15000);
  const chatStatus = usePatientResource<{ unread: number; latest: { sender_display_name: string } | null; care_team: { display_name: string } }>('/api/me/chat/status', 5000, true);
  const care = careResource.data?.patient_id === patient.patient_id ? careResource.data : null;
  useEffect(() => { const timer = setInterval(() => setNow(Date.now() / 1000), 1000); return () => clearInterval(timer); }, []);
  const fresh = isFreshReading(patient.monitor, now);
  const analysis = safeAnalysis(patient.monitor, now, fresh);
  const attention = fresh && ['WARNING', 'CRITICAL'].includes(patient.monitor.status);
  const open = care?.tasks.filter((task) => ['PENDING', 'ACKNOWLEDGED'].includes(task.state)) ?? [];
  const careProps = { care, error: careResource.error, loading: careResource.loading, refresh: careResource.refresh };
  return <>
    <AgentAssistant key={active} section={active} patientId={patient.patient_id} />
    <header className={s.hero}><div className={s.identity}><div className={s.avatar}><Icon name="patients" size={28} /></div><div><span className={s.eyebrow}>MY CARE · {patient.patient_id}</span><h1>การดูแลของฉัน</h1><p>โซน {patient.profile.zone} · ห้อง {patient.profile.room_number}</p></div></div><div className={s.heroActions}><button type="button" className={s.primary} onClick={() => setActive('chat')}><Icon name="chat" size={18} />แชทกับแพทย์และทีมดูแล{Boolean(chatStatus.data?.unread) && <span className={s.unread} aria-label={`ข้อความใหม่ ${chatStatus.data?.unread}`}>{chatStatus.data?.unread}</span>}</button><span className={s.badge}>{fresh ? 'ได้รับข้อมูลการวัดล่าสุด' : 'รอข้อมูลการวัดใหม่'}</span></div></header>
    <nav className={s.nav} aria-label="หมวดข้อมูลผู้ป่วย">{patientSections.map((section) => <button key={section.key} aria-pressed={active === section.key} onClick={() => setActive(section.key)}><Icon name={section.icon} size={19} />{section.title}{section.key === 'chat' && Boolean(chatStatus.data?.unread) && <span className={s.unread} aria-label={`ข้อความใหม่ ${chatStatus.data?.unread}`}>{chatStatus.data?.unread}</span>}</button>)}</nav>
    {active === 'overview' && <>
      <div className={s.sectionHeading}><div><h2>วันนี้มีอะไรให้ติดตาม</h2><p>ค่าสัญญาณชีพปัจจุบัน งานดูแลประจำวัน และแนวโน้มล่าสุดในหน้าเดียว</p></div><button onClick={refresh} disabled={loading}>↻ โหลดค่าล่าสุด</button></div>
      {!fresh && <p className={s.warning} role="status">ยังไม่มีข้อมูลใหม่เพียงพอ จึงไม่แสดงค่าเก่าเป็นค่าปัจจุบัน หากมีอาการผิดปกติ ให้ติดต่อบุคลากรโดยตรง ไม่ต้องรอระบบ</p>}
      {attention && <p className={s.warning} role="status">มีค่าวัดที่ระบบเสนอให้ทีมดูแลตรวจสอบ ผลนี้ไม่ใช่การวินิจฉัยและไม่ได้ยืนยันว่ามีคนรับเรื่องแล้ว</p>}
      <LatestVitals state={patient.monitor} />
      <div className={s.actions}>
        <button className={s.primary} onClick={() => setActive('chat')}><Icon name="chat" size={18} />แชทข้อความกับแพทย์และทีมดูแล (Messenger)</button>
        <button onClick={() => setActive('care')}><Icon name="care" size={18} />แจ้งเรื่อง / ติดตามงานดูแล{open.length ? ` (${open.length})` : ''}</button>
        <button onClick={() => setActive('trends')}><Icon name="evidence" size={18} />ดูกราฟย้อนหลัง</button>
        <span className={s.badge}>ข้อมูลการวัด: {fresh ? 'เชื่อมต่ออยู่' : 'ขาดช่วง โปรดตรวจอุปกรณ์และเครือข่าย'}</span>
      </div>
      <div className={s.split}>
        <section className={s.card}>
          <div className={s.eyebrow}>CARE SCHEDULE · แผนดูแลประจำวัน</div>
          <h3>งานดูแลที่กำลังติดตาม</h3>
          {!care ? <ResourceStatus error={careResource.error} loading={careResource.loading} retry={careResource.refresh} /> : <>
            <p>งานเปิด <b>{care.open_count}</b> รายการ · บันทึกเสร็จวันนี้ <b>{care.done_today}</b> รายการ</p>
            {open.length ? <ol className={s.timeline}>{open.slice(0, 3).map((task) => <li key={task.id} className={s.task}><strong>{task.title}</strong><small>กำหนด {careTime(task.scheduled_at)} · {task.state === 'ACKNOWLEDGED' ? 'ทีมดูแลรับงานแล้ว' : 'รอทีมดูแลรับงาน'}</small></li>)}</ol> : <p className={s.empty}>ไม่พบงานที่ยังเปิด ไม่ได้แปลว่าการดูแลทุกอย่างเสร็จแล้ว</p>}
            <button onClick={() => setActive('care')}>ดูงานและแผนทั้งหมด <Icon name="arrow" size={17} /></button>
          </>}
        </section>
        <section className={s.card}>
          <div className={s.eyebrow}>AI ASSISTANT · LOCAL ANALYSIS</div>
          <h3>AI กำลังช่วยอะไร</h3>
          <p>{analysis ? analysis.is_anomaly ? 'พบรูปแบบสัญญาณต่างจากชุดฝึก จึงเสนอให้บุคลากรตรวจสอบการวัดและบริบทเพิ่มเติม' : 'โมเดลประเมินข้อมูลรอบล่าสุดแล้ว ไม่พบรูปแบบต่างจากชุดฝึกในรอบนี้ ไม่ได้ยืนยันว่าปลอดภัยหรือไม่มีโรค' : 'กำลังรอข้อมูลต่อเนื่องและผลประเมินที่ใหม่พอ ไม่เดาค่าแทนข้อมูลที่ไม่มี'}</p>
          {analysis?.evaluated_at && <small>ประเมินเมื่อ {careTime(analysis.evaluated_at)}</small>}
          <details className={s.inlineDetails}><summary>ดูค่าคาดการณ์และที่มาของ AI</summary><PatientAnalysis state={patient.monitor} /></details>
          <small>ใช้โมเดลสัญญาณชีพเดิม ไม่ใช่การวินิจฉัยโรคประจำตัวหรือพยาบาลที่ตัดสินใจแทนคน</small>
        </section>
      </div>
      <VitalCharts points={patient.monitor.history} title="แนวโน้มล่าสุดจากอุปกรณ์" description="ดูการเปลี่ยนแปลงของทั้ง 3 ค่าก่อนเปิดประวัติระยะยาว" />
      <details className={s.learnMoreDrawer}>
        <summary className={s.learnMoreSummary}>
          <span>ℹ️ คำอธิบายค่าสัญญาณชีพเบื้องต้น ข้อมูลระบบ และทางลัดเพิ่มเติม (Learn More)</span>
          <span className={s.learnMoreBadge}>คลิกเพื่อดูรายละเอียด</span>
        </summary>
        <div className={s.learnMoreBody}>
          <p className={s.note}>{sourceLabel(patient.monitor.source ?? '')} · ข้อมูลของ {patient.patient_id} · ทะเบียนผู้ป่วยสาธิต{patient.monitor.simulation_state ? ` · สถานการณ์: ${patient.monitor.simulation_state}` : ''}</p>
          <div className={s.guideGrid}>
            <div><strong>อัตราการเต้นหัวใจ (bpm)</strong><p>จำนวนครั้งที่หัวใจเต้นใน 1 นาที ค่าอาจสูงขึ้นชั่วคราวหลังขยับตัว เปลี่ยนท่าทาง หรือพูดคุย</p></div>
            <div><strong>ออกซิเจนในเลือด (SpO₂ %)</strong><p>สัดส่วนออกซิเจนที่จับกับเม็ดเลือดแดง หากตัวเลขแกว่งหรือขาดช่วง มักเกิดจากเซนเซอร์ที่นิ้วหลวมหรือมือเย็น</p></div>
            <div><strong>อัตราการหายใจ (ครั้ง/นาที)</strong><p>จำนวนครั้งที่หายใจเข้า-ออกใน 1 นาที ขณะพูดคุยหรือไอ ค่าอาจเปลี่ยนแปลงได้ตามปกติ</p></div>
          </div>
          <small>ตัวเลขบนหน้าจอใช้ประกอบการติดตามของทีมดูแล ห้ามใช้ปรับยาหรือวินิจฉัยอาการด้วยตนเอง หากรู้สึกไม่สบายให้แจ้งบุคลากรโดยตรง</small>
          <div className={s.quick}><button onClick={() => setActive('trends')}><span>ดูแนวโน้มย้อนหลัง<small>เลือก 1 ชั่วโมงถึง 7 วัน</small></span><Icon name="evidence" /></button><button onClick={() => setActive('reports')}><span>อ่านสรุปประจำวัน<small>พร้อมดาวน์โหลด Text</small></span><Icon name="reports" /></button><button onClick={() => setActive('profile')}><span>ตรวจข้อมูลของฉัน<small>ประวัติที่ทีมดูแลยืนยัน</small></span><Icon name="patients" /></button></div>
          <a className={s.link} href="/api/me/report">ดาวน์โหลดค่าล่าสุด · Text</a>
        </div>
      </details>
    </>}
    {active === 'trends' && <PatientTrends patientId={patient.patient_id} />}
    {active === 'care' && <><PatientCare {...careProps} /><CareMessages /></>}
    {active === 'chat' && <CareChat />}
    {active === 'reports' && <PatientReports patientId={patient.patient_id} />}
    {active === 'profile' && <PatientProfile patient={patient} {...careProps} />}
  </>;
}

