import { API_BASE, getSessionToken } from '../native'

export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `HTTP ${status}`)
    this.status = status
    this.detail = detail
  }
}

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

export async function api<T>(path: string, options: { method?: Method; json?: unknown; headers?: Record<string, string> } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json', ...(options.headers ?? {}) }
  const token = await getSessionToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  let body: string | undefined
  if (options.json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.json)
  }
  const res = await fetch(API_BASE + path, { method: options.method ?? 'GET', headers, body, credentials: API_BASE ? 'include' : 'same-origin' })
  if (res.status === 204) return undefined as T
  const text = await res.text()
  let data: unknown = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = text
  }
  if (!res.ok) {
    const detail = data && typeof data === 'object' && 'detail' in data ? (data as { detail: unknown }).detail : data
    throw new ApiError(res.status, detail ?? res.statusText)
  }
  return data as T
}

interface ValidationItem {
  loc?: unknown[]
  msg?: string
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const d = err.detail
    if (typeof d === 'string') return d
    if (Array.isArray(d)) {
      return d
        .map((item) => {
          const it = item as ValidationItem
          const loc = (it.loc ?? []).filter((x) => x !== 'body').join('.')
          const msg = (it.msg ?? '').replace(/^Value error, /, '')
          return loc ? `${loc}:${msg}` : msg
        })
        .join(';')
    }
    return `请求失败(${err.status})`
  }
  return err instanceof Error ? err.message : String(err)
}
