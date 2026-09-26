import { Capacitor, registerPlugin } from '@capacitor/core'
import { Preferences } from '@capacitor/preferences'
import { PushNotifications } from '@capacitor/push-notifications'

/** 原生 App(Capacitor)相关:API 地址、登录令牌(钥匙串)、原生推送、深链接。网页版这些函数都是空操作。 */

export const isNative = () => Capacitor.isNativePlatform()
export const API_BASE = ((import.meta.env.VITE_API_BASE as string | undefined) ?? '').replace(/\/$/, '')

type Api = (path: string, opts: { method: 'POST'; json: unknown }) => Promise<unknown>

// ---------- 登录令牌:存 iOS 钥匙串(AppDelegate.swift 里的 SecureStore 插件),不进备份 ----------
interface SecureStorePlugin {
  get(options: { key: string }): Promise<{ value?: string }>
  set(options: { key: string; value: string }): Promise<void>
  remove(options: { key: string }): Promise<void>
}
const SecureStore = registerPlugin<SecureStorePlugin>('SecureStore')

const TOKEN_KEY = 'season.session_token'
const PUSH_TOKEN_KEY = 'season.push_token'
const PUSH_ON_KEY = 'season.push_enabled'
let cachedToken: string | null | undefined
let tokenLoad: Promise<string | null> | null = null

const secureAvailable = () => isNative() && Capacitor.isPluginAvailable('SecureStore')

async function loadToken(): Promise<string | null> {
  if (secureAvailable()) {
    try {
      const { value } = await SecureStore.get({ key: TOKEN_KEY })
      if (value) return value
    } catch {
      /* 钥匙串不可用:退回 Preferences */
    }
    // 旧版本(或钥匙串写入失败时)存在 Preferences(UserDefaults)里:能迁移就迁到钥匙串
    const legacy = (await Preferences.get({ key: TOKEN_KEY })).value
    if (legacy) {
      try {
        await SecureStore.set({ key: TOKEN_KEY, value: legacy })
        await Preferences.remove({ key: TOKEN_KEY })
      } catch {
        /* 保留在 Preferences */
      }
    }
    return legacy
  }
  return (await Preferences.get({ key: TOKEN_KEY })).value
}

export async function getSessionToken(): Promise<string | null> {
  if (!isNative()) return null
  if (cachedToken !== undefined) return cachedToken
  tokenLoad ??= loadToken().then((v) => {
    if (cachedToken === undefined) cachedToken = v
    return cachedToken ?? null
  })
  return tokenLoad
}

export async function setSessionToken(token: string | null): Promise<void> {
  cachedToken = token
  tokenLoad = null
  if (!isNative()) return
  if (secureAvailable()) {
    try {
      if (token) await SecureStore.set({ key: TOKEN_KEY, value: token })
      else await SecureStore.remove({ key: TOKEN_KEY })
      await Preferences.remove({ key: TOKEN_KEY })
      return
    } catch {
      /* 钥匙串写入失败(极少见):退回 Preferences,保证能登录 */
    }
  }
  if (token) await Preferences.set({ key: TOKEN_KEY, value: token })
  else await Preferences.remove({ key: TOKEN_KEY })
}

// ---------- 原生推送 ----------
export async function nativePushEnabled(): Promise<boolean> {
  if (!isNative()) return false
  if ((await Preferences.get({ key: PUSH_ON_KEY })).value !== '1') return false
  return (await PushNotifications.checkPermissions()).receive === 'granted'
}

let pendingRegistration: { resolve: (token: string) => void; reject: (err: unknown) => void } | null = null

async function reportToken(api: Api, token: string): Promise<void> {
  await Preferences.set({ key: PUSH_TOKEN_KEY, value: token })
  await api('/api/push/native', { method: 'POST', json: { platform: Capacitor.getPlatform(), token } })
}

/** 申请权限 → 向 APNs 注册 → 等拿到 token 并上报服务器成功,才算开启。返回错误说明或 null。 */
export async function enableNativePush(api: Api): Promise<string | null> {
  const perm = await PushNotifications.requestPermissions()
  if (perm.receive !== 'granted') return '没有获得通知权限;可在 iPhone 设置 → Season → 通知 里重新允许。'
  const token = new Promise<string>((resolve, reject) => {
    pendingRegistration = { resolve, reject }
    setTimeout(() => reject(new Error('timeout')), 20_000)
  })
  await PushNotifications.register()
  try {
    await reportToken(api, await token)
  } catch {
    return '推送注册失败,请检查网络后再试。'
  } finally {
    pendingRegistration = null
  }
  await Preferences.set({ key: PUSH_ON_KEY, value: '1' })
  return null
}

/** 关闭推送:服务器解绑这台设备,并记住用户的选择 */
export async function disableNativePush(api: Api): Promise<void> {
  await unbindNativePush(api)
  await Preferences.remove({ key: PUSH_ON_KEY })
}

/** 登出前调用:服务器上解绑这台设备(之后不再收到这个账号的推送),但保留「已开启」,下一个账号登录时自动重新绑定 */
export async function unbindNativePush(api: Api): Promise<void> {
  if (!isNative()) return
  const { value } = await Preferences.get({ key: PUSH_TOKEN_KEY })
  if (value) await api('/api/push/native/unregister', { method: 'POST', json: { token: value } })
}

/** 已登录且开过推送:每次启动 / 登录后都重新 register(),APNs token 可能变化,且要绑定到当前账号 */
export async function reRegisterNativePushIfEnabled(): Promise<void> {
  if (await nativePushEnabled()) await PushNotifications.register()
}

// ---------- 启动时挂一次的监听 ----------
const NON_PAGE_PREFIXES = ['/api/', '/cal/', '/assets/', '/.well-known/']

export function attachNativeListeners(api: Api, navigate: (to: string) => void, onForegroundPush: () => void): () => void {
  if (!isNative()) return () => undefined
  const handles: Promise<{ remove: () => Promise<void> }>[] = []
  handles.push(
    PushNotifications.addListener('registration', async (t) => {
      if (pendingRegistration) {
        pendingRegistration.resolve(t.value)
        return
      }
      try {
        await reportToken(api, t.value)
      } catch {
        /* 未登录或离线:下次登录 / 启动时会再注册 */
      }
    }),
  )
  handles.push(
    PushNotifications.addListener('registrationError', (e) => {
      if (pendingRegistration) pendingRegistration.reject(e)
    }),
  )
  handles.push(PushNotifications.addListener('pushNotificationReceived', () => onForegroundPush()))
  handles.push(
    PushNotifications.addListener('pushNotificationActionPerformed', (e) => {
      const link = (e.notification.data as { link?: string } | undefined)?.link
      if (link && link.startsWith('/')) navigate(link)
      onForegroundPush()
    }),
  )
  void import('@capacitor/app').then(({ App }) => {
    handles.push(
      App.addListener('appUrlOpen', ({ url }) => {
        try {
          const u = new URL(url)
          if (NON_PAGE_PREFIXES.some((p) => u.pathname.startsWith(p))) return
          navigate(u.pathname + u.search)
        } catch {
          /* ignore */
        }
      }),
    )
  })
  return () => {
    for (const h of handles) void h.then((x) => x.remove())
  }
}
