import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { useEvent, useEventMembers, useHeat } from '../../api/hooks'
import type { Heat } from '../../api/types'
import { Back, Badge, Button, Heading, KV, LinkButton, Panel, Spinner } from '../../ui'
import { useToast } from '../../ui/Toast'
import { copyText, fmtDateTime, fmtMd, hourLabel, weekdayShort } from '../../utils'

function HeatMap({ heat }: { heat: Heat }) {
  const [page, setPage] = useState(0)
  const per = 7
  const pages = Math.ceil(heat.dates.length / per)
  const dates = heat.dates.slice(page * per, page * per + per)
  const max = Math.max(1, heat.submitted_count)
  return (
    <>
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
          <FragmentRow key={h} hour={heat.day_start_hour + h} values={dates.map((d) => heat.heat[d]?.[h] ?? 0)} max={max} />
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
    </>
  )
}

function FragmentRow({ hour, values, max }: { hour: number; values: number[]; max: number }) {
  return (
    <>
      <span>{hourLabel(hour)}</span>
      {values.map((n, i) => (
        <b key={i} style={{ background: `color-mix(in srgb, var(--accent) ${Math.round((n / max) * 70) + (n ? 8 : 0)}%, var(--paper))`, color: n / max > 0.55 ? '#fff' : undefined }} title={`${n} 人有空`}>
          {n}
        </b>
      ))}
    </>
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
    const names = pending.map((m) => m.display_name).join('、')
    const text = `${names}:请在 ${e.availability_deadline ? fmtMd(e.availability_deadline) : '尽快'} 前登录 Season 填写空闲时间,谢谢!`
    toast((await copyText(text)) ? '催办文案已复制,发到群里即可' : text)
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
          <h3>全员空闲热力图</h3>
          <span className="muted">每格 = 该小时可排人数(只统计已提交)</span>
        </div>
        {heat.data ? <HeatMap heat={heat.data} /> : <Spinner />}
      </Panel>
    </>
  )
}
