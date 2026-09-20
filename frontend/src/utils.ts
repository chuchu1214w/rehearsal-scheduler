import dayjs from 'dayjs'

import type { Difficulty, EventSettings } from './api/types'

export const USERNAME_PATTERN = /^[A-Za-z0-9_.\-一-鿿]{1,32}$/

export function fmtMd(value: string): string {
  const d = dayjs(value)
  return `${d.month() + 1}/${d.date()}`
}

export function fmtDate(value: string): string {
  return dayjs(value).format('M月D日 ddd')
}

export function fmtDateTime(value: string | null): string {
  if (!value) return '—'
  return dayjs(value.endsWith('Z') ? value : value + 'Z').format('M/D HH:mm')
}

export function weekdayShort(value: string): string {
  return ['日', '一', '二', '三', '四', '五', '六'][dayjs(value).day()]
}

export function hourLabel(hour: number): string {
  return `${String(hour % 24).padStart(2, '0')}:00`
}

/** [3,2,2] → "1 场 3h + 2 场 2h";[2,2] → "2 场 × 2h" */
export function planText(plan: number[]): string {
  const counts = new Map<number, number>()
  for (const h of plan) counts.set(h, (counts.get(h) ?? 0) + 1)
  const parts = [...counts.entries()].sort((a, b) => b[0] - a[0]).map(([h, n]) => `${n} 场 × ${h}h`)
  if (parts.length === 1) return parts[0]
  return [...counts.entries()].sort((a, b) => b[0] - a[0]).map(([h, n]) => (n === 1 ? `1 场 ${h}h` : `${n} 场 ${h}h`)).join(' + ')
}

/** 解析 "3,2" / "3h+2h" / "1 场 3h + 2 场 2h" 为 [3,2,2];无法解析返回 null */
export function parsePlan(text: string): number[] | null {
  const t = text.trim()
  if (!t) return null
  const out: number[] = []
  const groups = t.split(/[+,，、]/)
  for (const g of groups) {
    const m = g.match(/(?:(\d+)\s*场\s*[×x*]?\s*)?(\d+)\s*h?/i)
    if (!m) return null
    const n = m[1] ? Number(m[1]) : 1
    const h = Number(m[2])
    if (!Number.isInteger(n) || !Number.isInteger(h) || n < 1 || h < 1) return null
    for (let i = 0; i < n; i++) out.push(h)
  }
  return out.length ? out : null
}

export function templatePlan(settings: EventSettings, difficulty: Difficulty): number[] {
  return settings.difficulty_templates[difficulty] ?? []
}

export function daysUntilText(days: number): string {
  if (days > 0) return `距演出 ${days} 天`
  if (days === 0) return '今天演出'
  return `演出已过 ${-days} 天`
}

export function splitNames(text: string): string[] {
  return text
    .split(/[，,、\n\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

export function blankSlots(n: number): string {
  return '0'.repeat(n)
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}
