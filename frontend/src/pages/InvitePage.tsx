import { useMutation, useQuery } from '@tanstack/react-query'
import { Alert, App as AntApp, Button, Form, Input, Spin } from 'antd'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { api, errorMessage } from '../api/client'
import type { InviteInfo, User } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { AuthShell } from '../components/AuthShell'
import { fmtDateTime, USERNAME_PATTERN } from '../utils'

interface Values {
  username: string
  password: string
  confirm: string
}

export function InvitePage() {
  const { token = '' } = useParams()
  const navigate = useNavigate()
  const { setUser } = useAuth()
  const { message } = AntApp.useApp()
  const info = useQuery({ queryKey: ['invite', token], queryFn: () => api<InviteInfo>(`/api/invites/${token}`), retry: false })
  const mutation = useMutation({
    mutationFn: (v: Values) =>
      api<User>(`/api/invites/${token}/accept`, { method: 'POST', json: { username: v.username, password: v.password } }),
    onSuccess: (u) => {
      setUser(u)
      message.success(`欢迎,${u.member_name ?? u.username}!`)
      navigate('/', { replace: true })
    },
    onError: (err) => message.error(errorMessage(err)),
  })

  if (info.isPending) {
    return (
      <AuthShell title="邀请">
        <Spin />
      </AuthShell>
    )
  }
  if (info.isError) {
    return (
      <AuthShell title="邀请无效">
        <Alert type="error" showIcon message={errorMessage(info.error)} description="请联系管理员重新生成邀请链接。" />
        <p style={{ textAlign: 'center', marginTop: 16 }}>
          <Link to="/login">已有账号?去登录</Link>
        </p>
      </AuthShell>
    )
  }

  return (
    <AuthShell
      title={`你好,${info.data.member_name}`}
      subtitle={
        <>
          设置你的登录账号。链接有效期至 {fmtDateTime(info.data.expires_at)}。
        </>
      }
    >
      <Form<Values> layout="vertical" onFinish={(v) => mutation.mutate(v)} requiredMark={false}>
        <Form.Item
          name="username"
          label="用户名"
          rules={[
            { required: true, message: '请输入用户名' },
            { pattern: USERNAME_PATTERN, message: '2–32 位,可用中英文、数字、_ . -' },
          ]}
        >
          <Input autoComplete="username" />
        </Form.Item>
        <Form.Item name="password" label="密码" rules={[{ required: true, min: 8, message: '至少 8 位' }]}>
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Form.Item
          name="confirm"
          label="确认密码"
          dependencies={['password']}
          rules={[
            { required: true, message: '请再输入一次' },
            ({ getFieldValue }) => ({
              validator: (_rule, value) =>
                !value || value === getFieldValue('password') ? Promise.resolve() : Promise.reject(new Error('两次输入不一致')),
            }),
          ]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Button type="primary" htmlType="submit" block size="large" loading={mutation.isPending}>
          加入
        </Button>
      </Form>
    </AuthShell>
  )
}
