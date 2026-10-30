"use client";

import { usePatientResource } from './usePatientResource';

type Profile = {
  subject: string; display_name: string; role: string; is_test: number;
  details: Record<string, string | string[]>;
  patient?: Record<string, string | number | null>;
  care_team?: { subject: string; display_name: string; role: string };
  assigned_patients?: { patient_id: string; name: string; condition: string; care_setting: string }[];
};

const labels: Record<string, string> = {
  professional_id: 'รหัสบุคลากร', department: 'หน่วยงาน', organization: 'องค์กร',
  contact_status: 'ช่องทางติดต่อ', care_setting: 'สถานที่ดูแล', emergency_contact: 'ผู้ติดต่อฉุกเฉิน',
};

export default function AccountProfile({ audience }: { audience: 'staff' | 'patient' }) {
  const { data, error, loading, refresh } = usePatientResource<Profile>('/api/session/profile', 30000, true);
  return <details className="account-menu"><summary>โปรไฟล์ของฉัน</summary><section>
    {loading && !data && <p>กำลังโหลดโปรไฟล์…</p>}
    {error && <p role="alert">{error} <button onClick={refresh}>ลองใหม่</button></p>}
    {data && <>
      <div className="profile-header-block">
        <span className="portal-kicker">{audience === 'staff' ? 'CARE PROVIDER PROFILE' : 'PATIENT PROFILE'}</span>
        <h3>{data.display_name}</h3>
        <p className="profile-role-line"><b>{data.role}</b> · ID <code>{data.subject}</code></p>
      </div>
      <dl>{Object.entries(data.details).filter(([key]) => !key.endsWith('_ids')).map(([key, value]) => <div key={key}><dt>{labels[key] ?? key}</dt><dd>{Array.isArray(value) ? value.join(', ') : value}</dd></div>)}</dl>
      {data.care_team && <div className="profile-assignment"><small>แพทย์/ทีมดูแลที่ได้รับมอบหมาย</small><b>{data.care_team.display_name}</b><span>{data.care_team.role} · {data.care_team.subject}</span></div>}
      {data.assigned_patients?.map(patient => <div className="profile-assignment" key={patient.patient_id}><small>ผู้ป่วยที่ได้รับมอบหมาย</small><b>{patient.name}</b><span>{patient.patient_id} · {patient.condition}</span></div>)}
      {data.patient?.care_goal && <p className="profile-note">เป้าหมายการดูแล: {data.patient.care_goal}</p>}
      <div className="profile-security-box">
        <b>ความปลอดภัยของบัญชีและรหัสผ่าน</b>
        <small>เซสชันได้รับการปกป้องด้วย HttpOnly Cookie และต่ออายุอัตโนมัติขณะใช้งาน หากต้องการเปลี่ยนรหัสผ่านหรือรีเซ็ตสิทธิ์ กรุณาติดต่อผู้ดูแลระบบหอผู้ป่วย</small>
      </div>
      {data.is_test === 1 && <small className="profile-test-disclaimer">โปรไฟล์ TEST สำหรับสาธิต ไม่ใช่ข้อมูลบุคลากรหรือผู้ป่วยจริง</small>}
    </>}
  </section></details>;
}
