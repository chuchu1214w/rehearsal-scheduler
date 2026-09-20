import dayjs from 'dayjs'

export const USERNAME_PATTERN = /^[A-Za-z0-9_.\-一-鿿]{2,32}$/

export function fmtDate(value: string): string {
  return dayjs(value).format('M月D日 ddd')
}

export function fmtDateTime(value: string | null): string {
  if (!value) return '—'
  // 后端存 UTC naive,补上 Z 再转本地
  return dayjs(value.endsWith('Z') ? value : value + 'Z').format('YYYY-MM-DD HH:mm')
}

export function planText(plan: number[]): string {
  return plan.map((h) => `${h}h`).join(' + ')
}

export function parsePlan(text: string): number[] | null {
  const trimmed = text.trim()
  if (!trimmed) return null
  return trimmed
    .split(/[,，、\s+]+/)
    .filter(Boolean)
    .map((x) => Number(x))
}

export function hourLabel(hour: number): string {
  return `${String(hour % 24).padStart(2, '0')}:00`
}
