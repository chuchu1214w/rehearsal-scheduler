import { useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { useAvailability, useEvents, usePublishedSchedule } from '../../api/hooks'
import type { PublishedSchedule, RehearsalEvent } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import { CalendarPanel } from '../../components/CalendarPanel'
import { DayView, SessionsByDate, WeekView, sessionsForMember } from '../../components/ScheduleViews'
import { pickCurrentEvent } from '../../layout/currentEvent'
import { Back, Badge, Empty, LinkButton, Panel, PrimaryBar, Spinner, Tabs } from '../../ui'
import { fmtMd, weekdayShort } from '../../utils'

type Scope = 'mine' | 'all'

function ScopeToggle({ value, onChange }: { value: Scope; onChange: (s: Scope) => void }) {
  return (
    <div className="toggle" role="group" aria-label="查看范围">
      <button type="button" aria-pressed={value === 'mine'} onClick={() => onChange('mine')}>
        我的时间表
      </button>
      <button type="button" aria-pressed={value === 'all'} onClick={() => onChange('all')}>
        全体成员
      </button>
    </div>
  )
}

export function MemberSchedulePage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [view, setView] = useState<'week' | 'list'>('week')
  const events = useEvents()
  const eventParam = params.get('event') ? Number(params.get('event')) : null
  const current = pickCurrentEvent(events.data ?? [], eventParam)
  const avail = useAvailability(current?.id ?? NaN, user?.member_id ?? NaN)
  const pub = usePublishedSchedule(current?.id ?? NaN)
  const scope: Scope = params.get('scope') === 'all' ? 'all' : 'mine'
  const update = (next: { scope?: Scope; event?: number | null }) => {
    const q: Record<string, string> = {}
    const s = next.scope ?? scope
    const ev = next.event === undefined ? eventParam : next.event
    if (s === 'all') q.scope = 'all'
    if (ev != null) q.event = String(ev)
    setParams(q, { replace: true })
  }
  const setScope = (s: Scope) => update({ scope: s })
  const list = events.data ?? []

  if (events.isPending || (current && pub.isPending)) return <Spinner />
  if (!current) {
    return (
      <>
        <Back to="/" label="返回首页" />
        <h1>我的排练表</h1>
        <Empty title="还没有演出" />
      </>
    )
  }
  if (!pub.data) {
    return (
      <NotPublished eventId={current.id} eventName={current.name} evalDate={current.eval_date} submitted={!!avail.data?.submitted_at}>
        {list.length > 1 && <EventSwitch list={list} value={current.id} onChange={(id) => update({ event: id })} />}
      </NotPublished>
    )
  }

  const d = pub.data
  const myId = d.my_member_id
  const sessions = scope === 'mine' ? sessionsForMember(d.sessions, myId) : d.sessions
  const mineCount = sessionsForMember(d.sessions, myId).filter((s) => s.kind === 'formal').length
  const dayQuery = [scope === 'all' ? 'scope=all' : '', eventParam != null ? `event=${eventParam}` : ''].filter(Boolean).join('&')
  return (
    <>
      <Back to="/" label="返回首页" />
      <div className="heading">
        <h1>我的排练表</h1>
        <Badge tone="green">已发布 v{d.version_no}</Badge>
      </div>
      <p className="lead">
        {d.event_name} · 你有 {mineCount} 场排练 + 1 场全员评估
      </p>
      {list.length > 1 && <EventSwitch list={list} value={current.id} onChange={(id) => update({ event: id })} />}
      <Panel>
        <div className="section">
          <ScopeToggle value={scope} onChange={setScope} />
          <Tabs
            value={view}
            options={[
              { value: 'week', label: '周日历' },
              { value: 'list', label: '列表' },
            ]}
            onChange={setView}
          />
        </div>
        {view === 'week' ? (
          <WeekView sessions={sessions} range={d} onDateClick={(date) => navigate(`/schedule/day/${date}${dayQuery ? `?${dayQuery}` : ''}`)} />
        ) : (
          <SessionsByDate sessions={sessions} allSessions={d.sessions} />
        )}
      </Panel>
      <CalendarPanel compact />
      <p className="muted" style={{ marginTop: 12 }}>
        有临时变动可随时 <Link to={`/events/${current.id}/availability`}>修改空闲时间</Link>,管理员会收到提示。
      </p>
    </>
  )
}

/** 成员:某一天的日程 */
export function MemberScheduleDayPage() {
  const { date = '' } = useParams()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const events = useEvents()
  const current = pickCurrentEvent(events.data ?? [], params.get('event') ? Number(params.get('event')) : null)
  const pub = usePublishedSchedule(current?.id ?? NaN)
  const scope: Scope = params.get('scope') === 'all' ? 'all' : 'mine'
  if (events.isPending || (current && pub.isPending)) return <Spinner />
  const query = params.toString()
  const back = `/schedule${query ? `?${query}` : ''}`
  if (!current || !pub.data) {
    return (
      <>
        <Back to={back} label="我的排练表" />
        <Empty title="排练表尚未发布" />
      </>
    )
  }
  const d: PublishedSchedule = pub.data
  const sessions = scope === 'mine' ? sessionsForMember(d.sessions, d.my_member_id) : d.sessions
  return (
    <>
      <Back to={back} label="我的排练表" />
      <div className="heading">
        <h1>当天日程</h1>
        <Badge tone="neutral">{scope === 'mine' ? '我的' : '全体'}</Badge>
      </div>
      <p className="lead">{d.event_name}</p>
      <Panel>
        <DayView date={date} sessions={sessions} range={d} memberId={scope === 'mine' ? d.my_member_id : null} onNavigate={(x) => navigate(`/schedule/day/${x}${query ? `?${query}` : ''}`)} />
      </Panel>
    </>
  )
}

function EventSwitch({ list, value, onChange }: { list: RehearsalEvent[]; value: number; onChange: (id: number) => void }) {
  return (
    <div className="version-bar" style={{ marginBottom: 12 }}>
      <select value={value} onChange={(e) => onChange(Number(e.target.value))} aria-label="切换演出">
        {list.map((e) => (
          <option key={e.id} value={e.id}>
            {e.name} · {fmtMd(e.performance_date)} 演出{e.published_version_no != null ? ' · 已发布排练表' : ''}
          </option>
        ))}
      </select>
    </div>
  )
}

function NotPublished({ eventId, eventName, evalDate, submitted, children }: { eventId: number; eventName: string; evalDate: string; submitted: boolean; children?: ReactNode }) {
  return (
    <>
      <Back to="/" label="返回首页" />
      <div className="heading">
        <h1>我的排练表</h1>
        <Badge tone="neutral">尚未发布</Badge>
      </div>
      <p className="lead">{eventName}</p>
      {children}
      <Panel>
        <Badge tone="neutral">尚未发布</Badge>
        <h3 className="card-title" style={{ marginTop: 18 }}>
          排练表正在准备中
        </h3>
        <p className="card-copy">{submitted ? '你的空闲时间已提交,管理员发布后会在这里显示。' : '先填好你的空闲时间,管理员才能安排排练。'}</p>
        <div className="evaluation">
          <strong>
            全员评估 · {fmtMd(evalDate)} 周{weekdayShort(evalDate)}
          </strong>
          <p>演出前一天只有这一场,全员参加,2–3 小时;具体时段等排练表发布。</p>
        </div>
        <p className="muted">
          发布后这里会显示周日历和你的每一场排练,并可订阅到手机日历。有临时变动可随时 <Link to={`/events/${eventId}/availability`}>修改空闲时间</Link>。
        </p>
      </Panel>
      <PrimaryBar>
        {submitted ? (
          <LinkButton to="/" variant="primary" full>
            返回首页
          </LinkButton>
        ) : (
          <LinkButton to={`/events/${eventId}/availability`} variant="primary" full>
            去填写空闲时间
          </LinkButton>
        )}
      </PrimaryBar>
    </>
  )
}
