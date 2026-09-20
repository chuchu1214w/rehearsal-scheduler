import dayjs from 'dayjs'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { useEvents } from '../../api/hooks'
import type { RehearsalEvent } from '../../api/types'
import { Badge, Empty, Heading, LinkButton, Spinner } from '../../ui'
import { daysUntilText, fmtMd } from '../../utils'

function stepText(ev: RehearsalEvent): string {
  const step = ev.steps.find((s) => s.no === ev.current_step)
  if (!step) return ''
  const names: Record<string, string> = { info: '演出信息', members: '添加人员', songs: '录曲目', rules: '特殊要求', availability: '等填报', solve: '排程', schedule: '排练表' }
  return `第 ${'①②③④⑤⑥⑦'[step.no - 1]} 步:${names[step.key] ?? step.label} · ${step.summary}`
}

function EventCard({ ev }: { ev: RehearsalEvent }) {
  const past = dayjs(ev.performance_date).isBefore(dayjs().startOf('day'))
  return (
    <Link to={`/events/${ev.id}`} className="event-card">
      <div className="section" style={{ marginBottom: 4 }}>
        <h3>{ev.name}</h3>
        <Badge tone={past || ev.status === 'closed' ? 'neutral' : 'green'}>{past ? '已结束' : daysUntilText(ev.days_until_performance)}</Badge>
      </div>
      <div className="event-card__meta">
        演出 {fmtMd(ev.performance_date)} · 正规排练 {fmtMd(ev.formal_start_date)}–{fmtMd(ev.formal_end_date)}({ev.formal_day_count} 天)· 全员评估 {fmtMd(ev.eval_date)}
        <br />
        {ev.member_count} 人 · {ev.song_count} 首 · {ev.session_count} 场
      </div>
      <div className="event-card__step">
        <span className="badge">{ev.current_step}/7</span>
        <span>{stepText(ev)}</span>
      </div>
    </Link>
  )
}

export function EventsPage() {
  const events = useEvents()
  const [showPast, setShowPast] = useState(false)
  if (events.isPending) return <Spinner />
  const all = events.data ?? []
  const today = dayjs().startOf('day')
  const active = all.filter((e) => e.status !== 'closed' && !dayjs(e.performance_date).isBefore(today))
  const past = all.filter((e) => !active.includes(e))

  if (all.length === 0) {
    return <Empty title="创建你的第一场演出" text="录好人员、曲目和要求,就可以开始收集空闲时间。" action={<LinkButton to="/events/new" variant="primary">新建演出</LinkButton>} />
  }
  return (
    <>
      <Heading title="演出" subtitle="每场演出一个工作台;点进去按七步推进。" action={<LinkButton to="/events/new" variant="primary">＋ 新建演出</LinkButton>} />
      <div className="event-grid">
        {active.map((ev) => (
          <EventCard key={ev.id} ev={ev} />
        ))}
      </div>
      {active.length === 0 && <p className="muted">没有进行中的演出。</p>}
      {past.length > 0 && (
        <details open={showPast} onToggle={(e) => setShowPast((e.target as HTMLDetailsElement).open)}>
          <summary>往期演出 · {past.length} 场</summary>
          <div className="event-grid">
            {past.map((ev) => (
              <EventCard key={ev.id} ev={ev} />
            ))}
          </div>
        </details>
      )}
    </>
  )
}
