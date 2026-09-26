import { api } from './api/client'

/** PWA:安装提示与推送订阅的浏览器侧逻辑 */

declare global {
  interface Window {
    __installPrompt?: BeforeInstallPromptEvent | null
  }
  interface BeforeInstallPromptEvent extends Event {
    prompt: () => Promise<void>
    userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
  }
}

export const isStandalone = () => window.matchMedia('(display-mode: standalone)').matches || (navigator as unknown as { standalone?: boolean }).standalone === true
export const isIOS = () => /iPhone|iPad|iPod/.test(navigator.userAgent) && !(window as unknown as { MSStream?: unknown }).MSStream
export const pushSupported = () => 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window

export function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => undefined)
  })
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault()
    window.__installPrompt = e as BeforeInstallPromptEvent
    window.dispatchEvent(new Event('season:installable'))
  })
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null
  const reg = await navigator.serviceWorker.ready
  return reg.pushManager.getSubscription()
}

function urlBase64ToArrayBuffer(base64: string): ArrayBuffer {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4)
  const raw = atob((base64 + padding).replace(/-/g, '+').replace(/_/g, '/'))
  const buf = new ArrayBuffer(raw.length)
  const view = new Uint8Array(buf)
  for (let i = 0; i < raw.length; i++) view[i] = raw.charCodeAt(i)
  return buf
}

/** 申请权限并订阅;返回错误说明或 null */
export async function enablePush(): Promise<string | null> {
  if (!pushSupported()) return isIOS() && !isStandalone() ? 'iPhone 需要先「添加到主屏幕」,再从主屏幕图标打开后才能开启推送。' : '这个浏览器不支持推送通知。'
  const perm = await Notification.requestPermission()
  if (perm !== 'granted') return '没有获得通知权限;可在浏览器 / 系统设置里重新允许。'
  const reg = await navigator.serviceWorker.ready
  const { public_key } = await api<{ public_key: string }>('/api/push/public-key')
  const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToArrayBuffer(public_key) })
  const json = sub.toJSON()
  await api('/api/push/subscribe', { method: 'POST', json: { endpoint: sub.endpoint, keys: { p256dh: json.keys?.p256dh, auth: json.keys?.auth } } })
  return null
}

export async function disablePush(): Promise<void> {
  const sub = await currentSubscription()
  if (!sub) return
  await api('/api/push/unsubscribe', { method: 'POST', json: { endpoint: sub.endpoint } })
  await sub.unsubscribe()
}

/** 登出前:服务器上解绑这个浏览器的订阅(浏览器本身的订阅保留,下次登录自动重新绑定) */
export async function unbindWebPush(): Promise<void> {
  const sub = await currentSubscription()
  if (sub) await api('/api/push/unsubscribe', { method: 'POST', json: { endpoint: sub.endpoint } })
}

/** 登录后:浏览器里已有订阅就重新绑定到当前账号 */
export async function resyncWebPush(): Promise<void> {
  if (!pushSupported() || Notification.permission !== 'granted') return
  const sub = await currentSubscription()
  if (!sub) return
  const json = sub.toJSON()
  await api('/api/push/subscribe', { method: 'POST', json: { endpoint: sub.endpoint, keys: { p256dh: json.keys?.p256dh, auth: json.keys?.auth } } })
}
