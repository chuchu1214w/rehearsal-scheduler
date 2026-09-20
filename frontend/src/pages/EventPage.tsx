import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, App as AntApp, Button, Card, Col, DatePicker, Descriptions, Form, Input, Modal, Popconfirm, Row, Select, Space, Spin, Tag } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { api, errorMessage } from '../api/client'
import { DIFFICULTIES, STATUS_LABELS, type EventMember, type EventStatus, type Member, type RehearsalEvent, type SongList } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { PageHeader } from '../components/AppLayout'
import { EventFormModal } from '../components/EventFormModal'
import { fmtDate, hourLabel, planText } from '../utils'

function useEvent(id: number) {
  return useQuery({ queryKey: ['event', id], queryFn: () => api<RehearsalEvent>(`/api/events/${id}`) })
}

function ParticipantsCard({ ev, isAdmin }: { ev: RehearsalEvent; isAdmin: boolean }) {
  const qc = useQueryClient()
  const { message } = AntApp.useApp()
  const participants = useQuery({ queryKey: ['event-members', ev.id], queryFn: () => api<EventMember[]>(`/api/events/${ev.id}/members`) })
  const roster = useQuery({ queryKey: ['members'], queryFn: () => api<Member[]>('/api/members'), enabled: isAdmin })
  const [selected, setSelected] = useState<number[] | null>(null)
  const current = useMemo(() => (participants.data ?? []).map((p) => p.member_id), [participants.data])
  const value = selected ?? current
  const dirty = selected !== null && (selected.length !== current.length || selected.some((id) => !current.includes(id)))

  const save = useMutation({
    mutationFn: (member_ids: number[]) => api<EventMember[]>(`/api/events/${ev.id}/members`, { method: 'PUT', json: { member_ids } }),
    onSuccess: () => {
      message.success('参与成员已更新')
      setSelected(null)
      void qc.invalidateQueries({ queryKey: ['event-members', ev.id] })
      void qc.invalidateQueries({ queryKey: ['event', ev.id] })
    },
    onError: (err) => message.error(errorMessage(err)),
  })

  const options = (roster.data ?? [])
    .filter((m) => m.active || current.includes(m.id))
    .map((m) => ({ value: m.id, label: m.display_name + (m.active ? '' : '(已停用)') }))

  return (
    <Card title={`参与成员(${current.length})`} extra={isAdmin && <Link to="/roster">管理名册</Link>}>
      {participants.isPending ? (
        <Spin />
      ) : (
        <>
          {!isAdmin && (
            <Space wrap>
              {(participants.data ?? []).map((p) => (
                <Tag key={p.member_id}>{p.display_name}</Tag>
              ))}
              {participants.data?.length === 0 && <span className="rs-muted">尚未添加成员</span>}
            </Space>
          )}
          {isAdmin && (
            <>
              <Select
                mode="multiple"
                style={{ width: '100%' }}
                placeholder={roster.data?.length ? '从名册中选择参加本活动的成员' : '名册为空,请先到「名册」添加成员'}
                options={options}
                value={value}
                onChange={(ids) => setSelected(ids)}
                optionFilterProp="label"
                maxTagCount="responsive"
              />
              <Space style={{ marginTop: 12 }}>
                <Button type="primary" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate(value)}>
                  保存
                </Button>
                {dirty && <Button onClick={() => setSelected(null)}>还原</Button>}
                <span className="rs-muted">未参与的成员不会出现在填报与求解中</span>
              </Space>
            </>
          )}
        </>
      )}
    </Card>
  )
}

function CloneModal({ ev, open, onClose }: { ev: RehearsalEvent; open: boolean; onClose: () => void }) {
  const [form] = Form.useForm<{ name: string; performance_date: Dayjs; formal_start_date: Dayjs }>()
  const { message } = AntApp.useApp()
  const qc = useQueryClient()
  const navigate = useNavigate()
  useEffect(() => {
    if (open) form.setFieldsValue({ name: `${ev.name}(副本)`, performance_date: dayjs(ev.performance_date).add(3, 'month'), formal_start_date: dayjs(ev.formal_start_date).add(3, 'month') })
  }, [open, ev, form])
  const mutation = useMutation({
    mutationFn: (v: { name: string; performance_date: Dayjs; formal_start_date: Dayjs }) =>
      api<RehearsalEvent>(`/api/events/${ev.id}/clone`, {
        method: 'POST',
        json: { name: v.name, performance_date: v.performance_date.format('YYYY-MM-DD'), formal_start_date: v.formal_start_date.format('YYYY-MM-DD') },
      }),
    onSuccess: (created) => {
      message.success('已复制活动(名册、曲目、规则),空闲数据与排练表不会复制')
      void qc.invalidateQueries({ queryKey: ['events'] })
      onClose()
      navigate(`/events/${created.id}`)
    },
    onError: (err) => message.error(errorMessage(err)),
  })
  return (
    <Modal open={open} title="复制活动" onCancel={onClose} onOk={() => form.submit()} okText="复制" cancelText="取消" confirmLoading={mutation.isPending}>
      <Form form={form} layout="vertical" onFinish={(v) => mutation.mutate(v)} requiredMark={false}>
        <Form.Item name="name" label="新活动名称" rules={[{ required: true, message: '请输入名称' }]}>
          <Input />
        </Form.Item>
        <Form.Item name="performance_date" label="演出日期" rules={[{ required: true, message: '请选择' }]}>
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="formal_start_date" label="排练开始日期" rules={[{ required: true, message: '请选择' }]}>
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>
      </Form>
    </Modal>
  )
}

export function EventPage() {
  const id = Number(useParams().id)
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const ev = useEvent(id)
  const songs = useQuery({ queryKey: ['songs', id], queryFn: () => api<SongList>(`/api/events/${id}/songs`) })
  const [editing, setEditing] = useState(false)
  const [cloning, setCloning] = useState(false)

  const remove = useMutation({
    mutationFn: () => api(`/api/events/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      message.success('活动已删除')
      void qc.invalidateQueries({ queryKey: ['events'] })
      navigate('/')
    },
    onError: (err) => message.error(errorMessage(err)),
  })
  const setStatus = useMutation({
    mutationFn: (status: EventStatus) => api<RehearsalEvent>(`/api/events/${id}`, { method: 'PATCH', json: { status } }),
    onSuccess: (updated) => {
      qc.setQueryData(['event', id], updated)
      void qc.invalidateQueries({ queryKey: ['events'] })
    },
    onError: (err) => message.error(errorMessage(err)),
  })

  if (ev.isPending) return <Spin />
  if (ev.isError) return <Alert type="error" showIcon message={errorMessage(ev.error)} action={<Link to="/">返回活动列表</Link>} />
  const e = ev.data
  const s = e.settings

  return (
    <>
      <Link to="/" className="rs-back">
        ← 活动列表
      </Link>
      <PageHeader
        title={e.name}
        subtitle={`演出 ${fmtDate(e.performance_date)}`}
        extra={
          isAdmin && (
            <Space wrap>
              <Select<EventStatus>
                value={e.status}
                onChange={(v) => setStatus.mutate(v)}
                options={(Object.keys(STATUS_LABELS) as EventStatus[]).map((k) => ({ value: k, label: STATUS_LABELS[k] }))}
                style={{ width: 120 }}
              />
              <Button onClick={() => setEditing(true)}>编辑</Button>
              <Button onClick={() => setCloning(true)}>复制</Button>
              <Popconfirm title="删除这个活动?" description="曲目、参与成员等数据都会一起删除,无法恢复。" okText="删除" cancelText="取消" okButtonProps={{ danger: true }} onConfirm={() => remove.mutate()}>
                <Button danger>删除</Button>
              </Popconfirm>
            </Space>
          )
        }
      />
      <Row gutter={[16, 16]}>
        <Col xs={24} md={12}>
          <Card title="关键日期">
            <Descriptions column={1} size="small" items={[
              { key: 'perf', label: '演出日期', children: <b>{fmtDate(e.performance_date)}</b> },
              { key: 'formal', label: '正规排练区间', children: `${fmtDate(e.formal_start_date)} ~ ${fmtDate(e.formal_end_date)}(${e.formal_day_count} 天)` },
              { key: 'eval', label: '全员评估日', children: <>{fmtDate(e.eval_date)} <span className="rs-muted">演出前一天,只排一场全员评估</span></> },
              { key: 'window', label: '每日排练窗口', children: `${hourLabel(e.day_start_hour)} – ${hourLabel(e.day_end_hour)}(${e.slots_per_day} 格)` },
              { key: 'tz', label: '时区', children: e.timezone },
            ]} />
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card title="曲目" extra={<Link to={`/events/${e.id}/songs`}>{isAdmin ? '管理曲目 →' : '查看 →'}</Link>}>
            <div className="rs-stat">{e.song_count} 首 · {e.session_count} 场正规排练</div>
            {songs.data && songs.data.songs.length > 0 && (
              <Space wrap style={{ marginTop: 8 }}>
                {songs.data.songs.map((song) => (
                  <Tag key={song.id}>{song.code} {song.name}</Tag>
                ))}
              </Space>
            )}
            {songs.data?.warnings.map((w) => <Alert key={w} type="warning" showIcon message={w} style={{ marginTop: 8 }} />)}
            {songs.data && songs.data.songs.length === 0 && <div className="rs-muted" style={{ marginTop: 8 }}>{isAdmin ? '还没有曲目,去「管理曲目」添加' : '尚未录入曲目'}</div>}
          </Card>
        </Col>
        <Col xs={24}>
          <ParticipantsCard ev={e} isAdmin={!!isAdmin} />
        </Col>
        <Col xs={24}>
          <Card title="规则参数" extra={isAdmin && <a onClick={() => setEditing(true)}>修改</a>}>
            <Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }} items={[
              { key: 'limit', label: '单日软 / 硬上限', children: `${s.soft_daily_limit}h / ${s.hard_daily_limit}h` },
              { key: 'gap', label: '往返合并 / 免罚空档', children: `${s.merge_visit_gap}h / ${s.free_gap}h` },
              { key: 'eval', label: '评估场时长', children: `${s.eval_durations.map((h) => `${h}h`).join(' 或 ')},每人至少连续 ${s.eval_min_contiguous}h` },
              { key: 'same', label: '同曲不同天', children: s.same_song_different_days ? '是(硬约束)' : '否' },
              ...DIFFICULTIES.map((d) => ({ key: d, label: `难度「${d}」`, children: planText(s.difficulty_templates[d]) })),
            ]} />
          </Card>
        </Col>
        <Col xs={24}>
          <Card title="下一步">
            <div className="rs-muted">成员填报空闲时间、求解与排练表将在后续版本开放(M2–M4)。当前可先完善名册、参与成员与曲目。</div>
          </Card>
        </Col>
      </Row>
      {isAdmin && (
        <>
          <EventFormModal open={editing} initial={e} onClose={() => setEditing(false)} onSaved={(updated) => { setEditing(false); qc.setQueryData(['event', id], updated); void qc.invalidateQueries({ queryKey: ['events'] }); void qc.invalidateQueries({ queryKey: ['songs', id] }) }} />
          <CloneModal ev={e} open={cloning} onClose={() => setCloning(false)} />
        </>
      )}
    </>
  )
}
