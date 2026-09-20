import dayjs from 'dayjs'
import { useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'

import type { ScheduleSession } from '../api/types'

/** 课程表式周视图:列 = 一周七天,行 = 小时;场次按曲目着色,评估场用主色。管理员可拖动色块移动场次(M5)。 */

export const SONG_COLORS = [
  { bg: '#e8ecfb', ink: '#2f3f78' },
  { bg: '#fde3f2', ink: '#8a2a5f' },
  { bg: '#e2f4ea', ink: '#1f5b41' },
  { bg: '#fff0d6', ink: '#7a4d0c' },
  { bg: '#e6f2fb', ink: '#1f4d73' },
  { bg: '#f3e6fb', ink: '#5a2c7a' },
  { bg: '#fbe9e3', ink: '#7a3520' },
  { bg: '#e8f7f5', ink: '#175c55' },
  { bg: '#f6f0dc', ink: '#5f5312' },
  { bg: '#ecebf5', ink: '#3d3a63' },
  { bg: '#fbe6ea', ink: '#7a2231' },
  { bg: '#e4f0e2', ink: '#2f5a2a' },
]

export function songColor(code: string | null, order: string[]) {
  if (!code) return { bg: 'var(--accent)', ink: '#fef0fb' }
  const i = order.indexOf(code)
  return SONG_COLORS[(i < 0 ? code.charCodeAt(0) : i) % SONG_COLORS.length]
}

/** 以周一为一周的开始;返回覆盖 [from, to] 的每周周一 */
export function weekStarts(from: string, to: string): string[] {
  const out: string[] = []
  let d = dayjs(from).startOf('day')
  d = d.subtract((d.day() + 6) % 7, 'day')
  const end = dayjs(to)
  while (!d.isAfter(end)) {
    out.push(d.format('YYYY-MM-DD'))
    d = d.add(7, 'day')
  }
  return out
}

export function weekOf(date: string): string {
  const d = dayjs(date)
  return d.subtract((d.day() + 6) % 7, 'day').format('YYYY-MM-DD')
}

interface Props {
  weekStart: string
  sessions: ScheduleSession[]
  dayStartHour: number
  dayEndHour: number
  songOrder: string[]
  rangeStart: string
  rangeEnd: string
  /** 只高亮这名成员参与的场次(其余变淡);null = 全体 */
  focusMemberId?: number | null
  onDateClick?: (date: string) => void
  onSessionClick?: (s: ScheduleSession) => void
  /** 允许拖动正规排练场次;评估场与已锁定的不能拖 */
  editable?: boolean
  onMove?: (s: ScheduleSession, date: string, startSlot: number) => void
}

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']

interface DragState {
  session: ScheduleSession
  pointerId: number
  offsetRows: number
  cols: DOMRect[]
  gridRect: DOMRect
  rowH: number
  moved: boolean
}

export function WeekGrid({
  weekStart,
  sessions,
  dayStartHour,
  dayEndHour,
  songOrder,
  rangeStart,
  rangeEnd,
  focusMemberId = null,
  onDateClick,
  onSessionClick,
  editable = false,
  onMove,
}: Props) {
  const hours = dayEndHour - dayStartHour
  const today = dayjs().format('YYYY-MM-DD')
  const days = Array.from({ length: 7 }, (_, i) => dayjs(weekStart).add(i, 'day').format('YYYY-MM-DD'))
  const byDay = new Map<string, ScheduleSession[]>()
  for (const s of sessions) byDay.set(s.date, [...(byDay.get(s.date) ?? []), s])
  const gridRef = useRef<HTMLDivElement>(null)
  const drag = useRef<DragState | null>(null)
  const suppressClick = useRef(false)
  const [ghost, setGhost] = useState<{ id: number; dayIdx: number; start: number; duration: number; valid: boolean } | null>(null)

  const canDrag = (s: ScheduleSession) => editable && !!onMove && s.kind === 'formal' && !s.locked

  const onPointerDown = (e: ReactPointerEvent<HTMLButtonElement>, s: ScheduleSession) => {
    if (!canDrag(s) || !gridRef.current || e.button !== 0) return
    const grid = gridRef.current
    const cols = [...grid.querySelectorAll<HTMLElement>('.weekgrid__col')].map((c) => c.getBoundingClientRect())
    const rowH = cols[0]?.height ? cols[0].height / hours : 34
    const blockRect = e.currentTarget.getBoundingClientRect()
    try {
      e.currentTarget.setPointerCapture(e.pointerId)
    } catch {
      /* 合成事件没有真实指针时会抛错,忽略 */
    }
    drag.current = { session: s, pointerId: e.pointerId, offsetRows: Math.floor((e.clientY - blockRect.top) / rowH), cols, gridRect: grid.getBoundingClientRect(), rowH, moved: false }
  }

  const onPointerMove = (e: ReactPointerEvent<HTMLButtonElement>) => {
    const d = drag.current
    if (!d || e.pointerId !== d.pointerId) return
    let dayIdx = d.cols.findIndex((r) => e.clientX >= r.left && e.clientX <= r.right)
    if (dayIdx < 0) dayIdx = e.clientX < d.cols[0].left ? 0 : d.cols.length - 1
    const col = d.cols[dayIdx]
    const start = Math.max(0, Math.min(hours - d.session.duration_slots, Math.round((e.clientY - col.top) / d.rowH - d.offsetRows)))
    const origIdx = days.indexOf(d.session.date)
    if (!d.moved && dayIdx === origIdx && start === d.session.start_slot) return
    d.moved = true
    const date = days[dayIdx]
    setGhost({ id: d.session.id, dayIdx, start, duration: d.session.duration_slots, valid: date >= rangeStart && date < rangeEnd })
  }

  const finishDrag = (e: ReactPointerEvent<HTMLButtonElement>, commit: boolean) => {
    const d = drag.current
    if (!d || e.pointerId !== d.pointerId) return
    drag.current = null
    const g = ghost
    setGhost(null)
    if (d.moved) suppressClick.current = true
    if (commit && d.moved && g && g.valid && onMove) {
      const date = days[g.dayIdx]
      if (date !== d.session.date || g.start !== d.session.start_slot) onMove(d.session, date, g.start)
    }
  }

  return (
    <div ref={gridRef} className={'weekgrid' + (editable ? ' is-editable' : '')} style={{ ['--rows' as string]: hours }}>
      <div className="weekgrid__corner" />
      {days.map((d) => {
        const inRange = d >= rangeStart && d <= rangeEnd
        const n = byDay.get(d)?.length ?? 0
        return (
          <button
            key={d}
            type="button"
            className={'weekgrid__day' + (d === today ? ' is-today' : '') + (inRange ? '' : ' is-off')}
            onClick={() => onDateClick?.(d)}
            disabled={!onDateClick}
            aria-label={`${dayjs(d).format('M月D日')} 周${WEEKDAYS[(dayjs(d).day() + 6) % 7]}${n ? `,${n} 场` : ''}`}
          >
            <span>周{WEEKDAYS[(dayjs(d).day() + 6) % 7]}</span>
            <b>{dayjs(d).format('M/D')}</b>
          </button>
        )
      })}
      <div className="weekgrid__hours">
        {Array.from({ length: hours }, (_, i) => (
          <span key={i}>{String(dayStartHour + i).padStart(2, '0')}</span>
        ))}
      </div>
      {days.map((d) => {
        const list = (byDay.get(d) ?? []).slice().sort((a, b) => a.start_slot - b.start_slot || b.duration_slots - a.duration_slots)
        const lanes = assignLanes(list)
        const laneCount = Math.max(1, ...lanes.map((l) => l.lanes))
        return (
          <div key={d} className={'weekgrid__col' + (d >= rangeStart && d <= rangeEnd ? '' : ' is-off')}>
            {list.map((s, i) => {
              const c = songColor(s.kind === 'evaluation' ? null : s.song_code, songOrder)
              const involved = focusMemberId == null || s.kind === 'evaluation' || s.members.some((m) => m.id === focusMemberId)
              const absent = focusMemberId != null && s.absent.some((m) => m.id === focusMemberId)
              const dim = !involved || absent
              const { lane, lanes: n } = lanes[i]
              const width = 100 / Math.max(n, 1)
              const dragging = ghost?.id === s.id
              return (
                <button
                  key={s.id}
                  type="button"
                  className={
                    'weekgrid__block' +
                    (s.kind === 'evaluation' ? ' is-eval' : '') +
                    (dim ? ' is-dim' : '') +
                    (s.locked ? ' is-locked' : '') +
                    (canDrag(s) ? ' is-draggable' : '') +
                    (dragging ? ' is-dragging' : '')
                  }
                  style={{
                    top: `calc(${s.start_slot} * var(--row-h))`,
                    height: `calc(${s.duration_slots} * var(--row-h) - 2px)`,
                    left: `${lane * width}%`,
                    width: `calc(${width}% - 2px)`,
                    background: c.bg,
                    color: c.ink,
                  }}
                  onClick={() => {
                    if (suppressClick.current) {
                      suppressClick.current = false
                      return
                    }
                    onSessionClick?.(s)
                  }}
                  onPointerDown={(e) => onPointerDown(e, s)}
                  onPointerMove={onPointerMove}
                  onPointerUp={(e) => finishDrag(e, true)}
                  onPointerCancel={(e) => finishDrag(e, false)}
                  title={`${s.time} ${s.song_name}${s.locked ? '(已锁定)' : ''}`}
                >
                  <b>
                    {s.locked && <i className="lock" aria-label="已锁定" />}
                    {s.kind === 'evaluation' ? '评估' : s.song_code}
                  </b>
                  <span>{s.kind === 'evaluation' ? '全员' : s.song_name}</span>
                  {laneCount === 1 && <small>{s.time}</small>}
                </button>
              )
            })}
          </div>
        )
      })}
      {ghost && drag.current && (
        <div
          className={'weekgrid__ghost' + (ghost.valid ? '' : ' is-invalid')}
          style={{
            left: drag.current.cols[ghost.dayIdx].left - drag.current.gridRect.left,
            top: drag.current.cols[ghost.dayIdx].top - drag.current.gridRect.top + ghost.start * drag.current.rowH,
            width: drag.current.cols[ghost.dayIdx].width,
            height: ghost.duration * drag.current.rowH - 2,
          }}
        >
          <b>{drag.current.session.song_code}</b>
          <span>
            {String(dayStartHour + ghost.start).padStart(2, '0')}:00–{String(dayStartHour + ghost.start + ghost.duration).padStart(2, '0')}:00
          </span>
        </div>
      )}
    </div>
  )
}

/** 同一天时间重叠的场次并排显示:返回每场的泳道号与该重叠组的泳道总数 */
function assignLanes(list: ScheduleSession[]): { lane: number; lanes: number }[] {
  const result = list.map(() => ({ lane: 0, lanes: 1 }))
  let groupStart = 0
  let groupEnd = -1
  let laneEnds: number[] = []
  const finishGroup = (to: number) => {
    for (let k = groupStart; k < to; k++) result[k].lanes = laneEnds.length
  }
  list.forEach((s, i) => {
    const start = s.start_slot
    const end = s.start_slot + s.duration_slots
    if (start >= groupEnd) {
      finishGroup(i)
      groupStart = i
      laneEnds = []
    }
    let lane = laneEnds.findIndex((e) => e <= start)
    if (lane < 0) {
      lane = laneEnds.length
      laneEnds.push(end)
    } else laneEnds[lane] = end
    result[i].lane = lane
    groupEnd = Math.max(groupEnd, end)
  })
  finishGroup(list.length)
  return result
}
