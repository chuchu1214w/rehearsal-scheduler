import { useMutation, useQueryClient } from '@tanstack/react-query'
import { App as AntApp, Button, Form, Input } from 'antd'
import { useNavigate } from 'react-router-dom'

import { api, errorMessage } from '../api/client'
import type { User } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { AuthShell } from '../components/AuthShell'
import { USERNAME_PATTERN } from '../utils'

interface Values {
  username: string
  password: string
  confirm: string
}

export function SetupPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { setUser } = useAuth()
  const { message } = AntApp.useApp()
  const mutation = useMutation({
    mutationFn: (v: Values) => api<User>('/api/setup', { method: 'POST', json: { username: v.username, password: v.password } }),
    onSuccess: async (user) => {
      setUser(user)
      await qc.invalidateQueries({ queryKey: ['setup-status'] })
      message.success('管理员账号已创建')
      navigate('/', { replace: true })
    },
    onError: (err) => message.error(errorMessage(err)),
  })

  return (
    <AuthShell title="首次设置" subtitle="创建第一个管理员账号。这个入口只会出现一次。">
      <Form<Values> layout="vertical" onFinish={(v) => mutation.mutate(v)} requiredMark={false}>
        <Form.Item
          name="username"
          label="管理员用户名"
          rules={[
            { required: true, message: '请输入用户名' },
            { pattern: USERNAME_PATTERN, message: '2–32 位,可用中英文、数字、_ . -' },
          ]}
        >
          <Input autoComplete="username" placeholder="例如 captain" />
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
          创建并进入
        </Button>
      </Form>
    </AuthShell>
  )
}
