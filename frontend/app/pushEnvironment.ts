export type PushEnvironment = { ios: boolean; installed: boolean; secure: boolean; supported: boolean; needsInstall: boolean };

export function pushEnvironment(input: { userAgent: string; platform: string; maxTouchPoints: number; standalone: boolean; secure: boolean; supported: boolean }): PushEnvironment {
  const ios = /iPad|iPhone|iPod/.test(input.userAgent) || (input.platform === 'MacIntel' && input.maxTouchPoints > 1);
  return { ios, installed: input.standalone, secure: input.secure, supported: input.supported, needsInstall: ios && !input.standalone };
}

export function inspectPushEnvironment(): PushEnvironment {
  return pushEnvironment({
    userAgent: navigator.userAgent, platform: navigator.platform, maxTouchPoints: navigator.maxTouchPoints,
    standalone: window.matchMedia('(display-mode: standalone)').matches || (navigator as Navigator & { standalone?: boolean }).standalone === true,
    secure: window.isSecureContext,
    supported: 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window,
  });
}
