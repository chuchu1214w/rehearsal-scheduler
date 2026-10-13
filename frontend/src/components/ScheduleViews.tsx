import dayjs from 'dayjs'
import { useEffect, useState } from 'react'

import type { MemberBrief, ScheduleSession, ScheduleVersionDetail } from '../api/types'
import { Badge, Button, Field } from '../ui'
import { Modal } from '../ui/Modal'
import { fmtMd } from '../utils'
import { Location } from './MapLink'
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
  editable = false,
  onMove,
  onSwap,
  onLock,
  onLocation,
  conflictIds,
  jumpDate,
  onResize,
  onDelete,
  onCreate,
  songs,
}: {
  sessions: ScheduleSession[]
  range: ScheduleRange
  focusMemberId?: number | null
  onDateClick?: (date: string) => void
  initialDate?: string
  editable?: boolean
  onMove?: (s: ScheduleSession, date: string, startSlot: number) => void
  onSwap?: (a: ScheduleSession, b: ScheduleSession) => void
  onLock?: (s: ScheduleSession, locked: boolean) => void
  onLocation?: (s: ScheduleSession, location: string) => void
  conflictIds?: Set<number>
  /** 跳到这一天所在的周(如点了某条冲突);可带“|时间戳”以便重复跳转 */
  jumpDate?: string | null
  onResize?: (s: ScheduleSession, startSlot: number, durationSlots: number) => void
  onDelete?: (s: ScheduleSession) => void
  /** 新建一场:选好曲目后回调 */
  onCreate?: (v: { songId: number; date: string; startSlot: number; durationSlots: number }) => void
  /** 新建时可选的曲目 */
  songs?: { id: number; code: string; name: string }[]
}) {
  const [creating, setCreating] = useState<{ date: string; start: number; duration: number } | null>(null)
  const weeks = weekStarts(range.formal_start_date, range.eval_date)
  const today = dayjs().format('YYYY-MM-DD')
  const preferred = initialDate ?? (today >= range.formal_start_date && today <= range.eval_date ? today : range.formal_start_date)
  const [week, setWeek] = useState(() => (weeks.includes(weekOf(preferred)) ? weekOf(preferred) : weeks[0]))
  const [open, setOpen] = useState<ScheduleSession | null>(null)
  useEffect(() => {
    const d = jumpDate?.split('|')[0]
    if (d && weeks.includes(weekOf(d))) setWeek(weekOf(d))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jumpDate])
  // 修改已发布版会复制出新草稿(场次 id 都变了):按曲目 + 固定编号找回同一场;找不到就关闭详情
  const current = open
    ? (sessions.find((s) => s.id === open.id) ??
      sessions.find((s) => s.kind === open.kind && s.song_code === open.song_code && (s.task_key ?? s.task_no) === (open.task_key ?? open.task_no)) ??
      null)
    : null
  useEffect(() => {
    if (open && current && current.id !== open.id) setOpen(current)
    if (open && !current) setOpen(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.id, open?.id])
  const idx = weeks.indexOf(week)
  const order = songOrderOf(sessions)
  const inWeek = sessions.filter((s) => weekOf(s.date) === week)
  const names = new Map<string, string>()
  for (const s of sessions) if (s.song_code) names.set(s.song_code, s.song_name)
  return (
    <>
      <div className="weeknav">
        <Button small className="weeknav__btn" disabled={idx <= 0} onClick={() => setWeek(weeks[idx - 1])} aria-label="上周">
          ‹<span className="weeknav__txt"> 上周</span>
        </Button>
        <div className="weeknav__title">
          <b>
            {fmtMd(week)} – {fmtMd(dayjs(week).add(6, 'day').format('YYYY-MM-DD'))}
          </b>
          <span className="muted">
            第 {idx + 1} / {weeks.length} 周 · {inWeek.length} 场
          </span>
        </div>
        <Button small className="weeknav__btn" disabled={idx >= weeks.length - 1} onClick={() => setWeek(weeks[idx + 1])} aria-label="下周">
          <span className="weeknav__txt">下周 </span>›
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
        editable={editable}
        onMove={onMove}
        onSwap={onSwap}
        conflictIds={conflictIds}
        onResize={onResize}
        onCreate={onCreate && songs?.length ? (date, start, duration) => setCreating({ date, start, duration }) : undefined}
      />
      <div className="legend">
        {order.map((code) => (
          <span key={code}>
            <i style={{ background: songColor(code, order).bg }} />
            {code}
            {names.get(code) && names.get(code) !== code ? ` ${names.get(code)}` : ''}
          </span>
        ))}
        <span>
          <i style={{ background: 'var(--accent)' }} />
          全员评估
        </span>
        {onDateClick && <span className="muted">点日期看当天日程</span>}
        {editable && (
          <span className="muted">
            拖动色块可移动{onSwap ? ',拖到另一场上可交换' : ''}
            {onResize ? ',拖上下边缘可拉长 / 缩短' : ''}
            {onCreate ? ',空白处按住往下拖(手机上点一下)可新建' : ''};<i className="lock" /> 已锁定
            {conflictIds && conflictIds.size > 0 ? ';红框 = 有冲突' : ''}
          </span>
        )}
      </div>
      <SessionModal
        s={current}
        onClose={() => setOpen(null)}
        onLock={
          editable && onLock
            ? (s, locked) => {
                setOpen(null)
                onLock(s, locked)
              }
            : undefined
        }
        onLocation={onLocation}
        onResize={editable && onResize ? onResize : undefined}
        onDelete={
          editable && onDelete
            ? (s) => {
                setOpen(null)
                onDelete(s)
              }
            : undefined
        }
        dayHours={range.day_end_hour - range.day_start_hour}
      />
      {creating && onCreate && songs && (
        <CreateSessionModal
          value={creating}
          songs={songs}
          dayStartHour={range.day_start_hour}
          dayEndHour={range.day_end_hour}
          onClose={() => setCreating(null)}
          onSubmit={(v) => {
            setCreating(null)
            onCreate(v)
          }}
        />
      )}
    </>
  )
}

/** 新建一场:确认时间、选曲目 */
function CreateSessionModal({
  value,
  songs,
  dayStartHour,
  dayEndHour,
  onClose,
  onSubmit,
}: {
  value: { date: string; start: number; duration: number }
  songs: { id: number; code: string; name: string }[]
  dayStartHour: number
  dayEndHour: number
  onClose: () => void
  onSubmit: (v: { songId: number; date: string; startSlot: number; durationSlots: number }) => void
}) {
  const hours = dayEndHour - dayStartHour
  const [songId, setSongId] = useState(songs[0]?.id ?? 0)
  const [start, setStart] = useState(value.start)
  const [duration, setDuration] = useState(value.duration)
  const maxDuration = hours - start
  return (
    <Modal
      open
      title={`新建排练 · ${fmtMd(value.date)} 周${'日一二三四五六'[dayjs(value.date).day()]}`}
      onClose={onClose}
      actions={
        <Button variant="primary" disabled={!songId} onClick={() => onSubmit({ songId, date: value.date, startSlot: start, durationSlots: Math.min(duration, maxDuration) })}>
          新建
        </Button>
      }
    >
      <div className="fields" style={{ marginTop: 4 }}>
        <Field label="曲目">
          <select value={songId} onChange={(e) => setSongId(Number(e.target.value))} aria-label="曲目">
            {songs.map((x) => (
              <option key={x.id} value={x.id}>
                {x.code}
                {x.name !== x.code ? ` · ${x.name}` : ''}
              </option>
            ))}
          </select>
        </Field>
        <Field label="开始">
          <select value={start} onChange={(e) => setStart(Number(e.target.value))} aria-label="开始时间">
            {Array.from({ length: hours }, (_, i) => (
              <option key={i} value={i}>
                {String(dayStartHour + i).padStart(2, '0')}:00
              </option>
            ))}
          </select>
        </Field>
        <Field label="时长">
          <select value={Math.min(duration, maxDuration)} onChange={(e) => setDuration(Number(e.target.value))} aria-label="时长">
            {Array.from({ length: maxDuration }, (_, i) => i + 1).map((h) => (
              <option key={h} value={h}>
                {h} 小时
              </option>
            ))}
          </select>
        </Field>
      </div>
      <p className="muted">场数和时长不必与曲目的排练方案一致,不一致时只会提醒,不影响发布。</p>
    </Modal>
  )
}

export function SessionModal({
  s,
  onClose,
  onLock,
  onLocation,
  onResize,
  onDelete,
  dayHours = 24,
}: {
  s: ScheduleSession | null
  onClose: () => void
  onLock?: (s: ScheduleSession, locked: boolean) => void
  onLocation?: (s: ScheduleSession, location: string) => void
  /** 以小时为单位缩短 / 延长(新的开始格与时长) */
  onResize?: (s: ScheduleSession, startSlot: number, durationSlots: number) => void
  onDelete?: (s: ScheduleSession) => void
  /** 每天可排的小时数(延长时不超出) */
  dayHours?: number
}) {
  const [loc, setLoc] = useState(s?.location ?? '')
  const [confirmDelete, setConfirmDelete] = useState(false)
  useEffect(() => setLoc(s?.location ?? ''), [s?.id, s?.location])
  useEffect(() => setConfirmDelete(false), [s?.id])
  if (!s) return null
  const editableFormal = s.kind === 'formal' && !s.locked
  const end = s.start_slot + s.duration_slots
  const absent = new Set(s.absent.map((m) => m.id))
  return (
    <Modal
      open
      title={s.kind === 'evaluation' ? '全员评估' : `${s.song_code} · ${s.song_name}`}
      onClose={onClose}
      actions={
        onLock && s.kind === 'formal' ? (
          <Button variant={s.locked ? 'ghost' : 'default'} onClick={() => onLock(s, !s.locked)}>
            {s.locked ? '解锁' : '锁定这场'}
          </Button>
        ) : undefined
      }
    >
      <p style={{ fontSize: 14, color: 'var(--ink)' }}>
        {fmtMd(s.date)} {s.weekday} · {s.time} · {s.duration_slots}h
        {s.locked && <Badge tone="orange">已锁定</Badge>}
      </p>
      {onLocation ? (
        <div className="inline" style={{ marginTop: 10, gap: 8 }}>
          <input value={loc} onChange={(e) => setLoc(e.target.value)} placeholder="排练地点,如 三楼排练厅;可粘贴 Naver 地图链接" maxLength={200} style={{ flex: 1 }} aria-label="排练地点" />
          <Button small disabled={loc.trim() === (s.location ?? '')} onClick={() => onLocation(s, loc.trim())}>
            保存地点
          </Button>
        </div>
      ) : (
        s.location && (
          <p style={{ marginTop: 8, fontSize: 13 }}>
            <Location location={s.location} />
          </p>
        )
      )}
      {onResize && editableFormal && (
        <div className="inline" style={{ marginTop: 10, gap: 8 }}>
          <span className="muted">时长 {s.duration_slots} 小时</span>
          <Button small disabled={s.duration_slots <= 1} onClick={() => onResize(s, s.start_slot, s.duration_slots - 1)}>
            − 缩短 1 小时
          </Button>
          <Button
            small
            disabled={s.duration_slots >= dayHours}
            onClick={() => (end < dayHours ? onResize(s, s.start_slot, s.duration_slots + 1) : onResize(s, s.start_slot - 1, s.duration_slots + 1))}
          >
            ＋ 延长 1 小时
          </Button>
        </div>
      )}
      {onLock && s.kind === 'formal' && (
        <p className="muted">
          在周日历里拖动色块可移动这场,拖上下边缘可调整时长;锁定后不会被改动,「锁定后重排」时也保持不变。时长和场数可以与曲目的排练方案不同,只会提醒。
        </p>
      )}
      {onDelete && editableFormal && (
        <div className="inline" style={{ marginTop: 10, gap: 8 }}>
          {confirmDelete ? (
            <>
              <span className="muted">确定删除这场?之后可以撤销。</span>
              <Button small variant="danger" onClick={() => onDelete(s)}>
                删除
              </Button>
              <Button small variant="ghost" onClick={() => setConfirmDelete(false)}>
                取消
              </Button>
            </>
          ) : (
            <Button small variant="ghost-danger" onClick={() => setConfirmDelete(true)}>
              删除这场
            </Button>
          )}
        </div>
      )}
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
      <strong>
        全员评估 · {s.time}
      </strong>
      {s.location && (
        <p>
          <Location location={s.location} />
        </p>
      )}
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
        {s.location && (
          <p style={{ color: 'var(--ink)' }}>
            <Location location={s.location} />
          </p>
        )}
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
  allSessions,
}: {
  date: string
  sessions: ScheduleSession[]
  range: ScheduleRange
  memberId?: number | null
  onNavigate: (date: string) => void
  /** 整版场次(「第 N / M 场」的 M 按整版算,与服务器给的序号一致) */
  allSessions?: ScheduleSession[]
}) {
  const prev = dayjs(date).subtract(1, 'day').format('YYYY-MM-DD')
  const next = dayjs(date).add(1, 'day').format('YYYY-MM-DD')
  const today = sessions.filter((s) => s.date === date)
  const taskTotal = new Map<string, number>()
  for (const s of allSessions ?? sessions) if (s.kind === 'formal' && s.song_code) taskTotal.set(s.song_code, (taskTotal.get(s.song_code) ?? 0) + 1)
  const hours = today.filter((s) => s.kind === 'formal').reduce((a, s) => a + s.duration_slots, 0)
  return (
    <>
      <div className="weeknav">
        <Button small className="weeknav__btn" disabled={prev < range.formal_start_date} onClick={() => onNavigate(prev)} aria-label="前一天">
          ‹<span className="weeknav__txt"> 前一天</span>
        </Button>
        <div className="weeknav__title">
          <b>
            {dayjs(date).format('M月D日')} 周{['日', '一', '二', '三', '四', '五', '六'][dayjs(date).day()]}
          </b>
          <span className="muted">{date === range.eval_date ? '全员评估日' : `${today.length} 场${hours ? ` · ${hours}h` : ''}`}</span>
        </div>
        <Button small className="weeknav__btn" disabled={next > range.eval_date} onClick={() => onNavigate(next)} aria-label="后一天">
          <span className="weeknav__txt">后一天 </span>›
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
