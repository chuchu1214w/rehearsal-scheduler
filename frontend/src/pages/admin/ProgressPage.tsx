import { Fragment, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api } from '../../api/client'
import type { RemindResult } from '../../api/types'
import { useEvent, useEventMembers, useHeat } from '../../api/hooks'
import type { Heat } from '../../api/types'
import { Back, Badge, Button, Heading, KV, LinkButton, Panel, Spinner } from '../../ui'
import { useToast } from '../../ui/Toast'
import { copyText, fmtDateTime, fmtMd, hourLabel, weekdayShort } from '../../utils'

type Cell = { date: string; slot: number }

/** 某人某格的状态:'1' 有空 / '2' 尽量避开 / '0' 没空;未提交视为没空 */
function status(heat: Heat, name: string, date: string, slot: number): string {
  return heat.availability[name]?.[date]?.[slot] ?? '0'
}

/** 把一天里“全员都有空”的格子合并成时段 */
function commonRanges(heat: Heat, names: string[], date: string) {
  const out: { start: number; end: number; avoid: boolean }[] = []
  for (let h = 0; h < heat.slots_per_day; h++) {
    const st = names.map((n) => status(heat, n, date, h))
    if (names.length === 0 || st.some((x) => x !== '1' && x !== '2')) continue
    const avoid = st.includes('2')
    const last = out[out.length - 1]
    if (last && last.end === h) {
      last.end = h + 1
      last.avoid ||= avoid
    } else out.push({ start: h, end: h + 1, avoid })
  }
  return out
}

function HeatMap({ heat }: { heat: Heat }) {
  const [page, setPage] = useState(0)
  const [songCode, setSongCode] = useState('')
  const [cell, setCell] = useState<Cell | null>(null)
  const per = 7
  const pages = Math.ceil(heat.dates.length / per)
  const dates = heat.dates.slice(page * per, page * per + per)
  const song = heat.songs.find((s) => s.code === songCode) ?? null
  const submitted = Object.keys(heat.availability)
  const scope = song ? song.members : submitted
  const notSubmitted = song ? song.members.filter((m) => !(m in heat.availability)) : []
  const max = Math.max(1, scope.length)
  const count = (d: string, h: number) => scope.filter((n) => ['1', '2'].includes(status(heat, n, d, h))).length
  const longest = song ? Math.max(...song.durations, 0) : 0

  return (
    <>
      <div className="heat-filter">
        <select
          value={songCode}
          onChange={(e) => {
            setSongCode(e.target.value)
            setCell(null)
          }}
          aria-label="按曲目查看"
        >
          <option value="">全员({submitted.length} 人已提交)</option>
          {heat.songs.map((s) => (
            <option key={s.code} value={s.code}>
              {s.code} · {s.name}({s.members.length} 人)
            </option>
          ))}
        </select>
        <span className="muted">{song ? '数字 = 该曲目成员中有空的人数;描边 = 全员有空' : '点格子查看这一小时谁有空'}</span>
      </div>
      {notSubmitted.length > 0 && <p className="muted">还没提交空闲(按没空计算):{notSubmitted.join('、')}</p>}
      <div className="heat" style={{ gridTemplateColumns: `34px repeat(${dates.length}, minmax(0, 1fr))` }}>
        <span />
        {dates.map((d) => (
          <span key={d}>
            {fmtMd(d)}
            <br />
            {weekdayShort(d)}
          </span>
        ))}
        {Array.from({ length: heat.slots_per_day }, (_, h) => (
          <Fragment key={h}>
            <span>{hourLabel(heat.day_start_hour + h)}</span>
            {dates.map((d) => {
              const n = count(d, h)
              const all = song != null && n === scope.length && n > 0
              const picked = cell?.date === d && cell.slot === h
              return (
                <button
                  key={d}
                  type="button"
                  className={'heat__cell' + (all ? ' is-all' : '') + (picked ? ' is-picked' : '')}
                  style={{ background: `color-mix(in srgb, var(--accent) ${Math.round((n / max) * 70) + (n ? 8 : 0)}%, var(--paper))`, color: n / max > 0.55 ? '#fff' : undefined }}
                  title={`${n} 人有空`}
                  aria-label={`${fmtMd(d)} ${hourLabel(heat.day_start_hour + h)},${n} 人有空`}
                  onClick={() => setCell(picked ? null : { date: d, slot: h })}
                >
                  {n}
                </button>
              )
            })}
          </Fragment>
        ))}
      </div>
      {pages > 1 && (
        <div className="heat-nav">
          <Button small disabled={page === 0} onClick={() => setPage(page - 1)}>
            ‹ 前 7 天
          </Button>
          <span className="muted">
            {page + 1} / {pages}
          </span>
          <Button small disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>
            后 7 天 ›
          </Button>
        </div>
      )}
      {cell && <WhoIsFree heat={heat} names={scope} cell={cell} title={song ? `${song.code} · ${song.name}` : '全员'} />}
      {song && (
        <div className="heat-common">
          <div className="kicker">
            {song.code} · {song.name} 的共同有空时间 · 场次方案 {song.durations.map((x) => `${x}h`).join(' + ')}
          </div>
          {(() => {
            const days = heat.dates.map((d) => ({ d, ranges: commonRanges(heat, song.members, d) })).filter((x) => x.ranges.length > 0)
            if (days.length === 0) return <p className="muted">没有任何一个小时是全员都有空的。</p>
            return (
              <ul>
                {days.map(({ d, ranges }) => (
                  <li key={d}>
                    <b>
                      {fmtMd(d)} 周{weekdayShort(d)}
                    </b>
                    {ranges.map((r, i) => {
                      const len = r.end - r.start
                      return (
                        <span key={i} className={'heat-common__range' + (len >= longest ? ' is-long' : '')}>
                          {hourLabel(heat.day_start_hour + r.start)}–{hourLabel(heat.day_start_hour + r.end)}({len}h{r.avoid ? ',含尽量避开' : ''})
                        </span>
                      )
                    })}
                  </li>
                ))}
              </ul>
            )
          })()}
          <p className="muted">加粗的时段够排最长的一场({longest}h)。</p>
        </div>
      )}
    </>
  )
}

function WhoIsFree({ heat, names, cell, title }: { heat: Heat; names: string[]; cell: Cell; title: string }) {
  const groups: Record<string, string[]> = { '1': [], '2': [], '0': [] }
  for (const n of names) groups[status(heat, n, cell.date, cell.slot)]?.push(n)
  const h = heat.day_start_hour + cell.slot
  return (
    <div className="heat-who">
      <div className="kicker">
        {fmtMd(cell.date)} 周{weekdayShort(cell.date)} {hourLabel(h)}–{hourLabel(h + 1)} · {title}
      </div>
      <p>
        <b>有空({groups['1'].length}):</b>
        {groups['1'].join('、') || '无'}
      </p>
      {groups['2'].length > 0 && (
        <p>
          <b>尽量避开({groups['2'].length}):</b>
          {groups['2'].join('、')}
        </p>
      )}
      <p className="muted">
        <b>没空({groups['0'].length}):</b>
        {groups['0'].join('、') || '无'}
      </p>
    </div>
  )
}

export function ProgressPage() {
  const id = Number(useParams().id)
  const ev = useEvent(id)
  const members = useEventMembers(id)
  const heat = useHeat(id)
  const { toast } = useToast()
  if (ev.isPending || members.isPending) return <Spinner />
  if (!ev.data) return null
  const e = ev.data
  const list = members.data ?? []
  const pending = list.filter((m) => !m.availability_submitted_at)
  const submitted = list.filter((m) => m.availability_submitted_at)
  const pct = list.length ? Math.round((submitted.length / list.length) * 100) : 0
  const remind = async () => {
    const r = await api<RemindResult>(`/api/events/${e.id}/remind`, { method: 'POST' })
    const parts: string[] = []
    if (r.notified.length) parts.push(`已通知 ${r.notified.join('、')}`)
    if (r.without_account.length) {
      const copied = await copyText(r.copy_text)
      parts.push(`${r.without_account.join('、')} 没有账号${copied ? ',催办文案已复制,发到群里即可' : `:${r.copy_text}`}`)
    }
    toast(parts.join(';') || '没有需要催办的人')
  }
  return (
    <>
      <Back to={`/events/${e.id}`} label={`${e.name} · 工作台`} />
      <Heading title="填报进度" subtitle="未提交人员置顶;必要时可代填。" action={<LinkButton to={`/events/${e.id}/solve`} variant="primary">去排程</LinkButton>} />
      <Panel>
        <div className="section">
          <h2>
            已提交 {submitted.length} / {list.length}
          </h2>
          {pending.length > 0 && <Button onClick={() => void remind()}>催办未提交人员</Button>}
        </div>
        <div className="progressbar" role="progressbar" aria-valuenow={submitted.length} aria-valuemax={list.length} aria-valuemin={0}>
          <span style={{ width: `${pct}%` }} />
        </div>
        {e.availability_deadline && (
          <p className="muted" style={{ marginBottom: 8 }}>
            填报截止 {fmtMd(e.availability_deadline)}{e.days_until_performance >= 0 ? '' : ''} · 到期只提醒不锁定,成员仍可修改
          </p>
        )}
        <div className="rows">
          {pending.map((m) => (
            <div key={m.member_id} className="row">
              <KV label="未提交" title>
                {m.display_name}
              </KV>
              <KV label="账号">{m.account ? <Badge tone="green">已开通</Badge> : <Badge tone="neutral">未开通</Badge>}</KV>
              <KV label="操作">
                <span className="inline">
                  {!m.account && (
                    <Link to={`/events/${e.id}/people`} className="btn btn--ghost btn--sm">
                      去开通账号
                    </Link>
                  )}
                  <Link to={`/events/${e.id}/availability/${m.member_id}`} className="btn btn--ghost btn--sm">
                    {m.availability_filled_days > 0 ? `代填(已填 ${m.availability_filled_days} 天)` : '代填'}
                  </Link>
                </span>
              </KV>
            </div>
          ))}
          {pending.length === 0 && list.length > 0 && <p className="muted" style={{ padding: '10px 0' }}>全员已提交。</p>}
        </div>
        <details open={pending.length === 0}>
          <summary>已提交 · {submitted.length} 人</summary>
          <div className="rows">
            {submitted.map((m) => (
              <div key={m.member_id} className="row">
                <KV label="成员" title>
                  {m.display_name}
                </KV>
                <KV label="提交时间">{fmtDateTime(m.availability_submitted_at)}</KV>
                <KV label="来源">
                  {m.availability_filled_by === 'admin' ? '管理员代填' : '本人提交'} · 已填 {m.availability_filled_days} 天 ·{' '}
                  <Link to={`/events/${e.id}/availability/${m.member_id}`}>查看</Link>
                </KV>
              </div>
            ))}
          </div>
        </details>
      </Panel>
      <Panel>
        <div className="section">
          <h3>空闲热力图</h3>
          <span className="muted">每格 = 该小时有空的人数(含尽量避开,只统计已提交)</span>
        </div>
        {heat.data ? <HeatMap heat={heat.data} /> : <Spinner />}
      </Panel>
    </>
  )
}
