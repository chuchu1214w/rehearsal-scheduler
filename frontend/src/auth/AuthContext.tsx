import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, type ReactNode } from 'react'

import { api, ApiError } from '../api/client'
import type { User } from '../api/types'

interface AuthValue {
  user: User | null
  loading: boolean
  setUser: (user: User | null) => void
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthValue | null>(null)

async function fetchMe(): Promise<User | null> {
  try {
    return await api<User>('/api/me')
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return null
    throw err
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const query = useQuery({ queryKey: ['me'], queryFn: fetchMe, staleTime: 60_000, retry: false })
  const value: AuthValue = {
    user: query.data ?? null,
    loading: query.isPending,
    setUser: (user) => qc.setQueryData(['me'], user),
    logout: async () => {
      try {
        await api('/api/auth/logout', { method: 'POST' })
      } finally {
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
