import { Capacitor } from '@capacitor/core'
import { Preferences } from '@capacitor/preferences'
import { PushNotifications } from '@capacitor/push-notifications'

/** 原生 App(Capacitor)相关:API 地址、登录令牌、原生推送。网页版这些函数都是空操作。 */

export const isNative = () => Capacitor.isNativePlatform()
export const API_BASE = ((import.meta.env.VITE_API_BASE as string | undefined) ?? '').replace(/\/$/, '')

const TOKEN_KEY = 'season.session_token'
const PUSH_TOKEN_KEY = 'season.push_token'
const PUSH_ON_KEY = 'season.push_enabled'
let cachedToken: string | null | undefined

export async function getSessionToken(): Promise<string | null> {
  if (!isNative()) return null
  if (cachedToken !== undefined) return cachedToken
  const { value } = await Preferences.get({ key: TOKEN_KEY })
  cachedToken = value
  return value
}

export async function setSessionToken(token: string | null): Promise<void> {
  cachedToken = token
  if (!isNative()) return
  if (token) await Preferences.set({ key: TOKEN_KEY, value: token })
  else await Preferences.remove({ key: TOKEN_KEY })
}

export async function nativePushEnabled(): Promise<boolean> {
  if (!isNative()) return false
  return (await Preferences.get({ key: PUSH_ON_KEY })).value === '1'
}

/** 申请权限并向 APNs 注册;真正的 token 通过 registration 事件回来(见 attachNativeListeners) */
export async function enableNativePush(): Promise<string | null> {
  const perm = await PushNotifications.requestPermissions()
  if (perm.receive !== 'granted') return '没有获得通知权限;可在 iPhone 设置 → Season → 通知 里重新允许。'
  await PushNotifications.register()
  await Preferences.set({ key: PUSH_ON_KEY, value: '1' })
  return null
}

export async function disableNativePush(api: (path: string, opts: { method: 'POST'; json: unknown }) => Promise<unknown>): Promise<void> {
  const { value } = await Preferences.get({ key: PUSH_TOKEN_KEY })
  if (value) await api('/api/push/native/unregister', { method: 'POST', json: { token: value } })
  await Preferences.remove({ key: PUSH_ON_KEY })
}

/** App 启动时挂一次:推送 token 上报、点通知跳转、深链接 */
export function attachNativeListeners(
  api: (path: string, opts: { method: 'POST'; json: unknown }) => Promise<unknown>,
  navigate: (to: string) => void,
): void {
  if (!isNative()) return
  void PushNotifications.addListener('registration', async (t) => {
    await Preferences.set({ key: PUSH_TOKEN_KEY, value: t.value })
    try {
      await api('/api/push/native', { method: 'POST', json: { platform: Capacitor.getPlatform(), token: t.value } })
    } catch {
      /* 未登录时稍后再报 */
    }
  })
  void PushNotifications.addListener('registrationError', (e) => console.warn('push registration failed', e))
  void PushNotifications.addListener('pushNotificationActionPerformed', (e) => {
    const link = (e.notification.data as { link?: string } | undefined)?.link
    if (link && link.startsWith('/')) navigate(link)
  })
  void import('@capacitor/app').then(({ App }) => {
    void App.addListener('appUrlOpen', ({ url }) => {
      try {
        const u = new URL(url)
        navigate(u.pathname + u.search)
      } catch {
        /* ignore */
      }
    })
  })
}

/** 登录后如果之前开过推送,重新注册一次(token 可能变化,且要绑定到当前账号) */
export async function reRegisterNativePushIfEnabled(): Promise<void> {
  if (!isNative()) return
  if (await nativePushEnabled()) {
    const perm = await PushNotifications.checkPermissions()
    if (perm.receive === 'granted') await PushNotifications.register()
  }
}
