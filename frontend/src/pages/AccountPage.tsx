import { useMutation } from '@tanstack/react-query'
import { App as AntApp, Button, Card, Col, Descriptions, Form, Input, Row } from 'antd'
import { useNavigate } from 'react-router-dom'

import { api, errorMessage } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { PageHeader } from '../components/AppLayout'
import { fmtDateTime } from '../utils'

interface Values {
  old_password: string
  new_password: string
  confirm: string
}

export function AccountPage() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const [form] = Form.useForm<Values>()
  const change = useMutation({
    mutationFn: (v: Values) => api('/api/me/password', { method: 'POST', json: { old_password: v.old_password, new_password: v.new_password } }),
    onSuccess: () => {
      message.success('密码已修改;其他设备需要重新登录')
      form.resetFields()
    },
    onError: (err) => message.error(errorMessage(err)),
  })
  if (!user) return null

  return (
    <>
      <PageHeader title="账号" />
      <Row gutter={[16, 16]}>
        <Col xs={24} md={12}>
          <Card title="我的信息">
            <Descriptions column={1} size="small" items={[
              { key: 'u', label: '用户名', children: user.username },
              { key: 'r', label: '角色', children: user.role === 'admin' ? '管理员' : '成员' },
              { key: 'm', label: '名册身份', children: user.member_name ?? '(未绑定)' },
              { key: 'l', label: '上次登录', children: fmtDateTime(user.last_login_at) },
            ]} />
            <Button style={{ marginTop: 16 }} onClick={async () => { await logout(); navigate('/login', { replace: true }) }}>
              退出登录
            </Button>
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card title="修改密码">
            <Form<Values> form={form} layout="vertical" onFinish={(v) => change.mutate(v)} requiredMark={false}>
              <Form.Item name="old_password" label="旧密码" rules={[{ required: true, message: '请输入旧密码' }]}>
                <Input.Password autoComplete="current-password" />
              </Form.Item>
              <Form.Item name="new_password" label="新密码" rules={[{ required: true, min: 8, message: '至少 8 位' }]}>
                <Input.Password autoComplete="new-password" />
              </Form.Item>
              <Form.Item
                name="confirm"
                label="确认新密码"
                dependencies={['new_password']}
                rules={[
                  { required: true, message: '请再输入一次' },
                  ({ getFieldValue }) => ({
                    validator: (_rule, value) => (!value || value === getFieldValue('new_password') ? Promise.resolve() : Promise.reject(new Error('两次输入不一致'))),
                  }),
                ]}
              >
                <Input.Password autoComplete="new-password" />
              </Form.Item>
              <Button type="primary" htmlType="submit" loading={change.isPending}>
                修改密码
              </Button>
            </Form>
          </Card>
        </Col>
      </Row>
    </>
  )
}
