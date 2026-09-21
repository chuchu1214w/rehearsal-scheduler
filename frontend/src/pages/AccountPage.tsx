import { useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import { useAction, useEvents } from '../api/hooks'
import { CalendarPanel } from '../components/CalendarPanel'
import { InstallPushPanel } from '../components/InstallPushPanel'
import { useAuth } from '../auth/AuthContext'
import { pickCurrentEvent } from '../layout/currentEvent'
import { Back, Button, Field, Heading, Note, Panel, PrimaryBar } from '../ui'
import { useToast } from '../ui/Toast'
import { fmtDateTime } from '../utils'

export function AccountPage() {
  const { user, setUser, logout } = useAuth()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { toast } = useToast()
  const events = useEvents()
  const [oldPw, setOldPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirm, setConfirm] = useState('')
  const [err, setErr] = useState('')
  const change = useAction(
    () => api('/api/me/password', { method: 'POST', json: { old_password: oldPw, new_password: newPw } }),
    () => {
      toast('密码已修改;其他设备需要重新登录')
      setOldPw('')
      setNewPw('')
      setConfirm('')
      if (user) setUser({ ...user, must_change_password: false })
      void qc.invalidateQueries({ queryKey: ['me'] })
    },
  )
  if (!user) return null
  const isAdmin = user.role === 'admin'
  const current = pickCurrentEvent(events.data ?? [])
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (newPw.length < 8) return setErr('新密码至少 8 位')
    if (newPw !== confirm) return setErr('两次输入的新密码不一致')
    setErr('')
    change.mutate(undefined)
  }
  const initial = (user.member_name ?? user.username).slice(0, 1)
  return (
    <>
      {!isAdmin && <Back to="/" label="返回首页" />}
      <Heading title="账号" subtitle={isAdmin ? '登录身份与密码。' : undefined} />
      {user.must_change_password && <Note tone="warning">你正在使用管理员设置的初始密码,建议现在修改。</Note>}
      <div className="profile">
        <div className="avatar">{initial}</div>
        <div>
          <h3 className="card-title">{user.member_name ?? user.username}</h3>
          <p className="muted">{isAdmin ? '管理员账号' : '成员账号 · 已开通'}</p>
        </div>
      </div>
      <div className="setting">
        <span>用户名</span>
        <span>{user.username}</span>
      </div>
      {!isAdmin && (
        <div className="setting">
          <span>当前演出</span>
          <span>{current?.name ?? '—'}</span>
        </div>
      )}
      <div className="setting">
        <span>上次登录</span>
        <span>{fmtDateTime(user.last_login_at)}</span>
      </div>
      <Panel>
        <h3 className="card-title" style={{ fontSize: 15 }}>
          修改密码
        </h3>
        <form onSubmit={submit} className="fields">
          <Field label="旧密码" full>
            <input type="password" value={oldPw} onChange={(e) => setOldPw(e.target.value)} autoComplete="current-password" />
          </Field>
          <Field label="新密码">
            <input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} autoComplete="new-password" />
          </Field>
          <Field label="再输入一次">
            <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />
          </Field>
          {err && <p className="error-text">{err}</p>}
          <div className="actions">
            <Button type="submit" variant="primary" loading={change.isPending} disabled={!oldPw || !newPw || !confirm}>
              修改密码
            </Button>
          </div>
        </form>
      </Panel>
      <InstallPushPanel />
      <CalendarPanel />
      <PrimaryBar>
        <Button full onClick={() => void logout().then(() => navigate('/login', { replace: true }))}>
          退出登录
        </Button>
      </PrimaryBar>
    </>
  )
}
