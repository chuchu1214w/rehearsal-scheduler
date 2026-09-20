import dayjs from 'dayjs'
import { useState } from 'react'

import type { MemberBrief, ScheduleSession, ScheduleVersionDetail } from '../api/types'
import { Badge, Button } from '../ui'
import { Modal } from '../ui/Modal'
import { fmtMd } from '../utils'
import { WeekGrid, songColor, weekOf, weekStarts } from './WeekGrid'

/** 排练表的三种呈现(周日历 / 按日期列表 / 按成员统计)与场次详情弹窗;管理员端草稿与成员端已发布共用。 */

export interface ScheduleRange {
  formal_start_date: string
  formal_end_date: string
  eval_date: string
  day_start_hour: number
  day_end_hour: number
}

export function songOrderOf(sessions: ScheduleSession[]): string[] {
  return [...new Set(sessions.filter((s) => s.song_code).map((s) => s.song_code as string))].sort()
}

/** 只保留某成员参与(且未缺席)的场次;评估场保留 */
export function sessionsForMember(sessions: ScheduleSession[], memberId: number | null): ScheduleSession[] {
  if (memberId == null) return sessions
  return sessions.filter((s) => s.kind === 'evaluation' || (s.members.some((m) => m.id === memberId) && !s.absent.some((m) => m.id === memberId)))
}

export function WeekView({
  sessions,
  range,
  focusMemberId = null,
  onDateClick,
  initialDate,
}: {
  sessions: ScheduleSession[]
  range: ScheduleRange
  focusMemberId?: number | null
  onDateClick?: (date: string) => void
  initialDate?: string
}) {
  const weeks = weekStarts(range.formal_start_date, range.eval_date)
  const today = dayjs().format('YYYY-MM-DD')
  const preferred = initialDate ?? (today >= range.formal_start_date && today <= range.eval_date ? today : range.formal_start_date)
  const [week, setWeek] = useState(() => (weeks.includes(weekOf(preferred)) ? weekOf(preferred) : weeks[0]))
  const [open, setOpen] = useState<ScheduleSession | null>(null)
  const idx = weeks.indexOf(week)
  const order = songOrderOf(sessions)
  const inWeek = sessions.filter((s) => weekOf(s.date) === week)
  const names = new Map<string, string>()
  for (const s of sessions) if (s.song_code) names.set(s.song_code, s.song_name)
  return (
    <>
      <div className="weeknav">
        <Button small disabled={idx <= 0} onClick={() => setWeek(weeks[idx - 1])}>
          ‹ 上周
        </Button>
        <b>
          {fmtMd(week)} – {fmtMd(dayjs(week).add(6, 'day').format('YYYY-MM-DD'))}
          <span className="muted"> · 第 {idx + 1} / {weeks.length} 周 · {inWeek.length} 场</span>
        </b>
        <Button small disabled={idx >= weeks.length - 1} onClick={() => setWeek(weeks[idx + 1])}>
          下周 ›
        </Button>
      </div>
      <WeekGrid
        weekStart={week}
        sessions={inWeek}
        dayStartHour={range.day_start_hour}
        dayEndHour={range.day_end_hour}
        songOrder={order}
        rangeStart={range.formal_start_date}
        rangeEnd={range.eval_date}
        focusMemberId={focusMemberId}
        onDateClick={onDateClick}
        onSessionClick={setOpen}
      />
      <div className="legend">
        {order.map((code) => (
          <span key={code}>
            <i style={{ background: songColor(code, order).bg }} />
            {code} {names.get(code)}
          </span>
        ))}
        <span>
          <i style={{ background: 'var(--accent)' }} />
          全员评估
        </span>
        {onDateClick && <span className="muted">点日期看当天日程</span>}
      </div>
      <SessionModal s={open} onClose={() => setOpen(null)} />
    </>
  )
}

export function SessionModal({ s, onClose }: { s: ScheduleSession | null; onClose: () => void }) {
  if (!s) return null
  const absent = new Set(s.absent.map((m) => m.id))
  return (
    <Modal open title={s.kind === 'evaluation' ? '全员评估' : `${s.song_code} · ${s.song_name}`} onClose={onClose}>
      <p style={{ fontSize: 14, color: 'var(--ink)' }}>
        {fmtMd(s.date)} {s.weekday} · {s.time} · {s.duration_slots}h
      </p>
      {s.kind === 'evaluation' ? (
        <div style={{ marginTop: 8 }}>
          {s.attendance && Object.values(s.attendance).some((t) => t !== s.time) ? (
            <>
              <p className="muted">迟到早退安排:</p>
              <ul style={{ margin: '4px 0 0 16px', fontSize: 13 }}>
                {Object.entries(s.attendance)
                  .filter(([, t]) => t !== s.time)
                  .map(([m, t]) => (
                    <li key={m}>
                      {m}:{t}
                    </li>
                  ))}
              </ul>
              <p className="muted">其余全程到场。</p>
            </>
          ) : (
            <p className="muted">{s.members.length} 人全程到场。</p>
          )}
        </div>
      ) : (
        <p style={{ marginTop: 8, fontSize: 13 }}>
          {s.members.map((m, i) => (
            <span key={m.id} style={absent.has(m.id) ? { color: 'var(--red)' } : undefined}>
              {i > 0 && '、'}
              {m.display_name}
              {absent.has(m.id) && '(缺席)'}
            </span>
          ))}
        </p>
      )}
    </Modal>
  )
}

export function SessionsByDate({ sessions, allSessions }: { sessions: ScheduleSession[]; allSessions?: ScheduleSession[] }) {
  const byDate = new Map<string, ScheduleSession[]>()
  for (const s of sessions) byDate.set(s.date, [...(byDate.get(s.date) ?? []), s])
  const taskTotal = new Map<string, number>()
  for (const s of allSessions ?? sessions) if (s.kind === 'formal' && s.song_code) taskTotal.set(s.song_code, (taskTotal.get(s.song_code) ?? 0) + 1)
  if (sessions.length === 0) return <p className="muted" style={{ marginTop: 14 }}>没有场次。</p>
  return (
    <>
      {[...byDate.entries()].map(([date, list]) => (
        <div key={date}>
          <div className="date-title">
            <span>
              {fmtMd(date)} {list[0].weekday}
            </span>
            <span>{list.length} 场</span>
          </div>
          {list.map((s) => (s.kind === 'evaluation' ? <EvaluationBlock key={s.id} s={s} /> : <SessionRow key={s.id} s={s} total={s.song_code ? (taskTotal.get(s.song_code) ?? 0) : 0} />))}
        </div>
      ))}
    </>
  )
}

export function EvaluationBlock({ s, memberId = null }: { s: ScheduleSession; memberId?: number | null }) {
  const mine = memberId != null && s.attendance ? Object.entries(s.attendance).find(([name]) => s.members.find((m) => m.id === memberId)?.display_name === name)?.[1] : undefined
  const partial = s.attendance ? Object.entries(s.attendance).filter(([, t]) => t !== s.time) : []
  return (
    <div className="evaluation" style={{ margin: '8px 0 12px' }}>
      <strong>全员评估 · {s.time}</strong>
      <p>
        {mine && mine !== s.time ? `你的到场时间:${mine};` : ''}
        {partial.length > 0 ? partial.map(([m, t]) => `${m} ${t}`).join(' · ') + ';其余全程到场' : `${s.members.length} 人全程到场`}
      </p>
    </div>
  )
}

export function SessionRow({ s, total }: { s: ScheduleSession; total: number }) {
  const [start, end] = s.time.split('–')
  const absentIds = new Set(s.absent.map((m) => m.id))
  return (
    <div className="session">
      <div className="session__time">
        {start}
        <br />
        <span>{end}</span>
      </div>
      <div>
        <div className="session__title">
          {s.song_code && <Badge>{s.song_code}</Badge>} {s.song_name}
          <small>
            第 {s.task_no} / {total} 场 · {s.duration_slots}h
          </small>
        </div>
        <p>
          {s.members.map((m: MemberBrief, i) => (
            <span key={m.id} className={absentIds.has(m.id) ? 'absent' : undefined}>
              {i > 0 && '、'}
              {m.display_name}
              {absentIds.has(m.id) && '(缺)'}
            </span>
          ))}
        </p>
      </div>
    </div>
  )
}

export function MemberTable({ d }: { d: ScheduleVersionDetail }) {
  return (
    <div className="tbl-wrap" style={{ marginTop: 12 }}>
      <table className="tbl">
        <thead>
          <tr>
            <th>成员</th>
            <th className="num">场次</th>
            <th className="num">小时</th>
            <th className="num">天数</th>
            <th className="num">缺席</th>
            <th>评估到场</th>
          </tr>
        </thead>
        <tbody>
          {d.member_stats.map((m) => (
            <tr key={m.member_id} className={m.absent > 0 ? 'bad' : ''}>
              <td>{m.display_name}</td>
              <td className="num">{m.sessions}</td>
              <td className="num">{m.hours}</td>
              <td className="num">{m.days}</td>
              <td className="num">{m.absent}</td>
              <td>{m.eval_time ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** 某一天的日程(按日页面):前后一天切换 + 当天场次 */
export function DayView({
  date,
  sessions,
  range,
  memberId = null,
  onNavigate,
}: {
  date: string
  sessions: ScheduleSession[]
  range: ScheduleRange
  memberId?: number | null
  onNavigate: (date: string) => void
}) {
  const prev = dayjs(date).subtract(1, 'day').format('YYYY-MM-DD')
  const next = dayjs(date).add(1, 'day').format('YYYY-MM-DD')
  const today = sessions.filter((s) => s.date === date)
  const taskTotal = new Map<string, number>()
  for (const s of sessions) if (s.kind === 'formal' && s.song_code) taskTotal.set(s.song_code, (taskTotal.get(s.song_code) ?? 0) + 1)
  const hours = today.filter((s) => s.kind === 'formal').reduce((a, s) => a + s.duration_slots, 0)
  return (
    <>
      <div className="weeknav">
        <Button small disabled={prev < range.formal_start_date} onClick={() => onNavigate(prev)}>
          ‹ 前一天
        </Button>
        <b>
          {dayjs(date).format('M月D日')} 周{['日', '一', '二', '三', '四', '五', '六'][dayjs(date).day()]}
          <span className="muted">
            {' '}
            · {date === range.eval_date ? '全员评估日' : `${today.length} 场${hours ? ` · ${hours}h` : ''}`}
          </span>
        </b>
        <Button small disabled={next > range.eval_date} onClick={() => onNavigate(next)}>
          后一天 ›
        </Button>
      </div>
      {today.length === 0 ? (
        <p className="muted" style={{ marginTop: 18 }}>
          {memberId != null ? '这天你没有排练。' : '这天没有排练。'}
        </p>
      ) : (
        <div style={{ marginTop: 6 }}>
          {today.map((s) => (s.kind === 'evaluation' ? <EvaluationBlock key={s.id} s={s} memberId={memberId} /> : <SessionRow key={s.id} s={s} total={s.song_code ? (taskTotal.get(s.song_code) ?? 0) : 0} />))}
        </div>
      )}
    </>
  )
}
