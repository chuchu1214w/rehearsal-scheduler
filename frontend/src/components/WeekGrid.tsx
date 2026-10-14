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
  /** 拖到另一场上松手 = 交换两场的时间 */
  onSwap?: (a: ScheduleSession, b: ScheduleSession) => void
  /** 有冲突的场次(标红) */
  conflictIds?: Set<number>
  /** 拖色块的上 / 下边缘调整时长(以小时为单位):新的开始格与时长 */
  onResize?: (s: ScheduleSession, startSlot: number, durationSlots: number) => void
  /** 在空白处按住往下拖(手机上点一下)新建一场:日期、开始格、时长 */
  onCreate?: (date: string, startSlot: number, durationSlots: number) => void
  /** 拖到某个时段时谁会缺席(参演成员里那段时间没空的,加上计划内缺席)、谁还没填空闲;null 表示不知道(不显示) */
  awayAt?: (s: ScheduleSession, date: string, startSlot: number, durationSlots: number) => Away | null
}

export interface Away {
  away: string[]
  unknown: string[]
}

/** 「缺 A、B」「全员可到」「未填空闲 C」 */
function awayText(a: Away): { text: string; tone: string } {
  const parts = []
  if (a.away.length) parts.push(`缺 ${a.away.join('、')}`)
  if (a.unknown.length) parts.push(`未填空闲 ${a.unknown.join('、')}`)
  return { text: parts.join(' · ') || '全员可到', tone: a.away.length > 1 ? ' is-many' : a.away.length || a.unknown.length ? ' is-one' : '' }
}

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']

type DragMode = 'move' | 'top' | 'bottom' | 'create'

interface DragState {
  mode: DragMode
  /** 新建时为 null */
  session: ScheduleSession | null
  pointerId: number
  pointerType: string
  offsetRows: number
  /** 新建:按下时所在的格与列 */
  anchorRow: number
  anchorDay: number
  x0: number
  y0: number
  cols: DOMRect[]
  gridRect: DOMRect
  rowH: number
  moved: boolean
  /** 当前预览(松手时以它为准,而不是可能还没渲染的 React 状态) */
  ghost: Ghost | null
  /** 拖到其上可交换的另一场 */
  target: ScheduleSession | null
}

interface Ghost {
  id: number | null
  dayIdx: number
  start: number
  duration: number
  valid: boolean
  mode: DragMode
}

/** 手机上点空白处新建时的默认时长 */
const DEFAULT_NEW_HOURS = 2

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
  onSwap,
  conflictIds,
  onResize,
  onCreate,
  awayAt,
}: Props) {
  const hours = dayEndHour - dayStartHour
  const today = dayjs().format('YYYY-MM-DD')
  const days = Array.from({ length: 7 }, (_, i) => dayjs(weekStart).add(i, 'day').format('YYYY-MM-DD'))
  const byDay = new Map<string, ScheduleSession[]>()
  for (const s of sessions) byDay.set(s.date, [...(byDay.get(s.date) ?? []), s])
  const gridRef = useRef<HTMLDivElement>(null)
  const drag = useRef<DragState | null>(null)
  const suppressClick = useRef(false)
  /** 手机上点空白处:等这次点按的 click 到了再打开新建窗口,免得这一下又点到刚弹出的窗口 */
  const pendingTap = useRef<{ date: string; start: number; duration: number } | null>(null)
  const [ghost, setGhost] = useState<Ghost | null>(null)
  const [swapTarget, setSwapTarget] = useState<ScheduleSession | null>(null)
  /** 正规排练日(评估日与演出日不能放正规排练) */
  const formalDay = (date: string) => date >= rangeStart && date < rangeEnd

  /** 指针下方的另一场(可交换的正规排练) */
  const swappableAt = (x: number, y: number, self: ScheduleSession): ScheduleSession | null => {
    if (!onSwap) return null
    const el = document.elementFromPoint(x, y)?.closest<HTMLElement>('[data-session-id]')
    const id = Number(el?.dataset.sessionId)
    if (!id || id === self.id) return null
    const other = sessions.find((s) => s.id === id)
    return other && other.kind === 'formal' && !other.locked ? other : null
  }

  const canDrag = (s: ScheduleSession) => editable && !!onMove && s.kind === 'formal' && !s.locked
  const canResize = (s: ScheduleSession) => editable && !!onResize && s.kind === 'formal' && !s.locked

  const measure = () => {
    const grid = gridRef.current!
    const cols = [...grid.querySelectorAll<HTMLElement>('.weekgrid__col')].map((c) => c.getBoundingClientRect())
    return { cols, gridRect: grid.getBoundingClientRect(), rowH: cols[0]?.height ? cols[0].height / hours : 34 }
  }
  const rowAt = (y: number, col: DOMRect, rowH: number) => Math.max(0, Math.min(hours, Math.round((y - col.top) / rowH)))

  const onPointerDown = (e: ReactPointerEvent<HTMLButtonElement>, s: ScheduleSession) => {
    if (!gridRef.current || e.button !== 0) return
    if (!e.isPrimary) return // 第二根手指不打断正在进行的拖动(新的主指针会重新开始,也清掉漏收松手事件的旧状态)
    const handle = (e.target as HTMLElement).dataset?.handle as 'top' | 'bottom' | undefined
    const mode: DragMode = handle && canResize(s) ? handle : 'move'
    if (mode === 'move' && !canDrag(s)) return
    e.stopPropagation() // 不要触发所在列的「新建」
    const { cols, gridRect, rowH } = measure()
    const blockRect = e.currentTarget.getBoundingClientRect()
    try {
      e.currentTarget.setPointerCapture(e.pointerId)
    } catch {
      /* 合成事件没有真实指针时会抛错,忽略 */
    }
    drag.current = {
      mode,
      session: s,
      pointerId: e.pointerId,
      pointerType: e.pointerType,
      offsetRows: Math.floor((e.clientY - blockRect.top) / rowH),
      anchorRow: 0,
      anchorDay: days.indexOf(s.date),
      x0: e.clientX,
      y0: e.clientY,
      cols,
      gridRect,
      rowH,
      moved: false,
      ghost: null,
      target: null,
    }
  }

  /** 在某一天的空白处按下:鼠标立即开始拖出时长;手指 / 触控笔先不拦截(保留页面滚动),松开时没怎么动才算「点了一下」 */
  const onColPointerDown = (e: ReactPointerEvent<HTMLDivElement>, dayIdx: number) => {
    if (!e.isPrimary) return // 第二根手指不打断正在进行的拖动
    pendingTap.current = null
    if (!editable || !onCreate || !gridRef.current || e.button !== 0) return
    if ((e.target as HTMLElement).closest('[data-session-id]')) return
    if (!formalDay(days[dayIdx])) return
    const { cols, gridRect, rowH } = measure()
    const anchorRow = Math.max(0, Math.min(hours - 1, Math.floor((e.clientY - cols[dayIdx].top) / rowH)))
    const preset: Ghost = { id: null, dayIdx, start: anchorRow, duration: Math.min(DEFAULT_NEW_HOURS, hours - anchorRow), valid: true, mode: 'create' }
    drag.current = {
      mode: 'create',
      session: null,
      pointerId: e.pointerId,
      pointerType: e.pointerType,
      offsetRows: 0,
      anchorRow,
      anchorDay: dayIdx,
      x0: e.clientX,
      y0: e.clientY,
      cols,
      gridRect,
      rowH,
      moved: false,
      ghost: preset,
      target: null,
    }
    if (e.pointerType === 'mouse') {
      e.preventDefault()
      try {
        e.currentTarget.setPointerCapture(e.pointerId)
      } catch {
        /* 忽略 */
      }
      setGhost(preset) // 只点一下 = 默认时长;往下拖 = 按拖出的范围
    }
  }

  /** 根据指针位置更新拖动中的预览(写在 drag ref 上,渲染只是显示它) */
  const track = (d: DragState, x: number, y: number) => {
    if (d.mode === 'create') {
      if (d.pointerType !== 'mouse') return // 手指拖动 = 滚动页面
      if (!d.moved && Math.abs(y - d.y0) < d.rowH / 3) return
      d.moved = true
      const end = Math.max(d.anchorRow + 1, rowAt(y, d.cols[d.anchorDay], d.rowH))
      d.ghost = { id: null, dayIdx: d.anchorDay, start: d.anchorRow, duration: end - d.anchorRow, valid: true, mode: 'create' }
      return
    }
    const s = d.session!
    // 按下后没怎么动 = 单击(打开详情),不算移动(手指容差更大);移动量按「相对按下位置」换算成整小时
    if (!d.moved && Math.hypot(x - d.x0, y - d.y0) < (d.pointerType === 'mouse' ? 5 : 10)) return
    const dRows = Math.round((y - d.y0) / d.rowH)
    if (d.mode === 'top' || d.mode === 'bottom') {
      const end0 = s.start_slot + s.duration_slots
      const start = d.mode === 'top' ? Math.max(0, Math.min(s.start_slot + dRows, end0 - 1)) : s.start_slot
      const end = d.mode === 'bottom' ? Math.min(hours, Math.max(end0 + dRows, s.start_slot + 1)) : end0
      d.moved = true
      d.ghost = start === s.start_slot && end === end0 ? null : { id: s.id, dayIdx: d.anchorDay, start, duration: end - start, valid: true, mode: d.mode }
      return
    }
    const other = swappableAt(x, y, s)
    // 两场时间完全相同(并排显示)时交换没有意义,只当作移动处理
    d.target = other && !(other.date === s.date && other.start_slot === s.start_slot && other.duration_slots === s.duration_slots) ? other : null
    if (d.target) {
      d.moved = true
      d.ghost = null
      return
    }
    let dayIdx = d.cols.findIndex((r) => x >= r.left && x <= r.right)
    if (dayIdx < 0) dayIdx = x < d.cols[0].left ? 0 : d.cols.length - 1
    const start = Math.max(0, Math.min(hours - s.duration_slots, s.start_slot + dRows))
    d.moved = true
    d.ghost = dayIdx === d.anchorDay && start === s.start_slot ? null : { id: s.id, dayIdx, start, duration: s.duration_slots, valid: formalDay(days[dayIdx]), mode: 'move' }
  }

  const onPointerMove = (e: ReactPointerEvent<HTMLElement>) => {
    const d = drag.current
    if (!d || e.pointerId !== d.pointerId) return
    track(d, e.clientX, e.clientY)
    if (d.mode === 'create' && d.pointerType !== 'mouse') return
    setGhost(d.ghost)
    setSwapTarget(d.target)
  }

  const finishDrag = (e: ReactPointerEvent<HTMLElement>, commit: boolean) => {
    const d = drag.current
    if (!d || e.pointerId !== d.pointerId) return
    if (commit) track(d, e.clientX, e.clientY) // 以松手的位置为准
    drag.current = null
    setGhost(null)
    setSwapTarget(null)
    if (d.mode === 'create') {
      if (!commit || !onCreate || !d.ghost) return
      const g = d.ghost
      if (d.pointerType === 'mouse') onCreate(days[d.anchorDay], g.start, g.duration)
      else if (Math.hypot(e.clientX - d.x0, e.clientY - d.y0) < 10) pendingTap.current = { date: days[d.anchorDay], start: g.start, duration: g.duration }
      return
    }
    const s = d.session!
    // 只有鼠标拖动后会紧跟一次 click;手指拖动后浏览器不发 click,不能留下「吞掉下一次点击」的标记
    if (d.moved && d.pointerType === 'mouse') suppressClick.current = true
    if (!commit) return
    const g = d.ghost
    if ((d.mode === 'top' || d.mode === 'bottom') && g && onResize) {
      if (g.start !== s.start_slot || g.duration !== s.duration_slots) onResize(s, g.start, g.duration)
      return
    }
    if (d.target && onSwap) {
      onSwap(s, d.target)
      return
    }
    if (d.moved && g && g.valid && onMove) {
      const date = days[g.dayIdx]
      if (date !== s.date || g.start !== s.start_slot) onMove(s, date, g.start)
    }
  }

  // 没有排练的日期收窄成细列(仍可作为拖动目标),把宽度让给有排练的日子
  const busy = days.map((d) => (byDay.get(d)?.length ?? 0) > 0)
  const collapse = busy.some(Boolean)
  const columns = `var(--hours-w) ${days.map((_, i) => (collapse && !busy[i] ? 'var(--empty-w)' : 'minmax(0, 1fr)')).join(' ')}`

  return (
    <div
      ref={gridRef}
      className={'weekgrid' + (editable ? ' is-editable' : '')}
      style={{ ['--rows' as string]: hours, gridTemplateColumns: columns }}
      onPointerDownCapture={() => {
        suppressClick.current = false // 新的一次按下:之前拖动留下的标记作废
      }}
    >
      <div className="weekgrid__corner" />
      {days.map((d) => {
        const inRange = d >= rangeStart && d <= rangeEnd
        const n = byDay.get(d)?.length ?? 0
        const empty = collapse && n === 0
        return (
          <button
            key={d}
            type="button"
            className={'weekgrid__day' + (d === today ? ' is-today' : '') + (inRange ? '' : ' is-off') + (empty ? ' is-empty' : '')}
            onClick={() => onDateClick?.(d)}
            disabled={!onDateClick}
            aria-label={`${dayjs(d).format('M月D日')} 周${WEEKDAYS[(dayjs(d).day() + 6) % 7]}${n ? `,${n} 场` : ''}`}
          >
            <span>{empty ? '' : '周'}{WEEKDAYS[(dayjs(d).day() + 6) % 7]}</span>
            <b>{dayjs(d).format(empty ? 'D' : 'M/D')}</b>
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
          <div
            key={d}
            className={
              'weekgrid__col' +
              (d >= rangeStart && d <= rangeEnd ? '' : ' is-off') +
              (collapse && list.length === 0 ? ' is-empty' : '') +
              (editable && onCreate && formalDay(d) ? ' is-creatable' : '')
            }
            onPointerDown={(e) => onColPointerDown(e, days.indexOf(d))}
            onClick={(e) => {
              const tap = pendingTap.current
              pendingTap.current = null
              if (tap && onCreate && !(e.target as HTMLElement).closest('[data-session-id]')) onCreate(tap.date, tap.start, tap.duration)
            }}
            onPointerMove={onPointerMove}
            onPointerUp={(e) => finishDrag(e, true)}
            onPointerCancel={(e) => finishDrag(e, false)}
          >
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
                    (canDrag(s) || canResize(s) ? ' is-draggable' : '') +
                    (dragging ? ' is-dragging' : '') +
                    (conflictIds?.has(s.id) ? ' is-conflict' : '') +
                    (swapTarget?.id === s.id ? ' is-swap-target' : '') +
                    (s.duration_slots <= 1 ? ' is-short' : '')
                  }
                  data-session-id={s.id}
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
                  title={`${s.time} ${s.song_name}${s.locked ? '(已锁定)' : ''}${conflictIds?.has(s.id) ? '(有冲突)' : ''}`}
                >
                  {swapTarget?.id === s.id && (
                    <i className="weekgrid__swap">
                      交换
                      {(() => {
                        // 交换后两场各自谁缺席:拖着的那场放到这场的时间,这场放到拖着那场原来的时间(各自时长不变)
                        const src = drag.current?.session
                        if (!src || !awayAt) return null
                        const a = awayAt(src, s.date, s.start_slot, src.duration_slots)
                        const b = awayAt(s, src.date, src.start_slot, s.duration_slots)
                        const notes = [a && a.away.length ? `${src.song_code}缺 ${a.away.join('、')}` : '', b && b.away.length ? `${s.song_code}缺 ${b.away.join('、')}` : '']
                        const text = notes.filter(Boolean).join(';')
                        return text ? ` · ${text}` : a && b ? ' · 全员可到' : null
                      })()}
                    </i>
                  )}
                  {canResize(s) && (
                    <>
                      <i className="weekgrid__handle weekgrid__handle--top" data-handle="top" aria-hidden="true" />
                      <i className="weekgrid__handle weekgrid__handle--bottom" data-handle="bottom" aria-hidden="true" />
                    </>
                  )}
                  <b>
                    {conflictIds?.has(s.id) && <i className="weekgrid__alert" aria-label="有冲突">!</i>}
                    {s.locked && <i className="lock" aria-label="已锁定" />}
                    {s.kind === 'evaluation' ? '评估' : s.song_code}
                  </b>
                  {/* 代号与名称相同时不重复显示 */}
                  {(s.kind === 'evaluation' || s.song_name !== s.song_code) && <span>{s.kind === 'evaluation' ? '全员' : s.song_name}</span>}
                  {/* 电脑端直接显示参演成员;缺席的单独标出 */}
                  {s.kind === 'formal' && (
                    <em className="weekgrid__names">
                      {s.members
                        .filter((m) => !s.absent.some((a) => a.id === m.id))
                        .map((m) => m.display_name)
                        .join('、')}
                      {s.absent.length > 0 && <i className="weekgrid__absent"> · 缺 {s.absent.map((m) => m.display_name).join('、')}</i>}
                    </em>
                  )}
                  {laneCount === 1 && (
                    <small>
                      <span className="weekgrid__time-full">{s.time}</span>
                      <span className="weekgrid__time-short">
                        {dayStartHour + s.start_slot}–{dayStartHour + s.start_slot + s.duration_slots}
                      </span>
                    </small>
                  )}
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
          <b>{ghost.mode === 'create' ? '新建排练' : drag.current.session?.song_code}</b>
          <span>
            {String(dayStartHour + ghost.start).padStart(2, '0')}:00–{String(dayStartHour + ghost.start + ghost.duration).padStart(2, '0')}:00 · {ghost.duration}h
          </span>
          {(() => {
            // 拖动时实时显示:松手后这些人会记为缺席(标签放在框外,不挤占时间文字)
            const s = drag.current.session
            const away = ghost.valid && ghost.mode !== 'create' && s && awayAt ? awayAt(s, days[ghost.dayIdx], ghost.start, ghost.duration) : null
            if (away == null) return null
            const { text, tone } = awayText(away)
            return <em className={'weekgrid__away' + tone}>{text}</em>
          })()}
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
