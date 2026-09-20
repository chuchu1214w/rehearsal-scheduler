import dayjs from 'dayjs'

import type { RehearsalEvent } from '../api/types'

/** 成员端的“当前演出”:未结束且演出日期最近的一场(同一天时优先已发布排练表的);都结束了就取最近结束的。 */
export function pickCurrentEvent(events: RehearsalEvent[], preferredId?: number | null): RehearsalEvent | null {
  if (!events.length) return null
  if (preferredId != null) {
    const hit = events.find((e) => e.id === preferredId)
    if (hit) return hit
  }
  const today = dayjs().startOf('day')
  const upcoming = events
    .filter((e) => e.status !== 'closed' && !dayjs(e.performance_date).isBefore(today))
    .sort((a, b) => a.performance_date.localeCompare(b.performance_date) || Number(b.published_version_no != null) - Number(a.published_version_no != null) || b.id - a.id)
  if (upcoming.length) return upcoming[0]
  return [...events].sort((a, b) => b.performance_date.localeCompare(a.performance_date))[0]
}
