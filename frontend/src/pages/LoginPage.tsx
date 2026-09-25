import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import { useAction } from '../api/hooks'
import type { User } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { isNative, reRegisterNativePushIfEnabled, setSessionToken } from '../native'
import { Button, Field, PrimaryBar, Wordmark } from '../ui'

export function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, setUser } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const from = (location.state as { from?: string } | null)?.from ?? '/'
  const login = useAction(
    () => api<User & { token?: string | null }>('/api/auth/login', { method: 'POST', json: { username, password }, headers: isNative() ? { 'X-Client': 'native' } : undefined }),
    (u) => {
      void setSessionToken(u.token ?? null).then(() => reRegisterNativePushIfEnabled())
      setUser(u)
      navigate(from === '/login' ? '/' : from, { replace: true })
    },
  )
  if (user) return <Navigate to="/" replace />
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (username.trim() && password) login.mutate(undefined)
  }
  return (
    <div className="auth shell-member">
      <div className="auth__box">
        <Wordmark big />
        <div className="kicker">Season · 舞团排练排程</div>
        <h1>欢迎回来</h1>
        <p className="lead">登录后,继续你的演出准备。</p>
        <form onSubmit={submit} className="fields">
          <Field label="用户名">
            <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoCapitalize="none" placeholder="输入用户名" autoFocus={!isNative()} />
          </Field>
          <Field label="密码">
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" placeholder="输入密码" />
          </Field>
          <p className="meta">
            忘记密码请找管理员重置。
            <br />
            连续 5 次密码错误,需等待 15 分钟再试。
          </p>
          <PrimaryBar>
            <Button type="submit" variant="primary" full loading={login.isPending} disabled={!username.trim() || !password}>
              登录
            </Button>
          </PrimaryBar>
        </form>
      </div>
    </div>
  )
}
