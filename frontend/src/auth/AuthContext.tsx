import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, useEffect, type ReactNode } from 'react'

import { api, ApiError } from '../api/client'
import type { User } from '../api/types'
import { isNative, setSessionToken, unbindNativePush } from '../native'
import { unbindWebPush } from '../push'

interface AuthValue {
  user: User | null
  loading: boolean
  /** 连不上服务器(不是没登录):显示「重试」而不是登录页 */
  offline: boolean
  retry: () => void
  setUser: (user: User | null) => void
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthValue | null>(null)

async function fetchMe(): Promise<User | null> {
  try {
    return await api<User>('/api/me')
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      await setSessionToken(null)
      return null
    }
    throw err
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const query = useQuery({ queryKey: ['me'], queryFn: fetchMe, staleTime: 60_000, retry: 1 })
  useEffect(() => {
    const onUnauthorized = () => {
      void setSessionToken(null)
      if (qc.getQueryData(['me'])) {
        qc.clear()
        qc.setQueryData(['me'], null)
      }
    }
    window.addEventListener('season:unauthorized', onUnauthorized)
    return () => window.removeEventListener('season:unauthorized', onUnauthorized)
  }, [qc])
  const value: AuthValue = {
    user: query.data ?? null,
    loading: query.isPending,
    offline: query.isError && !query.data,
    retry: () => void query.refetch(),
    setUser: (user) => qc.setQueryData(['me'], user),
    logout: async () => {
      try {
        // 先在服务器上解绑本机推送,否则登出后这台设备还会收到这个账号的通知
        if (isNative()) await unbindNativePush(api)
        else await unbindWebPush()
      } catch {
        /* 离线也要能登出 */
      }
      try {
        await api('/api/auth/logout', { method: 'POST' })
      } catch {
        /* 同上 */
      } finally {
        await setSessionToken(null)
        qc.clear()
        qc.setQueryData(['me'], null)
      }
    },
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth 必须在 AuthProvider 内使用')
  return value
}
