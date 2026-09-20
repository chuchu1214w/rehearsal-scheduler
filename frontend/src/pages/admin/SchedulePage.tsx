import { useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'

import { useEvent, useVersion, useVersions } from '../../api/hooks'
import type { ScheduleSession, ScheduleVersion, ScheduleVersionDetail } from '../../api/types'
import { Back, Badge, Heading, LinkButton, Note, Panel, Spinner, Tabs } from '../../ui'
import { fmtDateTime, fmtMd } from '../../utils'

type View = 'sessions' | 'members'

export function SchedulePage() {
  const id = Number(useParams().id)
  const [params, setParams] = useSearchParams()
  const [view, setView] = useState<View>('sessions')
  const ev = useEvent(id)
  const versions = useVersions(id)
  const list = versions.data ?? []
  const requested = Number(params.get('v'))
  const selectedId = list.some((v) => v.id === requested) ? requested : (list[0]?.id ?? null)
  const detail = useVersion(selectedId)

  if (ev.isPending || versions.isPending) return <Spinner />
  if (!ev.data) return null
  const e = ev.data

  if (list.length === 0) {
    return (
      <>
        <Back to={`/events/${e.id}`} label={`${e.name} · 工作台`} />
        <Heading title="排练表" subtitle="草稿仅管理员可见,校验通过后再发布。" />
        <Panel>
          <Badge tone="neutral">尚未生成</Badge>
          <h2 style={{ marginTop: 15 }}>排程完成后,排练表会出现在这里</h2>
          <p className="muted" style={{ marginTop: 8 }}>
            正规排练 {fmtMd(e.formal_start_date)}–{fmtMd(e.formal_end_date)},全员评估 {fmtMd(e.eval_date)}。
          </p>
          <div className="actions">
            <LinkButton to={`/events/${e.id}/solve`} variant="primary">
              去排程
            </LinkButton>
          </div>
        </Panel>
      </>
    )
  }

  const current = list.find((v) => v.id === selectedId) ?? list[0]
  return (
    <>
      <Back to={`/events/${e.id}`} label={`${e.name} · 工作台`} />
      <Heading title="排练表" subtitle={`正规排练 ${fmtMd(e.formal_start_date)}–${fmtMd(e.formal_end_date)},全员评估 ${fmtMd(e.eval_date)}。`} />

      <Panel>
        <div className="version-bar">
          <select value={current.id} onChange={(ev2) => setParams({ v: ev2.target.value })} aria-label="选择版本">
            {list.map((v) => (
              <option key={v.id} value={v.id}>
                v{v.version_no} · {versionLabel(v)}
              </option>
            ))}
          </select>
          <Badge tone={current.status === 'published' ? 'green' : 'neutral'}>{current.status === 'published' ? '已发布' : current.status === 'archived' ? '已归档' : '草稿'}</Badge>
          {current.level_used != null && <Badge tone={current.level_used === 0 ? 'green' : 'orange'}>{current.level_used === 0 ? '无计划外缺席' : `缺席层级 L${current.level_used}`}</Badge>}
          <Badge tone={current.exact_optimum ? 'accent' : 'orange'}>{current.exact_optimum ? '严格最优' : '非严格最优'}</Badge>
        </div>
        <p className="muted" style={{ marginTop: 8 }}>
          {current.session_count} 场 · 生成于 {fmtDateTime(current.created_at)}
        </p>
        {current.skipped_songs.length > 0 && <Note tone="warning">这一版跳过了曲目 {current.skipped_songs.join('、')}(求解时参演人员尚未全部提交空闲)。</Note>}
        {current.validation_errors.length > 0 && (
          <Note tone="error">
            校验未通过:
            <ul style={{ margin: '4px 0 0 16px' }}>
              {current.validation_errors.map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
          </Note>
        )}
        <div className="actions">
          <LinkButton to={`/events/${e.id}/solve`}>重新求解</LinkButton>
        </div>
      </Panel>

      <Panel>
        <Tabs
          value={view}
          options={[
            { value: 'sessions', label: '按日期' },
            { value: 'members', label: '按成员' },
          ]}
          onChange={setView}
        />
        {detail.isPending || !detail.data ? <Spinner /> : view === 'sessions' ? <SessionsByDate d={detail.data} /> : <MemberTable d={detail.data} />}
      </Panel>
      <Note>周视图、拖拽微调、锁定后重排、版本对比与发布,在 M4 接入。</Note>
    </>
  )
}

function versionLabel(v: ScheduleVersion): string {
  return fmtDateTime(v.created_at)
}

function SessionsByDate({ d }: { d: ScheduleVersionDetail }) {
  const byDate = new Map<string, ScheduleSession[]>()
  for (const s of d.sessions) byDate.set(s.date, [...(byDate.get(s.date) ?? []), s])
  const taskTotal = new Map<string, number>()
  for (const s of d.sessions) if (s.kind === 'formal' && s.song_code) taskTotal.set(s.song_code, (taskTotal.get(s.song_code) ?? 0) + 1)
  return (
    <>
      {[...byDate.entries()].map(([date, sessions]) => (
        <div key={date}>
          <div className="date-title">
            <span>
              {fmtMd(date)} {sessions[0].weekday}
            </span>
            <span>{sessions.length} 场</span>
          </div>
          {sessions.map((s) =>
            s.kind === 'evaluation' ? (
              <div key={s.id} className="evaluation" style={{ margin: '8px 0 12px' }}>
                <strong>全员评估 · {s.time}</strong>
                <p>
                  {s.attendance && Object.values(s.attendance).some((t) => t !== s.time)
                    ? Object.entries(s.attendance)
                        .filter(([, t]) => t !== s.time)
                        .map(([m, t]) => `${m} ${t}`)
                        .join(' · ') + ';其余全程到场'
                    : `${s.members.length} 人全程到场`}
                </p>
              </div>
            ) : (
              <SessionRow key={s.id} s={s} total={s.song_code ? (taskTotal.get(s.song_code) ?? 0) : 0} />
            ),
          )}
        </div>
      ))}
    </>
  )
}

function SessionRow({ s, total }: { s: ScheduleSession; total: number }) {
  const [start, end] = s.time.split('–')
  const absentIds = new Set(s.absent.map((m) => m.id))
  return (
    <div className="session">
      <div className="session__time">
        {start}
        <br />
        <span>{end}</span>
      </div>
      <div>
        <div className="session__title">
          {s.song_code && <Badge>{s.song_code}</Badge>} {s.song_name}
          <small>
            第 {s.task_no} / {total} 场 · {s.duration_slots}h
          </small>
        </div>
        <p>
          {s.members.map((m, i) => (
            <span key={m.id} className={absentIds.has(m.id) ? 'absent' : undefined}>
              {i > 0 && '、'}
              {m.display_name}
              {absentIds.has(m.id) && '(缺)'}
            </span>
          ))}
        </p>
      </div>
    </div>
  )
}

function MemberTable({ d }: { d: ScheduleVersionDetail }) {
  return (
    <div className="tbl-wrap" style={{ marginTop: 12 }}>
      <table className="tbl">
        <thead>
          <tr>
            <th>成员</th>
            <th className="num">场次</th>
            <th className="num">小时</th>
            <th className="num">天数</th>
            <th className="num">缺席</th>
            <th>评估到场</th>
          </tr>
        </thead>
        <tbody>
          {d.member_stats.map((m) => (
            <tr key={m.member_id} className={m.absent > 0 ? 'bad' : ''}>
              <td>{m.display_name}</td>
              <td className="num">{m.sessions}</td>
              <td className="num">{m.hours}</td>
              <td className="num">{m.days}</td>
              <td className="num">{m.absent}</td>
              <td>{m.eval_time ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
