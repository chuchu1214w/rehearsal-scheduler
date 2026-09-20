import { useMutation } from '@tanstack/react-query'
import { App as AntApp, Button, Form, Input } from 'antd'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { api, errorMessage } from '../api/client'
import type { User } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { AuthShell } from '../components/AuthShell'

interface Values {
  username: string
  password: string
}

export function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, setUser } = useAuth()
  const { message } = AntApp.useApp()
  const from = (location.state as { from?: string } | null)?.from ?? '/'
  const mutation = useMutation({
    mutationFn: (v: Values) => api<User>('/api/auth/login', { method: 'POST', json: v }),
    onSuccess: (u) => {
      setUser(u)
      navigate(from, { replace: true })
    },
    onError: (err) => message.error(errorMessage(err)),
  })
  if (user) return <Navigate to="/" replace />

  return (
    <AuthShell title="登录" subtitle="还没有账号?请向管理员索取邀请链接。">
      <Form<Values> layout="vertical" onFinish={(v) => mutation.mutate(v)} requiredMark={false}>
        <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}>
          <Input autoComplete="username" autoFocus />
        </Form.Item>
        <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        <Button type="primary" htmlType="submit" block size="large" loading={mutation.isPending}>
          登录
        </Button>
      </Form>
    </AuthShell>
  )
}
