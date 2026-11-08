"use client";

import { useEffect, useState } from 'react';
import { formatStaleDuration, LatestVitals, PatientAnalysis } from './MonitorPanel';
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
import NotificationPanel from './NotificationPanel';
import s from './PatientPortal.module.css';

const PATIENT_NIGHT_SHIFT_KEY = 'smart-ward-patient-night-shift';

export default function PatientPortal() {
  const live = usePatientResource<PatientRecord>('/api/me', 3000, true);
  return <main id="main-content" tabIndex={-1} className={s.page}>
    {live.data && live.error && <div className={s.error} role="alert">{live.error} · ข้อมูลด้านล่างเป็นข้อมูลที่โหลดสำเร็จครั้งล่าสุด <button onClick={live.refresh}>ลองใหม่</button></div>}
    {!live.data ? <><h1>การดูแลของฉัน</h1><ResourceStatus error={live.error} loading={live.loading} retry={live.refresh} /></>
      : <PatientWorkspace key={live.data.patient_id} patient={live.data} />}
    <footer className={s.footer}>ข้อมูลเพื่อสาธิตและวิจัยเท่านั้น · AI ช่วยจัดข้อมูล ไม่ใช้แทนการประเมินของบุคลากร · หน้านี้ไม่ใช่ช่องทางฉุกเฉินและไม่ได้ติดต่อทีมดูแลหรือเรียกรถพยาบาลอัตโนมัติ</footer>
  </main>;
}

function PatientWorkspace({ patient }: { patient: PatientRecord }) {
  const [active, setActive] = useState<PatientSection>(() => typeof window !== 'undefined'
    && new URLSearchParams(window.location.search).get('section') === 'chat' ? 'chat' : 'overview');
  const [showSettings, setShowSettings] = useState(false);
  const [nightShift, setNightShift] = useState(() => {
    try { return typeof window !== 'undefined' && localStorage.getItem(PATIENT_NIGHT_SHIFT_KEY) === '1'; } catch { return false; }
  });
  const [now, setNow] = useState(() => Date.now() / 1000);
  const careResource = usePatientResource<MyCare>('/api/me/care', 15000);
  const chatStatus = usePatientResource<{ unread: number; latest: { sender_display_name: string } | null; care_team: { display_name: string } }>('/api/me/chat/status', 5000, true);
  const care = careResource.data?.patient_id === patient.patient_id ? careResource.data : null;
  useEffect(() => { const timer = setInterval(() => setNow(Date.now() / 1000), 1000); return () => clearInterval(timer); }, []);
  function togglePatientNightShift() {
    setNightShift((prev) => {
      const next = !prev;
      try { localStorage.setItem(PATIENT_NIGHT_SHIFT_KEY, next ? '1' : '0'); } catch { /* ignore */ }
      void fetch('/api/session/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ night_shift: next }),
      }).catch(() => {});
      return next;
    });
  }
  const fresh = isFreshReading(patient.monitor, now);
  const analysis = safeAnalysis(patient.monitor, now, fresh);
  const open = care?.tasks.filter((task) => ['PENDING', 'ACKNOWLEDGED'].includes(task.state)) ?? [];
  const nextTask = open[0];
  const careProps = { care, error: careResource.error, loading: careResource.loading, refresh: careResource.refresh };

  const hr = patient.monitor?.heart_rate;
  const spo2 = patient.monitor?.spo2;
  const rr = patient.monitor?.respiratory_rate;

  const hrStatus = !fresh || !hr
    ? { tone: s.statusStale, badge: '— รอข้อมูล', hint: 'รอการอ่านค่าจากเซนเซอร์ข้างเตียง', percent: 50, barColor: '#d2b48c' }
    : hr < 60
      ? { tone: s.statusWarning, badge: 'ค่อนข้างช้า (<60)', hint: 'จังหวะช้ากว่าปกติเล็กน้อย กำลังติดตาม', percent: Math.max(15, Math.min(45, ((hr - 40) / 60) * 50)), barColor: '#d4a34b' }
      : hr > 100
        ? { tone: s.statusWarning, badge: 'ค่อนข้างเร็ว (>100)', hint: 'อาจเกิดจากการขยับตัวหรือพูดคุย', percent: Math.max(55, Math.min(95, 50 + ((hr - 100) / 40) * 50)), barColor: '#d4a34b' }
        : { tone: s.statusNormal, badge: 'ปกติ (60–100)', hint: 'จังหวะหัวใจสม่ำเสมอดี สบายใจได้ครับ', percent: 50, barColor: '#247354' };

  const spo2Status = !fresh || !spo2
    ? { tone: s.statusStale, badge: '— รอข้อมูล', hint: 'รอการอ่านค่าจากเซนเซอร์ข้างเตียง', percent: 50, barColor: '#d2b48c' }
    : spo2 < 92
      ? { tone: s.statusCritical, badge: 'ต่ำกว่าเกณฑ์ (<92%)', hint: 'พยาบาลเวรรับทราบแล้วและกำลังเข้าดูแล', percent: 25, barColor: '#ad394b' }
      : spo2 < 95
        ? { tone: s.statusWarning, badge: 'เฝ้าระวัง (92–94%)', hint: 'ออกซิเจนค่อนข้างต่ำ ลองสูดหายใจลึกๆ', percent: 50, barColor: '#d4a34b' }
        : { tone: s.statusNormal, badge: 'ปกติ (95–100%)', hint: 'ออกซิเจนในเลือดเพียงพอดีเยี่ยม', percent: 90, barColor: '#247354' };

  const rrStatus = !fresh || !rr
    ? { tone: s.statusStale, badge: '— รอข้อมูล', hint: 'รอการอ่านค่าจากเซนเซอร์ข้างเตียง', percent: 50, barColor: '#d2b48c' }
    : rr < 12
      ? { tone: s.statusWarning, badge: 'ช้ากว่าเกณฑ์ (<12)', hint: 'จังหวะการหายใจค่อนข้างช้า', percent: 25, barColor: '#d4a34b' }
      : rr > 20
        ? { tone: s.statusWarning, badge: 'เร็วกว่าเกณฑ์ (>20)', hint: 'อาจเกิดจากการพูดคุยหรือไอจาม', percent: 80, barColor: '#d4a34b' }
        : { tone: s.statusNormal, badge: 'ปกติ (12–20)', hint: 'จังหวะการหายใจอยู่ในเกณฑ์ปกติ', percent: 50, barColor: '#247354' };

  const overallStatus = !fresh || patient.monitor?.status === 'STALE_DATA'
    ? {
        badgeClass: s.statusStale,
        icon: '●',
        title: 'กำลังรอการเชื่อมต่อสายวัดข้างเตียง',
        desc: 'สายวัดที่นิ้วอาจขยับหรือเลื่อนหลุด ลองสวมให้กระชับพอดี หรือกดแชทแจ้งพยาบาลได้ครับ',
      }
    : patient.monitor?.status === 'CRITICAL'
      ? {
          badgeClass: s.statusCritical,
          icon: '●',
          title: 'สัญญาณชีพมีการเปลี่ยนแปลง',
          desc: 'ระบบส่งสัญญาณเตือนทีมแพทย์และพยาบาลเรียบร้อยแล้ว และกำลังเข้าตรวจดูแลข้างเตียง',
        }
      : patient.monitor?.status === 'WARNING'
        ? {
            badgeClass: s.statusWarning,
            icon: '●',
            title: 'สัญญาณชีพอยู่ในเกณฑ์เฝ้าระวัง',
            desc: 'มีบางค่าเปลี่ยนแปลงเล็กน้อย ทีมพยาบาลกำลังติดตามข้อมูลอย่างต่อเนื่อง',
          }
        : {
            badgeClass: s.statusNormal,
            icon: '●',
            title: 'สุขภาพและสัญญาณชีพอยู่ในเกณฑ์ดี',
            desc: 'การเต้นของหัวใจ ระดับออกซิเจน และการหายใจเป็นปกติดี พักผ่อนได้สบายใจครับ',
          };

  return <div className={nightShift ? s.nightShift : undefined}>
    <AgentAssistant key={active} section={active} patientId={patient.patient_id} />
    <header className={s.hero}><div className={s.identity}><div className={s.avatar}><Icon name="patients" size={28} /></div><div><span className={s.eyebrow}>MY CARE · {patient.patient_id}</span><h1>การดูแลของฉัน</h1><p>โซน {patient.profile.zone} · ห้อง {patient.profile.room_number} · แพทย์ผู้ดูแล: <b>{chatStatus.data?.care_team?.display_name ?? patient.profile.doctor}</b></p></div></div><div className={s.heroActions}><button type="button" className={s.primary} onClick={() => setActive('chat')}><Icon name="chat" size={18} />แชทกับแพทย์และทีมดูแล{Boolean(chatStatus.data?.unread) && <span className={s.unread} aria-label={`ข้อความใหม่ ${chatStatus.data?.unread}`}>{chatStatus.data?.unread}</span>}</button><button type="button" onClick={() => setShowSettings((v) => !v)} aria-expanded={showSettings}><Icon name="settings" size={18} />ตั้งค่า</button><span className={s.badge}>{fresh ? 'ได้รับข้อมูลการวัดล่าสุด' : `รอข้อมูลการวัดใหม่ · ${formatStaleDuration(patient.monitor?.timestamp, now)}`}</span></div></header>
    {showSettings && (
      <section className={s.card} aria-label="ตั้งค่าพอร์ทัลผู้ป่วย">
        <div className={s.eyebrow}>PATIENT SETTINGS · ตั้งค่าระบบ</div>
        <h3>การแสดงผลและการแจ้งเตือนมือถือ</h3>
        <div className={s.actions}>
          <button type="button" onClick={togglePatientNightShift} aria-pressed={nightShift}>
            {nightShift ? 'โหมดสว่าง' : 'โหมดถนอมสายตา (Night Shift)'}
          </button>
          <button type="button" onClick={() => setShowSettings(false)}>ปิดหน้าต่างตั้งค่า</button>
        </div>
        <NotificationPanel patient />
      </section>
    )}
    <nav className={s.nav} aria-label="หมวดข้อมูลผู้ป่วย">{patientSections.map((section) => <button key={section.key} aria-pressed={active === section.key} onClick={() => setActive(section.key)}><Icon name={section.icon} size={19} />{section.title}{section.key === 'chat' && Boolean(chatStatus.data?.unread) && <span className={s.unread} aria-label={`ข้อความใหม่ ${chatStatus.data?.unread}`}>{chatStatus.data?.unread}</span>}</button>)}</nav>
    {active === 'overview' && <>
      {/* 1. Visual Health Status Banner for Patient & Family */}
      <section className={s.patientHealthBanner} aria-label="สถานะสุขภาพโดยรวม">
        <div className={s.patientHealthTop}>
          <div className={`${s.patientHealthStatusBadge} ${overallStatus.badgeClass}`}>
            <span>{overallStatus.icon}</span>
            <span>{overallStatus.title}</span>
          </div>
          <button type="button" className={s.primary} onClick={() => setActive('chat')}>
            <Icon name="chat" size={17} /> แชทกับแพทย์
          </button>
        </div>
        <p className={s.patientHealthDesc}>{overallStatus.desc}</p>
        <div className={s.patientHealthMetaRow}>
          <span className={s.patientHealthChip}>
            แพทย์เจ้าของไข้: <b>{chatStatus.data?.care_team?.display_name ?? patient.profile.doctor}</b>
          </span>
          <span className={s.patientHealthChip}>
            ห้อง {patient.profile.room_number} · เตียง {patient.profile.bed_number}
          </span>
          {nextTask && (
            <span className={s.patientHealthChip}>
              งานดูแลรอบถัดไป: <b>{nextTask.title}</b> ({careTime(nextTask.scheduled_at)})
            </span>
          )}
        </div>
      </section>

      {/* 2. Visual Patient Vitals Cards with Range Gauges */}
      <div className={s.patientVitalsGrid}>
        {/* Heart Rate */}
        <div className={s.patientVitalCard}>
          <div className={s.patientVitalHeader}>
            <h3 className={s.patientVitalTitle}>ชีพจร (Heart Rate)</h3>
            <span className={`${s.patientHealthStatusBadge} ${hrStatus.tone}`} style={{ fontSize: 11.5, padding: '3px 10px' }}>
              {hrStatus.badge}
            </span>
          </div>
          <div className={s.patientVitalValueRow}>
            <span className={s.patientVitalNumber}>
              {fresh && typeof hr === 'number' && Number.isFinite(hr) ? hr : '—'}
            </span>
            <span className={s.patientVitalUnit}>ครั้ง/นาที (bpm)</span>
          </div>
          <div className={s.patientGaugeTrack}>
            <div className={s.patientGaugeFill} style={{ width: `${hrStatus.percent}%`, background: hrStatus.barColor }} />
          </div>
          <div className={s.patientVitalRangeText}>
            <span>ต่ำ (&lt;60)</span>
            <span style={{ color: '#0e6b52', fontWeight: 750 }}>เกณฑ์ปกติ 60 – 100</span>
            <span>สูง (&gt;100)</span>
          </div>
          <p className={s.patientVitalHint}>{hrStatus.hint}</p>
        </div>

        {/* SpO2 */}
        <div className={s.patientVitalCard}>
          <div className={s.patientVitalHeader}>
            <h3 className={s.patientVitalTitle}>ระดับออกซิเจนในเลือด (SpO₂)</h3>
            <span className={`${s.patientHealthStatusBadge} ${spo2Status.tone}`} style={{ fontSize: 11.5, padding: '3px 10px' }}>
              {spo2Status.badge}
            </span>
          </div>
          <div className={s.patientVitalValueRow}>
            <span className={s.patientVitalNumber}>
              {fresh && typeof spo2 === 'number' && Number.isFinite(spo2) ? spo2 : '—'}
            </span>
            <span className={s.patientVitalUnit}>%</span>
          </div>
          <div className={s.patientGaugeTrack}>
            <div className={s.patientGaugeFill} style={{ width: `${spo2Status.percent}%`, background: spo2Status.barColor }} />
          </div>
          <div className={s.patientVitalRangeText}>
            <span>เฝ้าระวัง (&lt;95%)</span>
            <span style={{ color: '#0e6b52', fontWeight: 750 }}>เกณฑ์ปกติ 95 – 100%</span>
            <span>ดีเยี่ยม</span>
          </div>
          <p className={s.patientVitalHint}>{spo2Status.hint}</p>
        </div>

        {/* Respiratory Rate */}
        <div className={s.patientVitalCard}>
          <div className={s.patientVitalHeader}>
            <h3 className={s.patientVitalTitle}>อัตราการหายใจ (Respiratory Rate)</h3>
            <span className={`${s.patientHealthStatusBadge} ${rrStatus.tone}`} style={{ fontSize: 11.5, padding: '3px 10px' }}>
              {rrStatus.badge}
            </span>
          </div>
          <div className={s.patientVitalValueRow}>
            <span className={s.patientVitalNumber}>
              {fresh && typeof rr === 'number' && Number.isFinite(rr) ? rr : '—'}
            </span>
            <span className={s.patientVitalUnit}>ครั้ง/นาที</span>
          </div>
          <div className={s.patientGaugeTrack}>
            <div className={s.patientGaugeFill} style={{ width: `${rrStatus.percent}%`, background: rrStatus.barColor }} />
          </div>
          <div className={s.patientVitalRangeText}>
            <span>ช้า (&lt;12)</span>
            <span style={{ color: '#0e6b52', fontWeight: 750 }}>เกณฑ์ปกติ 12 – 20</span>
            <span>เร็ว (&gt;20)</span>
          </div>
          <p className={s.patientVitalHint}>{rrStatus.hint}</p>
        </div>
      </div>

      <div className={s.actions}>
        <button className={s.primary} onClick={() => setActive('chat')}><Icon name="chat" size={18} />แชทข้อความกับแพทย์และทีมดูแล (Messenger)</button>
        <button onClick={() => setActive('care')}><Icon name="care" size={18} />แจ้งเรื่อง / ติดตามงานดูแล{open.length ? ` (${open.length})` : ''}</button>
        <button onClick={() => setActive('trends')}><Icon name="evidence" size={18} />ดูกราฟย้อนหลัง</button>
        <span className={s.badge}>ข้อมูลการวัด: {fresh ? 'เชื่อมต่อสด' : `ขาดช่วง (${formatStaleDuration(patient.monitor?.timestamp, now)})`}</span>
      </div>

      {/* 3. Clinical Details Drawer for Modified NEWS2 */}
      <details className={s.inlineDetails}>
        <summary>ดูรายละเอียดทางคลินิก (Modified NEWS2 &amp; เกณฑ์มาตรฐานข้างเตียง)</summary>
        <LatestVitals state={patient.monitor} now={now} />
      </details>

      <div className={s.split}>
        <section className={s.card}>
          <div className={s.eyebrow}>CARE SCHEDULE · แผนดูแลประจำวัน</div>
          <h3>งานดูแลที่กำลังติดตาม</h3>
          {!care ? <ResourceStatus error={careResource.error} loading={careResource.loading} retry={careResource.refresh} /> : <>
            <p>งานเปิด <b>{care.open_count}</b> รายการ · บันทึกเสร็จวันนี้ <b>{care.done_today}</b> รายการ</p>
            {open.length ? <ol className={s.timeline}>{open.slice(0, 3).map((task) => <li key={task.id} className={s.task}><strong>{task.title}</strong><small>กำหนด {careTime(task.scheduled_at)} · {task.state === 'ACKNOWLEDGED' ? 'ทีมดูแลรับงานแล้ว' : 'รอทีมดูแลรับงาน'}</small></li>)}</ol> : <p className={s.empty}>ไม่มีงานดูแลค้างในขณะนี้ ทีมพยาบาลจะเข้าตรวจตามรอบเวลา</p>}
            <button onClick={() => setActive('care')}>ดูงานและแผนทั้งหมด <Icon name="arrow" size={17} /></button>
          </>}
        </section>
        <section className={s.card}>
          <div className={s.eyebrow}>AI ASSISTANT · LOCAL ANALYSIS</div>
          <h3>ระบบเฝ้าระวังอัตโนมัติ</h3>
          <p>{analysis ? analysis.is_anomaly ? 'สัญญาณมีรูปแบบที่ควรตรวจซ้ำ ระบบแจ้งทีมพยาบาลเรียบร้อยแล้ว' : 'การประเมินรอบล่าสุดสม่ำเสมอดี และบันทึกข้อมูลเข้าสู่ระบบต่อเนื่อง' : 'กำลังรอรับข้อมูลจากเซนเซอร์'}</p>
          {analysis?.evaluated_at && <small>ประเมินรอบล่าสุด: {careTime(analysis.evaluated_at)}</small>}
          <details className={s.inlineDetails}><summary>ดูค่าคาดการณ์และที่มาของ AI</summary><PatientAnalysis state={patient.monitor} now={now} /></details>
        </section>
      </div>
      <VitalCharts points={patient.monitor.history} title="แนวโน้มสัญญาณชีพย้อนหลัง" description="การเปลี่ยนแปลงของชีพจร ออกซิเจน และการหายใจ" />
      <details className={s.learnMoreDrawer}>
        <summary className={s.learnMoreSummary}>
          <span>คำอธิบายค่าสัญญาณชีพเบื้องต้น ข้อมูลระบบ และทางลัดเพิ่มเติม (Learn More)</span>
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
  </div>;
}

