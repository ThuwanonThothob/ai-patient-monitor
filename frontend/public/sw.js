/* Web Push only. Never cache patient records, authenticated HTML, or API data. */
self.addEventListener('push', (event) => {
  let payload = {};
  try { payload = event.data?.json() ?? {}; } catch { /* generic privacy-safe fallback */ }
  const isTest = payload.tag === 'ward-test';
  const isChat = payload.tag === 'ward-chat';
  const isSimulation = payload.tag === 'ward-simulation';
  const allowed = ['/?section=notifications', '/?section=alerts', '/?section=chat', '/?section=triage', '/'];
  const url = allowed.includes(payload.url) ? payload.url : isTest ? '/?section=notifications' : '/?section=alerts';
  event.waitUntil(self.registration.showNotification(isChat ? 'Smart Ward · มีข้อความใหม่' : isSimulation ? 'Smart Ward · เหตุการณ์จำลอง TEST' : isTest ? 'Smart Ward · ทดสอบ' : 'Smart Ward · มีรายการให้ตรวจสอบ', {
    body: isChat ? 'เปิดแอปเพื่ออ่านข้อความ' : isSimulation ? 'Simulation มีเหตุการณ์ให้ตรวจสอบ เปิดแอปดูรายละเอียด' : 'เปิดศูนย์ดูแลและเข้าสู่ระบบเพื่อตรวจสอบรายละเอียด ไม่ใช่ระบบฉุกเฉิน',
    tag: isChat ? 'ward-chat' : isSimulation ? 'ward-simulation' : isTest ? 'ward-test' : 'ward-review',
    icon: '/smart-ward-192.png', badge: '/smart-ward-192.png',
    data: { url },
  }));
});
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  // Fixed same-origin destinations only; never navigate to payload-supplied URLs.
  const allowed = ['/?section=notifications', '/?section=alerts', '/?section=chat', '/?section=triage', '/'];
  const path = allowed.includes(event.notification.data?.url) ? event.notification.data.url : '/?section=alerts';
  const target = new URL(path, self.location.origin).href;
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(async (windows) => {
    for (const client of windows) {
      if (new URL(client.url).origin === self.location.origin && 'navigate' in client) {
        await client.navigate(target);
        return client.focus();
      }
    }
    return self.clients.openWindow(target);
  }));
});
