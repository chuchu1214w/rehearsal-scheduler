import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'

import type { Availability } from '../api/types'
import { Button, Note } from '../ui'
import { fmtMd, hourLabel, weekdayShort } from '../utils'

export type Brush = '1' | '2' | '0'
export const BRUSH_NAMES: Record<Brush, string> = { '1': '可排', '2': '尽量避开', '0': '不可排' }

interface Props {
  availability: Availability
  days: Record<string, string>
  onChange: (days: Record<string, string>) => void
}

export function countFilled(days: Record<string, string>): number {
  return Object.values(days).filter((v) => /[12]/.test(v)).length
}

export function AvailabilityGrid({ availability, days, onChange }: Props) {
  const dates = availability.dates
  const [dayIndex, setDayIndex] = useState(0)
  const [brush, setBrush] = useState<Brush>('1')
  const drawing = useRef(false)
  const lastSlot = useRef(-1)
  const swipe = useRef<{ x: number; y: number } | null>(null)
  const daysRef = useRef(days)
  daysRef.current = days

  const date = dates[dayIndex]
  const row = days[date] ?? '0'.repeat(availability.slots_per_day)
  const isEval = date === availability.eval_date

  const setSlot = (slot: number, value: Brush) => {
    const cur = daysRef.current[date] ?? '0'.repeat(availability.slots_per_day)
    if (cur[slot] === value) return
    const next = cur.slice(0, slot) + value + cur.slice(slot + 1)
    onChange({ ...daysRef.current, [date]: next })
  }
  const setWhole = (value: Brush) => onChange({ ...days, [date]: value.repeat(availability.slots_per_day) })
  const copyPrev = () => {
    if (dayIndex === 0) return
    onChange({ ...days, [date]: days[dates[dayIndex - 1]] ?? '0'.repeat(availability.slots_per_day) })
  }

  const paintAt = (x: number, y: number) => {
    const el = document.elementFromPoint(x, y) as HTMLElement | null
    const slot = el?.closest<HTMLElement>('[data-slot]')
    if (!slot) return
    const idx = Number(slot.dataset.slot)
    if (idx === lastSlot.current) return
    lastSlot.current = idx
    setSlot(idx, brush)
  }
  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    const slot = (e.target as HTMLElement).closest<HTMLElement>('[data-slot]')
    if (!slot) return
    e.preventDefault()
    drawing.current = true
    lastSlot.current = -1
    paintAt(e.clientX, e.clientY)
  }
  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (drawing.current) paintAt(e.clientX, e.clientY)
  }
  useEffect(() => {
    const up = () => {
      drawing.current = false
      lastSlot.current = -1
    }
    window.addEventListener('pointerup', up)
    window.addEventListener('pointercancel', up)
    return () => {
      window.removeEventListener('pointerup', up)
      window.removeEventListener('pointercancel', up)
    }
  }, [])

  // 日期条:显示 5 天,可左右滑动
  const start = Math.min(Math.max(dayIndex - 2, 0), Math.max(0, dates.length - 5))
  const visible = dates.slice(start, start + 5)
  const onStripDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    swipe.current = { x: e.clientX, y: e.clientY }
  }
  const onStripUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!swipe.current) return
    const dx = e.clientX - swipe.current.x
    const dy = e.clientY - swipe.current.y
    swipe.current = null
    if (Math.abs(dx) > 35 && Math.abs(dx) > Math.abs(dy)) setDayIndex((i) => Math.max(0, Math.min(dates.length - 1, i + (dx < 0 ? 1 : -1))))
  }

  return (
    <>
      <div className="dates" aria-label="日期选择,可横向滑动" onPointerDown={onStripDown} onPointerUp={onStripUp}>
        <button type="button" aria-label="前一天" disabled={dayIndex === 0} onClick={() => setDayIndex(dayIndex - 1)}>
          ‹
        </button>
        {visible.map((d) => {
          const i = dates.indexOf(d)
          const filled = /[12]/.test(days[d] ?? '')
          return (
            <button key={d} type="button" aria-pressed={i === dayIndex} className={d === availability.eval_date ? 'is-eval' : ''} onClick={() => setDayIndex(i)}>
              <span>{d === availability.eval_date ? '评估' : `周${weekdayShort(d)}`}</span>
              <strong>{fmtMd(d)}</strong>
              <span>{filled ? '已填' : '·'}</span>
            </button>
          )
        })}
        <button type="button" aria-label="后一天" disabled={dayIndex === dates.length - 1} onClick={() => setDayIndex(dayIndex + 1)}>
          ›
        </button>
      </div>
      {isEval && <Note>{fmtMd(date)} 是全员评估日,只需 2–3 小时。请尽量留出连续时段。</Note>}
      <div className="brushes" aria-label="空闲状态画笔">
        {(['1', '2', '0'] as Brush[]).map((b) => (
          <button key={b} type="button" aria-pressed={brush === b} onClick={() => setBrush(b)}>
            <span className={'dot' + (b === '1' ? ' dot--free' : b === '2' ? ' dot--avoid' : '')} />
            {BRUSH_NAMES[b]}
          </button>
        ))}
      </div>
      <div className="quick">
        <Button variant="ghost" small disabled={dayIndex === 0} onClick={copyPrev}>
          复制上一天
        </Button>
        <Button variant="ghost" small onClick={() => setWhole('1')}>
          全天可排
        </Button>
        <Button variant="ghost" small onClick={() => setWhole('0')}>
          全天不可排
        </Button>
      </div>
      <div className="hours" aria-label={`${fmtMd(date)} 每小时的空闲状态`} onPointerDown={onPointerDown} onPointerMove={onPointerMove}>
        {Array.from({ length: availability.slots_per_day }, (_, i) => {
          const hour = availability.day_start_hour + i
          const v = (row[i] ?? '0') as Brush
          return (
            <div key={i} className="hour">
              <span className="hour__time">
                {hourLabel(hour)}–{hourLabel(hour + 1)}
              </span>
              <button type="button" className="slot" data-slot={i} data-value={v} aria-label={`${fmtMd(date)} ${hourLabel(hour)} 至 ${hourLabel(hour + 1)},${BRUSH_NAMES[v]}`}>
                {BRUSH_NAMES[v]}
              </button>
            </div>
          )
        })}
      </div>
    </>
  )
}
