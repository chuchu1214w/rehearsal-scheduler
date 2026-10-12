import dayjs from 'dayjs'

import type { ScheduleSession } from './api/types'
import { splitLocation } from './components/MapLink'
import { songColor } from './components/WeekGrid'
import { isNative } from './native'

/** 把排练表画成一张按日期排列的长图,用于分享到微信等(开发文档 §4 排练表分享)。 */

interface ImageInput {
  eventName: string
  subtitle: string
  sessions: ScheduleSession[]
  songOrder: string[]
}

const W = 1080
const PAD = 56
const FONT = '-apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Noto Sans SC", "Microsoft YaHei", sans-serif'
const C = { bg: '#fef0fb', card: '#ffffff', ink: '#262a33', muted: '#6b7080', line: '#ecdde8', accent: '#5369af', red: '#b4475a' }
const WEEK = ['日', '一', '二', '三', '四', '五', '六']

/** 按字符折行(中文没有空格,逐字测量) */
function wrap(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
  const lines: string[] = []
  let line = ''
  for (const ch of text) {
    if (ctx.measureText(line + ch).width > maxWidth && line) {
      lines.push(line)
      line = ch
    } else line += ch
  }
  if (line) lines.push(line)
  return lines.length ? lines : ['']
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + w, y, x + w, y + h, r)
  ctx.arcTo(x + w, y + h, x, y + h, r)
  ctx.arcTo(x, y + h, x, y, r)
  ctx.arcTo(x, y, x + w, y, r)
  ctx.closePath()
}

/** 布局与绘制共用一套逻辑:draw=false 时只计算总高度 */
function layout(ctx: CanvasRenderingContext2D, input: ImageInput, draw: boolean): number {
  const text = (s: string, x: number, y: number, size: number, color: string, weight = 400) => {
    ctx.font = `${weight} ${size}px ${FONT}`
    if (draw) {
      ctx.fillStyle = color
      ctx.fillText(s, x, y)
    }
  }
  let y = PAD
  ctx.textBaseline = 'top'
  text(input.eventName, PAD, y, 46, C.ink, 700)
  y += 64
  text(input.subtitle, PAD, y, 26, C.muted)
  y += 56

  const byDate = new Map<string, ScheduleSession[]>()
  for (const s of [...input.sessions].sort((a, b) => a.date.localeCompare(b.date) || a.start_slot - b.start_slot)) {
    byDate.set(s.date, [...(byDate.get(s.date) ?? []), s])
  }
  const cardX = PAD
  const cardW = W - PAD * 2
  const timeW = 250
  const bodyX = cardX + 28 + timeW
  const bodyW = cardW - 28 - timeW - 24

  for (const [date, list] of byDate) {
    const d = dayjs(date)
    text(`${d.month() + 1}月${d.date()}日 周${WEEK[d.day()]}`, PAD, y, 32, C.accent, 700)
    y += 52
    for (const s of list) {
      const color = songColor(s.kind === 'evaluation' ? null : s.song_code, input.songOrder)
      const title = s.kind === 'evaluation' ? '全员评估' : s.song_name && s.song_name !== s.song_code ? `${s.song_code} · ${s.song_name}` : (s.song_code ?? s.song_name)
      ctx.font = `700 32px ${FONT}`
      const titleLines = wrap(ctx, title, bodyW)
      const present = s.members.filter((m) => !s.absent.some((a) => a.id === m.id)).map((m) => m.display_name)
      ctx.font = `400 26px ${FONT}`
      const memberLines = s.kind === 'evaluation' ? ['全员'] : wrap(ctx, present.join('、') || '—', bodyW)
      const absentLines = s.absent.length ? wrap(ctx, `缺席:${s.absent.map((m) => m.display_name).join('、')}`, bodyW) : []
      const loc = s.location ? splitLocation(s.location).text || 'Naver 地图链接' : ''
      const locLines = loc ? wrap(ctx, `地点:${loc}`, bodyW) : []
      const h = 26 + titleLines.length * 44 + 8 + (memberLines.length + absentLines.length + locLines.length) * 38 + 22
      if (draw) {
        roundRect(ctx, cardX, y, cardW, h, 22)
        ctx.fillStyle = C.card
        ctx.fill()
        ctx.strokeStyle = C.line
        ctx.lineWidth = 2
        ctx.stroke()
        roundRect(ctx, cardX, y, 12, h, 6)
        ctx.fillStyle = s.kind === 'evaluation' ? C.accent : color.ink
        ctx.fill()
      }
      let ty = y + 26
      text(s.time, cardX + 32, ty + 2, 30, C.ink, 600)
      text(`${s.duration_slots} 小时`, cardX + 32, ty + 44, 24, C.muted)
      for (const l of titleLines) {
        text(l, bodyX, ty, 32, s.kind === 'evaluation' ? C.accent : color.ink, 700)
        ty += 44
      }
      ty += 8
      for (const l of memberLines) {
        text(l, bodyX, ty, 26, C.ink)
        ty += 38
      }
      for (const l of absentLines) {
        text(l, bodyX, ty, 26, C.red)
        ty += 38
      }
      for (const l of locLines) {
        text(l, bodyX, ty, 26, C.muted)
        ty += 38
      }
      y += h + 16
    }
    y += 20
  }
  if (byDate.size === 0) {
    text('这一版没有场次', PAD, y, 28, C.muted)
    y += 60
  }
  text(`Season 排练排程 · ${dayjs().format('M月D日 HH:mm')} 生成`, PAD, y + 8, 22, C.muted)
  return y + 8 + 22 + PAD
}

export async function renderScheduleImage(input: ImageInput): Promise<Blob> {
  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('无法生成图片')
  const height = layout(ctx, input, false)
  // iOS 对画布总像素有上限(约 1600 万),超长时整体缩小
  const scale = Math.min(1, 15_000_000 / (W * height))
  canvas.width = Math.floor(W * scale)
  canvas.height = Math.floor(height * scale)
  ctx.scale(scale, scale)
  ctx.fillStyle = C.bg
  ctx.fillRect(0, 0, W, height)
  layout(ctx, input, true)
  return new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('无法生成图片'))), 'image/png'))
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '')
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(blob)
  })
}

/** 交给系统分享面板(可选微信);电脑浏览器不支持分享图片时直接下载。返回实际采用的方式。 */
export async function shareImage(blob: Blob, filename: string, title: string): Promise<'shared' | 'downloaded' | 'cancelled'> {
  if (isNative()) {
    const [{ Filesystem, Directory }, { Share }] = await Promise.all([import('@capacitor/filesystem'), import('@capacitor/share')])
    const saved = await Filesystem.writeFile({ path: filename, data: await blobToBase64(blob), directory: Directory.Cache })
    try {
      await Share.share({ title, files: [saved.uri] })
      return 'shared'
    } catch {
      return 'cancelled' // 用户关掉了分享面板
    }
  }
  const file = new File([blob], filename, { type: 'image/png' })
  if (navigator.canShare?.({ files: [file] })) {
    try {
      await navigator.share({ files: [file], title })
      return 'shared'
    } catch (err) {
      if ((err as Error).name === 'AbortError') return 'cancelled'
    }
  }
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
  return 'downloaded'
}
