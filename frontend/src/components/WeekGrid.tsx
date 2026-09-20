import dayjs from 'dayjs'

import type { ScheduleSession } from '../api/types'

/** 课程表式周视图:列 = 一周七天,行 = 小时;场次按曲目着色,评估场用主色。 */

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
}

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']

export function WeekGrid({ weekStart, sessions, dayStartHour, dayEndHour, songOrder, rangeStart, rangeEnd, focusMemberId = null, onDateClick, onSessionClick }: Props) {
  const hours = dayEndHour - dayStartHour
  const today = dayjs().format('YYYY-MM-DD')
  const days = Array.from({ length: 7 }, (_, i) => dayjs(weekStart).add(i, 'day').format('YYYY-MM-DD'))
  const byDay = new Map<string, ScheduleSession[]>()
  for (const s of sessions) byDay.set(s.date, [...(byDay.get(s.date) ?? []), s])

  return (
    <div className="weekgrid" style={{ ['--rows' as string]: hours }}>
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
              return (
                <button
                  key={s.id}
                  type="button"
                  className={'weekgrid__block' + (s.kind === 'evaluation' ? ' is-eval' : '') + (dim ? ' is-dim' : '')}
                  style={{
                    top: `calc(${s.start_slot} * var(--row-h))`,
                    height: `calc(${s.duration_slots} * var(--row-h) - 2px)`,
                    left: `${lane * width}%`,
                    width: `calc(${width}% - 2px)`,
                    background: c.bg,
                    color: c.ink,
                  }}
                  onClick={() => onSessionClick?.(s)}
                  title={`${s.time} ${s.song_name}`}
                >
                  <b>{s.kind === 'evaluation' ? '评估' : s.song_code}</b>
                  <span>{s.kind === 'evaluation' ? '全员' : s.song_name}</span>
                  {laneCount === 1 && <small>{s.time}</small>}
                </button>
              )
            })}
          </div>
        )
      })}
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
