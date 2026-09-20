import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Card, Col, Empty, Row, Spin, Tag } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import { STATUS_LABELS, type RehearsalEvent } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { PageHeader } from '../components/AppLayout'
import { EventFormModal } from '../components/EventFormModal'
import { fmtDate } from '../utils'

const STATUS_COLORS: Record<string, string> = {
  preparing: 'default',
  collecting: 'gold',
  scheduling: 'blue',
  published: 'green',
  closed: 'default',
}

export function EventCard({ ev }: { ev: RehearsalEvent }) {
  const navigate = useNavigate()
  return (
    <Card
      hoverable
      title={ev.name}
      extra={<Tag color={STATUS_COLORS[ev.status]}>{STATUS_LABELS[ev.status]}</Tag>}
      onClick={() => navigate(`/events/${ev.id}`)}
    >
      <div className="rs-stat">演出 {fmtDate(ev.performance_date)}</div>
      <div style={{ marginTop: 6 }}>
        正规排练 {fmtDate(ev.formal_start_date)} ~ {fmtDate(ev.formal_end_date)}({ev.formal_day_count} 天)
      </div>
      <div>全员评估 {fmtDate(ev.eval_date)}</div>
      <div className="rs-muted" style={{ marginTop: 8 }}>
        成员 {ev.member_count} · 曲目 {ev.song_count} · 场次 {ev.session_count}
      </div>
    </Card>
  )
}

export function EventsPage() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const events = useQuery({ queryKey: ['events'], queryFn: () => api<RehearsalEvent[]>('/api/events') })
  const isAdmin = user?.role === 'admin'

  return (
    <>
      <PageHeader
        title="活动"
        subtitle={isAdmin ? '每场演出一个活动:名册、曲目、规则、排练表都归在活动里' : '你参加的活动'}
        extra={isAdmin && <Button type="primary" onClick={() => setOpen(true)}>+ 新建活动</Button>}
      />
      {events.isPending ? (
        <Spin />
      ) : !events.data || events.data.length === 0 ? (
        <Card>
          <Empty
            image={<div className="rs-empty-star">✦</div>}
            description={isAdmin ? '还没有活动,先新建一个吧' : '你还没有被加入任何活动,请联系管理员'}
          >
            {isAdmin && (
              <Button type="primary" onClick={() => setOpen(true)}>
                新建活动
              </Button>
            )}
          </Empty>
        </Card>
      ) : (
        <Row gutter={[16, 16]}>
          {events.data.map((ev) => (
            <Col xs={24} md={12} key={ev.id}>
              <EventCard ev={ev} />
            </Col>
          ))}
        </Row>
      )}
      <EventFormModal
        open={open}
        onClose={() => setOpen(false)}
        onSaved={(ev) => {
          setOpen(false)
          void qc.invalidateQueries({ queryKey: ['events'] })
          navigate(`/events/${ev.id}`)
        }}
      />
    </>
  )
}
