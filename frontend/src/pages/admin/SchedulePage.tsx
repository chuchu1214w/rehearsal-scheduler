import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { api } from '../../api/client'
import { keys, useAction, useConflicts, useDiff, useEvent, useEventMembers, useInvalidateEvent, useVersion, useVersions } from '../../api/hooks'
import type { DiffItem, EditResult, ScheduleSession, ScheduleVersion } from '../../api/types'
import { MemberTable, SessionsByDate, WeekView, sessionsForMember } from '../../components/ScheduleViews'
import { Back, Badge, Button, Heading, LinkButton, Note, Panel, Spinner, Tabs } from '../../ui'
import { Modal } from '../../ui/Modal'
import { useToast } from '../../ui/Toast'
import { fmtDateTime, fmtMd } from '../../utils'

type View = 'week' | 'list' | 'members'

const SOURCE_TEXT: Record<string, string> = { solver: '求解', manual: '手动修改', resolve: '锁定重排', copy: '复制' }

export function SchedulePage() {
  const id = Number(useParams().id)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const invalidate = useInvalidateEvent()
  const { toast } = useToast()
  const [params, setParams] = useSearchParams()
  const [view, setView] = useState<View>('week')
  const [memberFilter, setMemberFilter] = useState<number | null>(null)
  const [confirm, setConfirm] = useState<'publish' | 'unpublish' | null>(null)
  const ev = useEvent(id)
  const members = useEventMembers(id)
  const versions = useVersions(id)
  const list = versions.data ?? []
  const requested = Number(params.get('v'))
  const selectedId = list.some((v) => v.id === requested) ? requested : (list[0]?.id ?? null)
  const detail = useVersion(selectedId)
  const diffAgainst = Number(params.get('diff')) || null
  const showDiff = params.has('diff')
  const diff = useDiff(showDiff ? selectedId : null, diffAgainst)
  const conflicts = useConflicts(id, selectedId)

  const setQuery = (next: Record<string, string | null>) => {
    const q: Record<string, string> = {}
    for (const [k, v] of params.entries()) q[k] = v
    for (const [k, v] of Object.entries(next)) {
      if (v == null) delete q[k]
      else q[k] = v
    }
    setParams(q, { replace: true })
  }

  const afterEdit = (r: EditResult, what: string) => {
    qc.setQueryData(keys.version(r.version.id), r.version)
    invalidate(id)
    if (r.forked) setQuery({ v: String(r.version.id), diff: String(r.version.parent_version_id ?? '') })
    const extra = r.warnings.length ? `;${r.warnings.join('、')}` : ''
    toast(r.forked ? `已基于 v${r.version.parent_version_id != null ? list.find((v) => v.id === r.version.parent_version_id)?.version_no ?? '' : ''} 创建草稿 v${r.version.version_no},${what}${extra}` : `${what}${extra}`)
  }
  const move = useAction(
    (vars: { vid: number; s: ScheduleSession; date: string; start: number }) =>
      api<EditResult>(`/api/schedules/${vars.vid}/sessions/${vars.s.id}/move`, { method: 'POST', json: { date: vars.date, start_slot: vars.start } }),
    (r, vars) => afterEdit(r, `已移动 ${vars.s.song_code} 到 ${fmtMd(vars.date)}`),
  )
  const lock = useAction(
    (vars: { vid: number; s: ScheduleSession; locked: boolean }) => api<EditResult>(`/api/schedules/${vars.vid}/sessions/${vars.s.id}/lock`, { method: 'POST', json: { locked: vars.locked } }),
    (r, vars) => afterEdit(r, vars.locked ? `已锁定 ${vars.s.song_code} 第 ${vars.s.task_no} 场` : `已解锁 ${vars.s.song_code} 第 ${vars.s.task_no} 场`),
  )
  const publish = useAction(
    (vid: number) => api<ScheduleVersion>(`/api/schedules/${vid}/publish`, { method: 'POST' }),
    (v) => {
      setConfirm(null)
      invalidate(id)
      toast(`已发布 v${v.version_no},成员现在可以看到并订阅日历`)
    },
  )
  const unpublish = useAction(
    (vid: number) => api<ScheduleVersion>(`/api/schedules/${vid}/unpublish`, { method: 'POST' }),
    (v) => {
      setConfirm(null)
      invalidate(id)
      toast(`已撤回 v${v.version_no},成员端恢复为「尚未发布」`)
    },
  )

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
  const canPublish = current.status !== 'published' && current.validation_errors.length === 0
  const editable = current.status !== 'archived'
  const sessions = detail.data ? sessionsForMember(detail.data.sessions, memberFilter) : []
  const range = { formal_start_date: e.formal_start_date, formal_end_date: e.formal_end_date, eval_date: e.eval_date, day_start_hour: e.day_start_hour, day_end_hour: e.day_end_hour }
  const dayUrl = (date: string) => `/events/${e.id}/schedule/day/${date}?v=${current.id}${memberFilter != null ? `&m=${memberFilter}` : ''}`
  const others = list.filter((v) => v.id !== current.id)
  const conflictItems = conflicts.data?.items ?? []
  const busy = move.isPending || lock.isPending

  return (
    <>
      <Back to={`/events/${e.id}`} label={`${e.name} · 工作台`} />
      <Heading title="排练表" subtitle={`正规排练 ${fmtMd(e.formal_start_date)}–${fmtMd(e.formal_end_date)},全员评估 ${fmtMd(e.eval_date)}。`} />

      <Panel>
        <div className="version-bar">
          <select value={current.id} onChange={(ev2) => setQuery({ v: ev2.target.value, diff: null })} aria-label="选择版本">
            {list.map((v) => (
              <option key={v.id} value={v.id}>
                v{v.version_no} · {fmtDateTime(v.created_at)} · {SOURCE_TEXT[v.source] ?? v.source}
                {v.status === 'published' ? ' · 已发布' : v.status === 'archived' ? ' · 已归档' : ''}
              </option>
            ))}
          </select>
          <Badge tone={current.status === 'published' ? 'green' : 'neutral'}>{current.status === 'published' ? '已发布' : current.status === 'archived' ? '已归档' : '草稿'}</Badge>
          {current.level_used != null && <Badge tone={current.level_used === 0 ? 'green' : 'orange'}>{current.level_used === 0 ? '无计划外缺席' : `缺席层级 L${current.level_used}`}</Badge>}
          <Badge tone={current.exact_optimum ? 'accent' : 'neutral'}>{current.exact_optimum ? '严格最优' : SOURCE_TEXT[current.source] === '求解' ? '非严格最优' : (SOURCE_TEXT[current.source] ?? current.source)}</Badge>
          {current.locked_count > 0 && <Badge tone="orange">锁定 {current.locked_count} 场</Badge>}
        </div>
        <p className="muted" style={{ marginTop: 8 }}>
          {current.session_count} 场 · 生成于 {fmtDateTime(current.created_at)}
          {current.parent_version_id != null && ` · 来自 v${list.find((v) => v.id === current.parent_version_id)?.version_no ?? '?'}`}
          {current.published_at && ` · 发布于 ${fmtDateTime(current.published_at)}`}
        </p>
        {current.skipped_songs.length > 0 && <Note tone="warning">这一版跳过了曲目 {current.skipped_songs.join('、')}(求解时参演人员尚未全部提交空闲)。</Note>}
        {current.validation_errors.length > 0 && (
          <Note tone="error">
            校验未通过,不能发布:
            <ul style={{ margin: '4px 0 0 16px' }}>
              {current.validation_errors.map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
          </Note>
        )}
        {conflictItems.length > 0 && (
          <Note tone="warning">
            <b>
              {conflicts.data?.members.map((m) => m.display_name).join('、')} 修改了空闲,{conflictItems.length} 场受影响:
            </b>
            {conflictItems.map((c, i) => (
              <div key={i} className="conflict">
                {fmtMd(c.session.date)} {c.session.weekday} {c.session.time} · <b>{c.session.kind === 'evaluation' ? '全员评估' : `${c.session.song_code} ${c.session.song_name}`}</b> · {c.member.display_name} 在 {c.hours.join('、')} 没空
              </div>
            ))}
            <p className="muted" style={{ marginTop: 6 }}>
              可以拖动这些场次到别的时间,或锁定不想动的场次后「重排其余」。
            </p>
          </Note>
        )}
        <div className="actions">
          <LinkButton to={`/events/${e.id}/solve`}>重新求解</LinkButton>
          {current.locked_count > 0 && <LinkButton to={`/events/${e.id}/solve?base=${current.id}`}>锁定后重排</LinkButton>}
          {others.length > 0 && !showDiff && <Button onClick={() => setQuery({ diff: String(current.parent_version_id ?? others[0].id) })}>对比版本</Button>}
          {current.status === 'published' ? (
            <Button variant="ghost-danger" onClick={() => setConfirm('unpublish')}>
              撤回发布
            </Button>
          ) : (
            <Button variant="primary" disabled={!canPublish} onClick={() => setConfirm('publish')}>
              发布这一版
            </Button>
          )}
        </div>
      </Panel>

      {showDiff && (
        <Panel>
          <div className="section">
            <h2>版本对比</h2>
            <Button small variant="ghost" onClick={() => setQuery({ diff: null })}>
              收起
            </Button>
          </div>
          <div className="version-bar">
            <span className="muted">v{current.version_no} 相对于</span>
            <select value={diffAgainst ?? diff.data?.against_id ?? ''} onChange={(ev2) => setQuery({ diff: ev2.target.value })} aria-label="对比的版本">
              {others.map((v) => (
                <option key={v.id} value={v.id}>
                  v{v.version_no} · {SOURCE_TEXT[v.source] ?? v.source}
                  {v.status === 'published' ? ' · 已发布' : ''}
                </option>
              ))}
            </select>
          </div>
          {diff.isPending ? <Spinner /> : diff.data ? <DiffList d={diff.data} /> : <p className="muted">没有可对比的版本。</p>}
        </Panel>
      )}

      <Panel>
        <Tabs
          value={view}
          options={[
            { value: 'week', label: '周日历' },
            { value: 'list', label: '按日期' },
            { value: 'members', label: '按成员' },
          ]}
          onChange={setView}
        />
        {view !== 'members' && (
          <div className="version-bar" style={{ marginTop: 10 }}>
            <select value={memberFilter ?? ''} onChange={(ev2) => setMemberFilter(ev2.target.value ? Number(ev2.target.value) : null)} aria-label="按成员筛选">
              <option value="">全体成员</option>
              {(members.data ?? []).map((m) => (
                <option key={m.member_id} value={m.member_id}>
                  只看 {m.display_name}
                </option>
              ))}
            </select>
            {memberFilter != null && <span className="muted">{sessions.filter((s) => s.kind === 'formal').length} 场</span>}
            {busy && <span className="muted">保存中…</span>}
          </div>
        )}
        {current.status === 'published' && view === 'week' && <p className="muted" style={{ marginTop: 8 }}>这一版已发布;拖动或锁定会自动复制成新的草稿,发布新草稿后才会影响成员。</p>}
        {detail.isPending || !detail.data ? (
          <Spinner />
        ) : view === 'week' ? (
          <WeekView
            sessions={sessions}
            range={range}
            onDateClick={(d) => navigate(dayUrl(d))}
            editable={editable && !busy}
            onMove={(s, date, start) => move.mutate({ vid: current.id, s, date, start })}
            onLock={(s, locked) => lock.mutate({ vid: current.id, s, locked })}
          />
        ) : view === 'list' ? (
          <SessionsByDate sessions={sessions} allSessions={detail.data.sessions} />
        ) : (
          <MemberTable d={detail.data} />
        )}
      </Panel>

      <Modal
        open={confirm !== null}
        title={confirm === 'publish' ? `发布 v${current.version_no}?` : `撤回 v${current.version_no} 的发布?`}
        onClose={() => setConfirm(null)}
        actions={
          confirm === 'publish' ? (
            <Button variant="primary" loading={publish.isPending} onClick={() => publish.mutate(current.id)}>
              发布
            </Button>
          ) : (
            <Button variant="danger" loading={unpublish.isPending} onClick={() => unpublish.mutate(current.id)}>
              撤回
            </Button>
          )
        }
      >
        <p>
          {confirm === 'publish'
            ? `发布后成员能在「我的排练表」看到,并可订阅到手机日历;${e.published_version_no ? `已发布的 v${e.published_version_no} 会归档。` : '之前没有发布过的版本。'}`
            : '撤回后成员端恢复为「尚未发布」,已订阅的日历会清空这场演出的排练。'}
        </p>
      </Modal>
    </>
  )
}

const CHANGE_TEXT: Record<DiffItem['change'], { label: string; tone: 'accent' | 'green' | 'orange' | 'red' | 'neutral' }> = {
  moved: { label: '移动', tone: 'orange' },
  changed: { label: '变更', tone: 'orange' },
  added: { label: '新增', tone: 'green' },
  removed: { label: '删除', tone: 'red' },
}

function when(s: ScheduleSession) {
  return `${fmtMd(s.date)} ${s.weekday} ${s.time}`
}

function DiffList({ d }: { d: ReturnType<typeof useDiff>['data'] & object }) {
  return (
    <>
      <p style={{ marginTop: 10, fontSize: 13 }}>
        <b>{d.summary}</b>
        {d.affected_members.length > 0 && <span className="muted"> · {d.affected_members.map((m) => m.display_name).join('、')}</span>}
      </p>
      {d.items.map((it, i) => {
        const s = (it.after ?? it.before) as ScheduleSession
        const title = it.kind === 'evaluation' ? '全员评估' : `${s.song_code} ${s.song_name} 第 ${s.task_no} 场`
        return (
          <div key={i} className="diff-item">
            <Badge tone={CHANGE_TEXT[it.change].tone}>{CHANGE_TEXT[it.change].label}</Badge>
            <div>
              <div>{title}</div>
              {it.change === 'moved' && it.before && it.after && (
                <div>
                  <span className="from">{when(it.before)}</span>
                  <span className="arrow">→</span>
                  {when(it.after)}
                </div>
              )}
              {it.change === 'changed' && it.after && (
                <div className="muted">
                  {when(it.after)} · {it.after.kind === 'evaluation' ? '到场时段变化' : `缺席:${it.after.absent.map((m) => m.display_name).join('、') || '无'}(原:${it.before?.absent.map((m) => m.display_name).join('、') || '无'})`}
                </div>
              )}
              {(it.change === 'added' || it.change === 'removed') && <div className="muted">{when(s)}</div>}
            </div>
          </div>
        )
      })}
    </>
  )
}
