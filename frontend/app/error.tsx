"use client";

import Link from 'next/link';

export default function ErrorPage({ retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return <main className="login-form-area" style={{ minHeight: '70dvh' }}><section className="portal-card" role="alert">
    <span className="portal-kicker">SMART WARD</span><h1>เปิดหน้านี้ไม่สำเร็จ</h1>
    <p>กรุณาลองเปิดใหม่ หากยังพบปัญหาให้โหลดหน้าเว็บอีกครั้ง ข้อมูลที่ยังไม่ได้ส่งอาจต้องกรอกใหม่</p>
    <button onClick={retry}>ลองเปิดหน้าใหม่</button><Link href="/">กลับหน้าหลัก</Link>
  </section></main>;
}
