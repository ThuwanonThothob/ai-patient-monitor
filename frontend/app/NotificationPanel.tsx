"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Icon from "./Icon";
import s from "./Ward.module.css";
import { requestJson } from './apiRequest';
import { inspectPushEnvironment, type PushEnvironment } from './pushEnvironment';

type Device = { id: number; fingerprint: string; enabled: boolean; zone: string; include_warning: boolean };
type PushState = {
  ready: boolean;
  status: string;
  public_key: string | null;
  session_expires_at: number | null;
  devices: Device[];
  events: { id: number; kind: string; state: string; attempts: number; updated_at: number; error_code: string | null }[];
};

const configurationLabels: Record<string, string> = {
  DISABLED: "ยังไม่ได้เปิด Web Push ที่เซิร์ฟเวอร์",
  MISSING_DEPENDENCY: "ต้องติดตั้ง requirements-push.txt",
  MISSING_CONTACT: "ต้องตั้งอีเมลติดต่อผู้ดูแลใน WARD_VAPID_SUBJECT",
  MISSING_OR_INVALID_KEY: "ต้องสร้างและตั้งค่า VAPID key",
  READY: "เซิร์ฟเวอร์พร้อมเชื่อมต่ออุปกรณ์",
};

const deliveryLabels: Record<string, string> = {
  QUEUED: "เข้าคิวแล้ว",
  SENDING: "กำลังส่ง",
  ACCEPTED: "ผู้ให้บริการรับแล้ว",
  RETRY: "รอลองใหม่",
  FAILED: "ส่งไม่สำเร็จ",
  EXPIRED: "หมดอายุ / ไม่ส่งข้อมูลเก่า",
  CANCELLED: "ยกเลิกแล้ว",
  BUNDLED: "รวมในข้อความแจ้งเตือนเดียวกัน",
};

const permissionLabels: Record<string, string> = {
  default: "ยังไม่ได้ขออนุญาต",
  granted: "อนุญาตแล้ว",
  denied: "ถูกบล็อก — แก้ในตั้งค่าเว็บไซต์",
  unsupported: "เบราว์เซอร์นี้ยังไม่รองรับ",
  install: "ต้องเปิดจากไอคอนบนหน้าจอโฮมก่อน",
  checking: "กำลังตรวจสอบ…",
};

async function fingerprint(subscription: PushSubscription) {
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(subscription.endpoint));
  return Array.from(new Uint8Array(hash), (value) => value.toString(16).padStart(2, "0")).join("");
}

export default function NotificationPanel({ patient = false }: { patient?: boolean }) {
  const [state, setState] = useState<PushState | null>(null);
  const [permission, setPermission] = useState("checking");
  const [environment, setEnvironment] = useState<PushEnvironment | null>(null);
  const [zone, setZone] = useState("ALL");
  const [warning, setWarning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [localFingerprint, setLocalFingerprint] = useState<string | null>(null);
  const initialized = useRef<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    const data = await requestJson<PushState>("/api/notifications/status", { signal });
    if (!signal?.aborted) setState(data);
    return data;
  }, []);

  useEffect(() => {
    let stopped = false;
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      const env = inspectPushEnvironment();
      setEnvironment(env);
      setPermission(env.needsInstall ? 'install' : env.supported ? Notification.permission : "unsupported");
      try {
        const data = await load(abort.signal);
        if (stopped) return;
        setLoadError("");
        if (env.supported) {
          const registration = await navigator.serviceWorker.getRegistration("/");
          const subscription = await registration?.pushManager.getSubscription();
          const key = subscription ? await fingerprint(subscription) : null;
          if (stopped) return;
          setLocalFingerprint(key);
          const device = data.devices.find((item) => item.fingerprint === key && item.enabled);
          if (device && initialized.current !== key) {
            initialized.current = key;
            setZone(device.zone);
            setWarning(Boolean(device.include_warning));
          }
        }
      } catch (e) {
        if (!stopped) setLoadError((e as Error).message);
      } finally {
        if (!stopped) timer = setTimeout(refresh, 5000);
      }
    }
    void refresh();
    return () => {
      stopped = true;
      abort.abort();
      clearInterval(timer);
    };
  }, [load]);

  const device = state?.devices.find((item) => item.enabled && item.fingerprint === localFingerprint);
  const localSubscription = localFingerprint !== null;

  async function enable() {
    if (!state?.public_key || busy || !environment?.secure || !environment.supported || environment.needsInstall) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const granted = await Notification.requestPermission();
      setPermission(granted);
      if (granted !== "granted") throw new Error("ยังไม่ได้รับอนุญาต เปิดสิทธิ์ในตั้งค่าเว็บไซต์แล้วลองใหม่");
      await navigator.serviceWorker.register("/sw.js", { scope: "/", updateViaCache: 'none' });
      const registration = await Promise.race([
        navigator.serviceWorker.ready,
        new Promise<never>((_, reject) => setTimeout(() => reject(new Error("Service Worker ยังไม่พร้อม กรุณาโหลดหน้าใหม่")), 12000)),
      ]);
      const key = Uint8Array.from(atob(state.public_key.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));
      const existing = await registration.pushManager.getSubscription();
      if (existing?.options.applicationServerKey) {
        const original = new Uint8Array(existing.options.applicationServerKey);
        if (original.length !== key.length || original.some((value, index) => value !== key[index])) {
          throw new Error("VAPID key เปลี่ยนแล้ว กรุณากดหยุดแจ้งเตือนก่อน แล้วเปิดใหม่");
        }
      }
      const subscription = existing ?? await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
      await requestJson("/api/notifications/subscriptions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...subscription.toJSON(), zone, include_warning: warning }),
      });
      const keyFingerprint = await fingerprint(subscription);
      setLocalFingerprint(keyFingerprint);
      initialized.current = keyFingerprint;
      await load();
      setMessage("ผูกอุปกรณ์กับการเข้าสู่ระบบนี้แล้ว กดส่งข้อความทดสอบและตรวจบนโทรศัพท์ด้วยตัวเอง");
    } catch (e) {
      setError(e instanceof Error ? e.message : "เปิดแจ้งเตือนไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  async function disable() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      if (device) {
        await requestJson(`/api/notifications/subscriptions/${device.id}`, { method: "DELETE" });
      }
      if ("serviceWorker" in navigator) {
        const registration = await navigator.serviceWorker.getRegistration("/");
        const subscription = await registration?.pushManager.getSubscription();
        await subscription?.unsubscribe();
      }
      setLocalFingerprint(null);
      initialized.current = null;
      await load();
      setMessage("หยุดแจ้งเตือนเครื่องนี้แล้ว ข้อความที่ส่งออกไปก่อนหน้านี้อาจยังปรากฏได้");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    if (!device) return;
    setBusy(true);
    setMessage("");
    setError("");
    try {
      await requestJson(`/api/notifications/subscriptions/${device.id}/test`, { method: "POST" });
      setMessage("เข้าคิวทดสอบแล้ว ดูผลด้านล่าง และตรวจว่ามีข้อความปรากฏบนโทรศัพท์จริงหรือไม่");
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="ตั้งค่าการแจ้งเตือนมือถือ">
      <div className={s.notice}>
        <b>ช่องทางเสริมสำหรับทีมดูแล ไม่ใช่สัญญาณฉุกเฉินหลัก</b>
        <p style={{ margin: "4px 0 0" }}>
          Web Push อาจล่าช้าหรือไม่แสดงเมื่อเน็ตขาด แบตหมด หรือเปิดโหมดห้ามรบกวน ต้องมีช่องทางติดต่อฉุกเฉินสำรองเสมอ
        </p>
      </div>

      <div className={s.steps}>
        {[
          ["เปิดบนโทรศัพท์", "ใช้ลิงก์ HTTPS ของฝั่งบุคลากรหรือผู้ป่วย แล้วเข้าสู่บัญชีที่ต้องการรับข้อความ"],
          ["ติดตั้งและอนุญาต", "iPhone / iPad: เพิ่มไปยังหน้าจอโฮม แล้วเปิดจากไอคอนก่อนกดอนุญาตแจ้งเตือน"],
          ["ทดสอบให้เห็นจริง", "ส่งข้อความทดสอบ ล็อกหน้าจอ และตรวจข้อความบนเครื่อง ก่อนนำไปสาธิต"],
        ].map(([title, text], index) => (
          <article key={title} className={s.step}>
            <span className={s.stepNumber}>{index + 1}</span>
            <b>{title}</b>
            <p>{text}</p>
          </article>
        ))}
      </div>

      <div className={s.panel}>
        <Header subscribed={Boolean(device && localSubscription)} />

        <div className={s.switchRow}>
          <span>1. เซิร์ฟเวอร์</span>
          <b>{state ? configurationLabels[state.status] ?? state.status : "กำลังโหลด…"}</b>
        </div>
        <div className={s.switchRow}>
          <span>2. รูปแบบที่เปิดอยู่</span>
          <b>{environment ? (environment.installed ? 'แอปจากหน้าจอโฮม' : 'เว็บในเบราว์เซอร์') : 'กำลังตรวจสอบ…'}</b>
        </div>
        <div className={s.switchRow}>
          <span>3. สิทธิ์เบราว์เซอร์</span>
          <b>{permissionLabels[permission]}</b>
        </div>
        <div className={s.switchRow}>
          <span>4. อุปกรณ์นี้</span>
          <b>
            {device && localSubscription
              ? patient
                ? 'เปิดรับข้อความของบัญชีคุณ'
                : `เปิดรับ · ${device.zone === "ALL" ? "ทุกโซน" : "โซน " + device.zone} · ${
                    device.include_warning ? "เฝ้าระวังและเร่งด่วน" : "เฉพาะเร่งด่วน"
                  }`
              : "ยังไม่ผูกกับการเข้าสู่ระบบนี้"}
          </b>
        </div>

        {environment && !environment.secure && (
          <p className={s.error}>
            ต้องเปิดผ่านลิงก์ HTTPS จึงจะรับแจ้งเตือนบนโทรศัพท์ได้ ลิงก์ HTTP หรือเลข IP ในเครือข่ายยังใช้รับ Push ไม่ได้
          </p>
        )}

        {environment?.needsInstall && (
          <div className={s.notice}>
            <b>ติดตั้งบน iPhone / iPad ก่อนเปิดแจ้งเตือน</b>
            <ol>
              <li>เปิดลิงก์นี้ใน Safari แล้วกดแชร์</li>
              <li>เลือก “เพิ่มไปยังหน้าจอโฮม” และกดเพิ่ม</li>
              <li>เปิด Smart Ward จากไอคอน เข้าสู่ระบบ แล้วกลับมาหน้านี้</li>
            </ol>
            <p>ใช้ iOS / iPadOS 16.4 ขึ้นไป และเปิดแจ้งเตือนจากภายในแอปที่ติดตั้ง</p>
          </div>
        )}

        {!patient && (
          <>
            <div className={s.filters}>
              <label htmlFor="push-zone">รับแจ้งเตือน</label>
              <select className={s.choice} id="push-zone" value={zone} onChange={(e) => setZone(e.target.value)}>
                {["ALL", "A", "B", "C"].map((value) => (
                  <option key={value} value={value}>
                    {value === "ALL" ? "ทุกโซน" : `โซน ${value}`}
                  </option>
                ))}
              </select>
            </div>
            <label className={s.actions}>
              <input type="checkbox" checked={warning} onChange={(e) => setWarning(e.target.checked)} />
              รวมระดับเฝ้าระวัง (ปกติรับเฉพาะเร่งด่วน)
            </label>
          </>
        )}

        <div className={s.actions}>
          <button
            className={s.primary}
            disabled={
              busy ||
              !state?.ready ||
              !environment?.secure ||
              ['install', 'unsupported', 'denied', 'checking'].includes(permission)
            }
            onClick={() => void enable()}
          >
            <Icon name="notifications" />
            {busy ? 'กำลังดำเนินการ…' : device ? "บันทึก / ผูกอุปกรณ์นี้อีกครั้ง" : "เปิดแจ้งเตือนเครื่องนี้"}
          </button>
          <button
            className={s.secondary}
            disabled={busy || !state?.ready || !device || !localSubscription}
            onClick={() => void test()}
          >
            ส่งข้อความทดสอบ
          </button>
          {(device || localSubscription) && (
            <button className={s.critical} disabled={busy} onClick={() => void disable()}>
              หยุดแจ้งเตือน
            </button>
          )}
        </div>

        {message && <p className={s.notice} role="status">{message}</p>}
        {error && <p className={s.error} role="alert">{error}</p>}
        {loadError && <p className={s.error} role="alert">{loadError}</p>}

        <details className={s.learnMoreDrawer}>
          <summary className={s.learnMoreSummary}>
            <span>🛡️ ความเป็นส่วนตัว การตั้งค่าเซิร์ฟเวอร์ และประวัติการส่ง (Learn More)</span>
            <span className={s.learnMoreBadge}>ดูประวัติ ({state?.events.length ?? 0})</span>
          </summary>
          <div className={s.learnMoreBody}>
            <div className={s.aiPanel} style={{ marginBottom: 14 }}>
              <b>
                <Icon name="shield" />
                ความเป็นส่วนตัวมาก่อน
              </b>
              <p className={s.aiText} style={{ margin: "10px 0" }}>
                หน้าจอล็อกแสดงเพียงว่ามีงานให้ตรวจสอบ ไม่แสดงชื่อ ID โรค หรือค่าสัญญาณชีพ
              </p>
              <p className={s.disclaimer}>
                ระบบรวมข้อความต่อเครื่องเพื่อลดการรบกวน และไม่ส่งรายการเก่าที่เกิน 5 นาที ไม่มีการส่งคำสั่งรักษาหรือติดต่อรถพยาบาล
              </p>
              <p className={s.disclaimer}>
                ผูกกับการเข้าสู่ระบบของบัญชีนี้เท่านั้น ออกจากระบบหรือเซสชันหมดอายุจะหยุดส่ง ต้องเปิดใช้งานอีกครั้งหลังเข้าสู่ระบบใหม่
                {state?.session_expires_at ? ` · หมดอายุ ${new Date(state.session_expires_at * 1000).toLocaleString("th-TH")}` : ""}
              </p>
              <details>
                <summary>ผู้ดูแลต้องตั้งค่าอะไร?</summary>
                <p className={s.disclaimer}>
                  ติดตั้ง backend/requirements-push.txt → สร้าง VAPID key → ตั้ง WARD_WEB_PUSH_ENABLED, key, อีเมลผู้ดูแล และ HTTPS origin → restart backend
                </p>
                <p className={s.disclaimer}>ดูขั้นตอนใน docs/WEB_PUSH.md · ไม่ต้องใส่ private key ในหน้าเว็บ</p>
              </details>
            </div>

            <h3 className={s.h2} style={{ fontSize: 15, marginBottom: 6 }}>ประวัติการส่งของการเข้าสู่ระบบนี้</h3>
            <p className={s.muted}>
              “ผู้ให้บริการรับแล้ว” ไม่ได้ยืนยันว่าเครื่องแสดงข้อความ หรือบุคลากรรับทราบ ต้องกดรับทราบในหน้ารายการแจ้งเตือนแยกต่างหาก
            </p>
            <div className={s.tableWrap}>
              <table className={s.table}>
                <thead>
                  <tr>
                    <th>เวลา</th>
                    <th>ประเภท</th>
                    <th>สถานะ</th>
                    <th>จำนวนครั้ง</th>
                  </tr>
                </thead>
                <tbody>
                  {state?.events.length ? (
                    state.events.map((event) => (
                      <tr key={event.id}>
                        <td>{new Date(event.updated_at * 1000).toLocaleTimeString("th-TH")}</td>
                        <td>
                          {event.kind === "TEST"
                            ? "ทดสอบ"
                            : event.kind.startsWith('CHAT:')
                            ? 'ข้อความแชท'
                            : event.kind === 'SIMULATION'
                            ? 'เหตุการณ์จำลอง TEST'
                            : "มีงานให้ตรวจสอบ"}
                        </td>
                        <td>
                          {deliveryLabels[event.state] ?? event.state}
                          {event.error_code && <small className={s.blockSmall}>{event.error_code}</small>}
                        </td>
                        <td>{event.attempts}</td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={4}>ยังไม่มีรายการส่ง — ตั้งค่าและทดสอบอุปกรณ์ก่อน</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </details>
      </div>
    </section>
  );
}

function Header({ subscribed }: { subscribed: boolean }) {
  return (
    <div className={s.titleRow}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Icon name="notifications" />
        <h2 className={s.h2}>เชื่อมต่อโทรศัพท์ของคุณ</h2>
      </div>
      <span className={`${s.pill} ${subscribed ? s.resolve : s.warning}`}>
        {subscribed ? "🟢 ผูกอุปกรณ์แล้ว" : "⚪ ยังไม่ได้ผูกอุปกรณ์"}
      </span>
    </div>
  );
}
