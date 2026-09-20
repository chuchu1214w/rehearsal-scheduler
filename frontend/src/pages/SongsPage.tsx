import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, App as AntApp, Button, Card, Form, Input, Modal, Popconfirm, Segmented, Select, Space, Spin, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api, errorMessage } from '../api/client'
import { DIFFICULTIES, type Difficulty, type EventMember, type RehearsalEvent, type Song, type SongList } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { PageHeader } from '../components/AppLayout'
import { parsePlan, planText } from '../utils'

const DIFF_COLORS: Record<Difficulty, string> = { 简单: 'green', 一般: 'gold', 困难: 'magenta' }

interface Values {
  code: string
  name: string
  difficulty: Difficulty
  member_ids: number[]
  session_plan: string
}

function nextCode(songs: Song[]): string {
  const used = new Set(songs.map((s) => s.code.toLowerCase()))
  for (let i = 0; i < 26; i++) {
    const c = String.fromCharCode(97 + i)
    if (!used.has(c)) return c
  }
  return `s${songs.length + 1}`
}

function SongFormModal({ ev, songs, members, initial, open, onClose }: { ev: RehearsalEvent; songs: Song[]; members: EventMember[]; initial?: Song; open: boolean; onClose: () => void }) {
  const [form] = Form.useForm<Values>()
  const qc = useQueryClient()
  const { message } = AntApp.useApp()
  const difficulty = Form.useWatch('difficulty', form)
  const planText_ = Form.useWatch('session_plan', form)

  useEffect(() => {
    if (open) {
      form.setFieldsValue(
        initial
          ? { code: initial.code, name: initial.name, difficulty: initial.difficulty, member_ids: initial.members.map((m) => m.id), session_plan: initial.session_plan?.join(',') ?? '' }
          : { code: nextCode(songs), name: '', difficulty: '简单', member_ids: [], session_plan: '' },
      )
    }
  }, [open, initial, songs, form])

  const mutation = useMutation({
    mutationFn: (v: Values) => {
      const plan = parsePlan(v.session_plan)
      const body = { code: v.code, name: v.name, difficulty: v.difficulty, member_ids: v.member_ids, session_plan: plan }
      return initial
        ? api<Song>(`/api/songs/${initial.id}`, { method: 'PATCH', json: { ...body, clear_session_plan: plan === null } })
        : api<Song>(`/api/events/${ev.id}/songs`, { method: 'POST', json: body })
    },
    onSuccess: () => {
      message.success('已保存')
      void qc.invalidateQueries({ queryKey: ['songs', ev.id] })
      void qc.invalidateQueries({ queryKey: ['event', ev.id] })
      onClose()
    },
    onError: (err) => message.error(errorMessage(err)),
  })

  const effective = useMemo(() => {
    const override = parsePlan(planText_ ?? '')
    if (override && override.every((x) => Number.isInteger(x) && x > 0)) return { plan: override, source: '曲目覆盖' }
    if (difficulty) return { plan: ev.settings.difficulty_templates[difficulty], source: `难度「${difficulty}」模板` }
    return null
  }, [planText_, difficulty, ev.settings])

  return (
    <Modal open={open} title={initial ? '编辑曲目' : '添加曲目'} onCancel={onClose} onOk={() => form.submit()} okText="保存" cancelText="取消" confirmLoading={mutation.isPending}>
      <Form<Values> form={form} layout="vertical" onFinish={(v) => mutation.mutate(v)} requiredMark={false}>
        <div style={{ display: 'grid', gridTemplateColumns: '90px 1fr', gap: 12 }}>
          <Form.Item name="code" label="代号" rules={[{ required: true, message: '必填' }]}>
            <Input maxLength={16} />
          </Form.Item>
          <Form.Item name="name" label="曲目名称" rules={[{ required: true, message: '请输入曲目名称' }]}>
            <Input maxLength={120} placeholder="例如 aespa - Drama" />
          </Form.Item>
        </div>
        <Form.Item name="difficulty" label="难度" rules={[{ required: true }]}>
          <Segmented options={DIFFICULTIES.map((d) => ({ value: d, label: `${d}(${planText(ev.settings.difficulty_templates[d])})` }))} block />
        </Form.Item>
        <Form.Item name="member_ids" label="参演成员" rules={[{ required: true, message: '至少选择一名成员' }]}>
          <Select
            mode="multiple"
            placeholder={members.length ? '选择参演成员' : '活动还没有参与成员,请先在活动页添加'}
            options={members.map((m) => ({ value: m.member_id, label: m.display_name }))}
            optionFilterProp="label"
          />
        </Form.Item>
        <Form.Item name="session_plan" label="场次方案(可选,覆盖难度模板)" rules={[{ pattern: /^\s*$|^\s*\d+(\s*[,，、]\s*\d+)*\s*$/, message: '用逗号分隔的小时数,如 3,2' }]}>
          <Input placeholder="留空则按难度模板;例如 3,2 表示 1 场 3 小时 + 1 场 2 小时" allowClear />
        </Form.Item>
        {effective && (
          <Alert type="info" showIcon message={<>本曲将安排 <b>{effective.plan.length}</b> 场:{planText(effective.plan)}<span className="rs-muted">(来源:{effective.source})</span></>} />
        )}
      </Form>
    </Modal>
  )
}

export function SongsPage() {
  const id = Number(useParams().id)
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const qc = useQueryClient()
  const { message } = AntApp.useApp()
  const ev = useQuery({ queryKey: ['event', id], queryFn: () => api<RehearsalEvent>(`/api/events/${id}`) })
  const songs = useQuery({ queryKey: ['songs', id], queryFn: () => api<SongList>(`/api/events/${id}/songs`) })
  const members = useQuery({ queryKey: ['event-members', id], queryFn: () => api<EventMember[]>(`/api/events/${id}/members`) })
  const [editing, setEditing] = useState<Song | 'new' | null>(null)

  const remove = useMutation({
    mutationFn: (songId: number) => api(`/api/songs/${songId}`, { method: 'DELETE' }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['songs', id] })
      void qc.invalidateQueries({ queryKey: ['event', id] })
    },
    onError: (err) => message.error(errorMessage(err)),
  })

  if (ev.isPending || songs.isPending || members.isPending) return <Spin />
  if (ev.isError) return <Alert type="error" showIcon message={errorMessage(ev.error)} />
  if (songs.isError) return <Alert type="error" showIcon message={errorMessage(songs.error)} />

  const columns: ColumnsType<Song> = [
    { title: '代号', dataIndex: 'code', width: 64, render: (c: string) => <b>{c}</b> },
    { title: '曲目', dataIndex: 'name', width: 180 },
    { title: '难度', dataIndex: 'difficulty', width: 80, render: (d: Difficulty) => <Tag color={DIFF_COLORS[d]}>{d}</Tag> },
    { title: '参演成员', dataIndex: 'members', width: 260, render: (ms: Song['members']) => <Space wrap size={[4, 4]}>{ms.map((m) => <Tag key={m.id} style={{ marginInlineEnd: 0 }}>{m.display_name}</Tag>)}</Space> },
    { title: '场次方案', dataIndex: 'durations', width: 170, render: (d: number[], row) => <span style={{ whiteSpace: 'nowrap' }}>{planText(d)} {row.session_plan && <Tag color="purple">覆盖</Tag>}</span> },
    { title: '场次', dataIndex: 'session_count', width: 64 },
  ]
  if (isAdmin) {
    columns.push({
      title: '',
      key: 'actions',
      width: 120,
      render: (_v, row) => (
        <Space size={0}>
          <Button type="link" size="small" onClick={() => setEditing(row)}>编辑</Button>
          <Popconfirm title={`删除曲目「${row.name}」?`} okText="删除" cancelText="取消" okButtonProps={{ danger: true }} onConfirm={() => remove.mutate(row.id)}>
            <Button type="link" size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    })
  }

  return (
    <>
      <Link to={`/events/${id}`} className="rs-back">← {ev.data.name}</Link>
      <PageHeader
        title="曲目"
        subtitle={`共 ${songs.data.songs.length} 首 · ${songs.data.total_sessions} 场正规排练`}
        extra={isAdmin && <Button type="primary" onClick={() => setEditing('new')} disabled={(members.data ?? []).length === 0}>+ 添加曲目</Button>}
      />
      {isAdmin && (members.data ?? []).length === 0 && <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="活动还没有参与成员" description={<>请先在 <Link to={`/events/${id}`}>活动页</Link> 添加参与成员,再录入曲目。</>} />}
      {songs.data.warnings.map((w) => <Alert key={w} type="warning" showIcon message={w} style={{ marginBottom: 12 }} />)}
      <Card styles={{ body: { padding: 0 } }}>
        <Table<Song> rowKey="id" columns={columns} dataSource={songs.data.songs} pagination={false} scroll={{ x: true }} locale={{ emptyText: isAdmin ? '还没有曲目' : '尚未录入曲目' }} />
      </Card>
      {isAdmin && (
        <SongFormModal ev={ev.data} songs={songs.data.songs} members={members.data ?? []} initial={editing && editing !== 'new' ? editing : undefined} open={editing !== null} onClose={() => setEditing(null)} />
      )}
    </>
  )
}
