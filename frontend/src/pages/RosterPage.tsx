import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, App as AntApp, Button, Card, Form, Input, Modal, Popconfirm, Select, Space, Spin, Switch, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useEffect, useState } from 'react'

import { api, errorMessage } from '../api/client'
import type { Account, Invite, Member } from '../api/types'
import { PageHeader } from '../components/AppLayout'
import { fmtDateTime } from '../utils'

interface Values {
  display_name: string
  aliases: string[]
  note: string
  active: boolean
}

function MemberFormModal({ initial, open, onClose }: { initial?: Member; open: boolean; onClose: () => void }) {
  const [form] = Form.useForm<Values>()
  const qc = useQueryClient()
  const { message } = AntApp.useApp()
  useEffect(() => {
    if (open) form.setFieldsValue(initial ? { display_name: initial.display_name, aliases: initial.aliases, note: initial.note, active: initial.active } : { display_name: '', aliases: [], note: '', active: true })
  }, [open, initial, form])
  const mutation = useMutation({
    mutationFn: (v: Values) => (initial ? api<Member>(`/api/members/${initial.id}`, { method: 'PATCH', json: v }) : api<Member>('/api/members', { method: 'POST', json: v })),
    onSuccess: () => {
      message.success('已保存')
      void qc.invalidateQueries({ queryKey: ['members'] })
      onClose()
    },
    onError: (err) => message.error(errorMessage(err)),
  })
  return (
    <Modal open={open} title={initial ? '编辑成员' : '添加成员'} onCancel={onClose} onOk={() => form.submit()} okText="保存" cancelText="取消" confirmLoading={mutation.isPending}>
      <Form<Values> form={form} layout="vertical" onFinish={(v) => mutation.mutate(v)} requiredMark={false}>
        <Form.Item name="display_name" label="昵称" rules={[{ required: true, message: '请输入昵称' }]}>
          <Input maxLength={64} placeholder="排练表里显示的名字" />
        </Form.Item>
        <Form.Item name="aliases" label="别名(可选)" tooltip="录入曲目时可用别名匹配,如 ash → Ash">
          <Select mode="tags" tokenSeparators={[',', '，', ' ']} placeholder="输入后按回车" open={false} />
        </Form.Item>
        <Form.Item name="note" label="备注(可选)">
          <Input maxLength={500} placeholder="例如 住得远、周三有课" />
        </Form.Item>
        <Form.Item name="active" label="启用" valuePropName="checked">
          <Switch />
        </Form.Item>
      </Form>
    </Modal>
  )
}

export function RosterPage() {
  const qc = useQueryClient()
  const { message } = AntApp.useApp()
  const members = useQuery({ queryKey: ['members'], queryFn: () => api<Member[]>('/api/members') })
  const [editing, setEditing] = useState<Member | 'new' | null>(null)
  const [invite, setInvite] = useState<{ member: Member; invite: Invite } | null>(null)
  const [temp, setTemp] = useState<{ member: Member; username: string; temp_password: string } | null>(null)

  const refresh = () => void qc.invalidateQueries({ queryKey: ['members'] })
  const onError = (err: unknown) => message.error(errorMessage(err))
  const toggleActive = useMutation({ mutationFn: (m: Member) => api<Member>(`/api/members/${m.id}`, { method: 'PATCH', json: { active: !m.active } }), onSuccess: refresh, onError })
  const remove = useMutation({ mutationFn: (m: Member) => api(`/api/members/${m.id}`, { method: 'DELETE' }), onSuccess: refresh, onError })
  const createInvite = useMutation({
    mutationFn: (m: Member) => api<Invite>(`/api/members/${m.id}/invite`, { method: 'POST' }).then((inv) => ({ member: m, invite: inv })),
    onSuccess: (data) => setInvite(data),
    onError,
  })
  const resetPassword = useMutation({
    mutationFn: (m: Member) => api<{ username: string; temp_password: string }>(`/api/members/${m.id}/reset-password`, { method: 'POST' }).then((r) => ({ member: m, ...r })),
    onSuccess: (data) => setTemp(data),
    onError,
  })
  const toggleAccount = useMutation({
    mutationFn: (m: Member) => api<Account>(`/api/members/${m.id}/account`, { method: 'PATCH', json: { is_active: !m.account?.is_active } }),
    onSuccess: refresh,
    onError,
  })

  const columns: ColumnsType<Member> = [
    {
      title: '昵称',
      dataIndex: 'display_name',
      width: 120,
      render: (name: string, m) => (
        <>
          <b style={{ opacity: m.active ? 1 : 0.5 }}>{name}</b>
          {m.note && <div className="rs-muted" style={{ fontSize: 12 }}>{m.note}</div>}
        </>
      ),
    },
    { title: '别名', dataIndex: 'aliases', width: 140, render: (a: string[]) => <Space wrap size={[4, 4]}>{a.map((x) => <Tag key={x} style={{ marginInlineEnd: 0 }}>{x}</Tag>)}</Space> },
    { title: '启用', dataIndex: 'active', width: 70, render: (_a, m) => <Switch size="small" checked={m.active} onChange={() => toggleActive.mutate(m)} /> },
    {
      title: '账号',
      key: 'account',
      render: (_v, m) =>
        m.account ? (
          <Space wrap size={[4, 4]}>
            <span>{m.account.username}</span>
            {m.account.is_active ? <Tag color="green">正常</Tag> : <Tag>已停用</Tag>}
            <Button type="link" size="small" onClick={() => resetPassword.mutate(m)}>重置密码</Button>
            <Button type="link" size="small" onClick={() => toggleAccount.mutate(m)}>{m.account.is_active ? '停用账号' : '启用账号'}</Button>
          </Space>
        ) : (
          <Button size="small" onClick={() => createInvite.mutate(m)} disabled={!m.active} loading={createInvite.isPending && createInvite.variables?.id === m.id}>
            生成邀请链接
          </Button>
        ),
    },
    {
      title: '',
      key: 'actions',
      width: 110,
      render: (_v, m) => (
        <Space size={0}>
          <Button type="link" size="small" onClick={() => setEditing(m)}>编辑</Button>
          <Popconfirm title={`删除成员「${m.display_name}」?`} description="已参加活动或已有账号的成员无法删除,请改为停用。" okText="删除" cancelText="取消" okButtonProps={{ danger: true }} onConfirm={() => remove.mutate(m)}>
            <Button type="link" size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <>
      <PageHeader title="名册" subtitle="舞团全部成员,可跨活动沿用。成员通过邀请链接创建自己的登录账号。" extra={<Button type="primary" onClick={() => setEditing('new')}>+ 添加成员</Button>} />
      {members.isPending ? (
        <Spin />
      ) : (
        <Card styles={{ body: { padding: 0 } }}>
          <Table<Member> rowKey="id" columns={columns} dataSource={members.data ?? []} pagination={false} scroll={{ x: true }} locale={{ emptyText: '名册为空,点右上角添加成员' }} />
        </Card>
      )}
      <MemberFormModal open={editing !== null} initial={editing && editing !== 'new' ? editing : undefined} onClose={() => setEditing(null)} />
      <Modal open={invite !== null} title={`邀请 ${invite?.member.display_name}`} onCancel={() => setInvite(null)} footer={<Button type="primary" onClick={() => setInvite(null)}>完成</Button>}>
        {invite && (
          <>
            <p>把下面的链接发给 {invite.member.display_name},打开后设置用户名和密码即可登录。链接只能使用一次,有效期至 {fmtDateTime(invite.invite.expires_at)}。</p>
            <Typography.Paragraph copyable={{ text: invite.invite.url, tooltips: ['复制', '已复制'] }} className="rs-code">
              {invite.invite.url}
            </Typography.Paragraph>
            <Alert type="info" showIcon message="关闭后无法再次查看这个链接;需要时可重新生成,旧链接会作废。" />
          </>
        )}
      </Modal>
      <Modal open={temp !== null} title={`已重置 ${temp?.member.display_name} 的密码`} onCancel={() => setTemp(null)} footer={<Button type="primary" onClick={() => setTemp(null)}>完成</Button>}>
        {temp && (
          <>
            <p>用户名 <b>{temp.username}</b>,临时密码:</p>
            <Typography.Paragraph copyable={{ text: temp.temp_password, tooltips: ['复制', '已复制'] }} className="rs-code" style={{ fontSize: 20 }}>
              {temp.temp_password}
            </Typography.Paragraph>
            <Alert type="info" showIcon message="该成员在其他设备上的登录已全部失效。请提醒 TA 登录后在「账号」页修改密码。" />
          </>
        )}
      </Modal>
    </>
  )
}
