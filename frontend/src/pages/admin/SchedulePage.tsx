import { useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { api } from '../../api/client'
import { useAction, useEvent, useEventMembers, useInvalidateEvent, useVersion, useVersions } from '../../api/hooks'
import type { ScheduleVersion } from '../../api/types'
import { MemberTable, SessionsByDate, WeekView, sessionsForMember } from '../../components/ScheduleViews'
import { Back, Badge, Button, Heading, LinkButton, Note, Panel, Spinner, Tabs } from '../../ui'
import { Modal } from '../../ui/Modal'
import { useToast } from '../../ui/Toast'
import { fmtDateTime, fmtMd } from '../../utils'

type View = 'week' | 'list' | 'members'

export function SchedulePage() {
  const id = Number(useParams().id)
  const navigate = useNavigate()
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
  const sessions = detail.data ? sessionsForMember(detail.data.sessions, memberFilter) : []
  const range = { formal_start_date: e.formal_start_date, formal_end_date: e.formal_end_date, eval_date: e.eval_date, day_start_hour: e.day_start_hour, day_end_hour: e.day_end_hour }
  const dayUrl = (date: string) => `/events/${e.id}/schedule/day/${date}?v=${current.id}${memberFilter != null ? `&m=${memberFilter}` : ''}`

  return (
    <>
      <Back to={`/events/${e.id}`} label={`${e.name} · 工作台`} />
      <Heading title="排练表" subtitle={`正规排练 ${fmtMd(e.formal_start_date)}–${fmtMd(e.formal_end_date)},全员评估 ${fmtMd(e.eval_date)}。`} />

      <Panel>
        <div className="version-bar">
          <select value={current.id} onChange={(ev2) => setParams({ v: ev2.target.value })} aria-label="选择版本">
            {list.map((v) => (
              <option key={v.id} value={v.id}>
                v{v.version_no} · {fmtDateTime(v.created_at)}
                {v.status === 'published' ? ' · 已发布' : v.status === 'archived' ? ' · 已归档' : ''}
              </option>
            ))}
          </select>
          <Badge tone={current.status === 'published' ? 'green' : 'neutral'}>{current.status === 'published' ? '已发布' : current.status === 'archived' ? '已归档' : '草稿'}</Badge>
          {current.level_used != null && <Badge tone={current.level_used === 0 ? 'green' : 'orange'}>{current.level_used === 0 ? '无计划外缺席' : `缺席层级 L${current.level_used}`}</Badge>}
          <Badge tone={current.exact_optimum ? 'accent' : 'orange'}>{current.exact_optimum ? '严格最优' : '非严格最优'}</Badge>
        </div>
        <p className="muted" style={{ marginTop: 8 }}>
          {current.session_count} 场 · 生成于 {fmtDateTime(current.created_at)}
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
        <div className="actions">
          <LinkButton to={`/events/${e.id}/solve`}>重新求解</LinkButton>
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
          </div>
        )}
        {detail.isPending || !detail.data ? (
          <Spinner />
        ) : view === 'week' ? (
          <WeekView sessions={sessions} range={range} onDateClick={(d) => navigate(dayUrl(d))} />
        ) : view === 'list' ? (
          <SessionsByDate sessions={sessions} allSessions={detail.data.sessions} />
        ) : (
          <MemberTable d={detail.data} />
        )}
      </Panel>
      <Note>拖拽微调、锁定后重排、版本对比在 M5 接入。</Note>

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
