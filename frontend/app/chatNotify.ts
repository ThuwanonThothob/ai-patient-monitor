export const CHAT_NOTICE_KEY = 'smart-ward-chat-notifications';

export function chatNotificationsEnabled() {
  try {
    return typeof window !== 'undefined' && localStorage.getItem(CHAT_NOTICE_KEY) === '1'
      && 'Notification' in window && Notification.permission === 'granted';
  } catch { return false; }
}

export async function enableChatNotifications() {
  if (typeof window === 'undefined' || !('Notification' in window)) return false;
  const permission = await Notification.requestPermission();
  const enabled = permission === 'granted';
  try { localStorage.setItem(CHAT_NOTICE_KEY, enabled ? '1' : '0'); } catch { return false; }
  return enabled;
}

export function notifyNewChat(sender = 'ทีมดูแล') {
  if (!chatNotificationsEnabled()) return;
  void (async () => {
    const registration = await navigator.serviceWorker?.getRegistration('/');
    // A push subscription handles background and foreground delivery together.
    if (await registration?.pushManager.getSubscription()) return;
    const options = { body: `ข้อความใหม่จาก ${sender} · เปิดระบบเพื่อตรวจสอบ`, tag: 'smart-ward-care-chat' };
    if (registration) await registration.showNotification('Smart Ward · มีข้อความใหม่', options);
    else new Notification('Smart Ward · มีข้อความใหม่', options);
  })().catch(() => { /* In-app unread counts remain available when the OS declines. */ });
}
