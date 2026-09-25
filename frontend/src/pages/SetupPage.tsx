import { useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import { useAction } from '../api/hooks'
import type { User } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { isNative, setSessionToken } from '../native'
import { Button, Field, Heading, Panel, Wordmark } from '../ui'
import { USERNAME_PATTERN } from '../utils'

export function SetupPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { setUser } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [err, setErr] = useState('')
  const create = useAction(
    () => api<User & { token?: string | null }>('/api/setup', { method: 'POST', json: { username, password }, headers: isNative() ? { 'X-Client': 'native' } : undefined }),
    async (user) => {
      await setSessionToken(user.token ?? null)
      setUser(user)
      await qc.invalidateQueries({ queryKey: ['setup-status'] })
      navigate('/events/new', { replace: true })
    },
  )
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!USERNAME_PATTERN.test(username)) return setErr('用户名只能用中英文、数字、_ . -')
    if (password.length < 8) return setErr('密码至少 8 位')
    if (password !== confirm) return setErr('两次输入的密码不一致')
    setErr('')
    create.mutate(undefined)
  }
  return (
    <div className="auth shell-admin">
      <div className="auth__box">
        <Wordmark big />
        <Heading title="首次设置" subtitle="只在空库出现一次。创建管理员后直接进入新建演出向导。" />
        <Panel>
          <form onSubmit={submit} className="fields">
            <Field label="管理员用户名" full>
              <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" placeholder="例如 captain" autoFocus />
            </Field>
            <Field label="设置密码">
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
            </Field>
            <Field label="再输入一次">
              <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />
            </Field>
            {err && <p className="error-text">{err}</p>}
            <div className="actions">
              <Button type="submit" variant="primary" loading={create.isPending}>
                创建管理员,进入新建向导 →
              </Button>
            </div>
          </form>
        </Panel>
      </div>
    </div>
  )
}
