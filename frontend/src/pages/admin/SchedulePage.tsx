import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { ApiError, api } from '../../api/client'
import { keys, useAction, useConflicts, useDiff, useEvent, useEventMembers, useInvalidateEvent, useSongs, useVersion, useVersions } from '../../api/hooks'
import type { DiffItem, EditResult, ReoptResult, ScheduleSession, ScheduleVersion, ScheduleVersionDetail } from '../../api/types'
import { AiEditPanel } from '../../components/AiEditPanel'
import { MemberTable, SessionsByDate, WeekView, sessionsForMember, songOrderOf } from '../../components/ScheduleViews'
import { renderScheduleImage, shareImage } from '../../share'
import { Back, Badge, Button, Heading, LinkButton, Note, Panel, Spinner, Tabs } from '../../ui'
import { Modal } from '../../ui/Modal'
import { useToast } from '../../ui/Toast'
import { fmtDateTime, fmtMd } from '../../utils'

type View = 'week' | 'list' | 'members'

const SOURCE_TEXT: Record<string, string> = { solver: '求解', manual: '手动修改', resolve: '锁定重排', copy: '复制', partial: '部分排程' }

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
  /** 有冲突时发布:管理员逐条看过并勾选确认,可写一句说明 */
  const [forceOk, setForceOk] = useState(false)
  const [forceNote, setForceNote] = useState('')
  const [sharing, setSharing] = useState(false)
  const [jumpDate, setJumpDate] = useState<string | null>(null)
  /** 少改动解决冲突的提案(连同算它的版本;revision 是服务器算提案时的修改次数,应用时核对) */
  const [reopt, setReopt] = useState<(ReoptResult & { vid: number }) | null>(null)
  const ev = useEvent(id)
  const members = useEventMembers(id)
  const songs = useSongs(id)
  const versions = useVersions(id)
  const list = versions.data ?? []
  const requested = Number(params.get('v'))
  const selectedId = list.some((v) => v.id === requested) ? requested : (list[0]?.id ?? null)
  const detail = useVersion(selectedId)
  const diffAgainst = Number(params.get('diff')) || null
  const showDiff = params.has('diff')
  const diff = useDiff(showDiff ? selectedId : null, diffAgainst)
  const conflicts = useConflicts(id, selectedId)
  // 冲突清单变了(如刚有成员改了空闲)就要重新勾选确认
  const issueKey = (detail.data?.issues ?? []).map((i) => i.message).join('\n')
  useEffect(() => setForceOk(false), [issueKey, selectedId])
  useEffect(() => setForceNote(''), [selectedId])

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
    // 复制出了新草稿:先放进版本列表缓存,页面立刻切到它(不等列表重新请求,免得短暂落到别的草稿上)
    if (r.forked) qc.setQueryData<ScheduleVersion[]>(keys.versions(id), (old) => (old && !old.some((v) => v.id === r.version.id) ? [r.version, ...old] : old))
    invalidate(id)
    if (r.forked) setQuery({ v: String(r.version.id), diff: String(r.version.parent_version_id ?? '') })
    const extra = r.warnings.length ? `;${r.warnings.join('、')}` : ''
    const parentNo = r.version.parent_version_id != null ? (list.find((v) => v.id === r.version.parent_version_id)?.version_no ?? '') : ''
    const msg = r.forked ? `已基于 v${parentNo} 创建草稿 v${r.version.version_no},${what}${extra}` : `${what}${extra}`
    // 新引入的冲突:草稿照样保存,标红并说明;发布前必须解决
    if (r.new_issues?.length) toast(`${msg}。注意,有冲突:${r.new_issues.slice(0, 2).join(';')}${r.new_issues.length > 2 ? ' 等' : ''}(已标红,可撤销)`)
    else toast(msg)
  }
  /** 提交修改:带上看到的修改次数;对不上(别处改过)时刷新再提示 */
  const edit = async (vid: number, path: string, json: Record<string, unknown>) => {
    try {
      return await api<EditResult>(`/api/schedules/${vid}/${path}`, { method: 'POST', json: { ...json, expected_revision: detail.data?.revision ?? null } })
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) void qc.invalidateQueries({ queryKey: keys.version(vid) })
      throw err
    }
  }
  const move = useAction(
    (vars: { vid: number; s: ScheduleSession; date: string; start: number }) => edit(vars.vid, 'ops/move', { session_id: vars.s.id, date: vars.date, start_slot: vars.start }),
    (r, vars) => afterEdit(r, `已移动 ${vars.s.song_code} 到 ${fmtMd(vars.date)}`),
  )
  const resize = useAction(
    (vars: { vid: number; s: ScheduleSession; start: number; duration: number }) =>
      edit(vars.vid, 'ops/resize', { session_id: vars.s.id, start_slot: vars.start, duration_slots: vars.duration }),
    (r, vars) => afterEdit(r, `已把 ${vars.s.song_code} 调整为 ${vars.duration} 小时`),
  )
  const addSession = useAction(
    (vars: { vid: number; songId: number; date: string; start: number; duration: number }) =>
      edit(vars.vid, 'ops/add', { song_id: vars.songId, date: vars.date, start_slot: vars.start, duration_slots: vars.duration }),
    (r, vars) => afterEdit(r, `已新建 ${fmtMd(vars.date)} 的排练`),
  )
  const deleteSession = useAction(
    (vars: { vid: number; s: ScheduleSession }) => edit(vars.vid, 'ops/delete', { session_id: vars.s.id }),
    (r, vars) => afterEdit(r, `已删除 ${vars.s.song_code} 第 ${vars.s.task_no} 场(可撤销)`),
  )
  const swap = useAction(
    (vars: { vid: number; a: ScheduleSession; b: ScheduleSession }) => edit(vars.vid, 'ops/swap', { a: vars.a.id, b: vars.b.id }),
    (r, vars) => afterEdit(r, `已交换 ${vars.a.song_code} 与 ${vars.b.song_code} 的时间`),
  )
  const lock = useAction(
    (vars: { vid: number; s: ScheduleSession; locked: boolean }) => edit(vars.vid, 'ops/lock', { session_id: vars.s.id, locked: vars.locked }),
    (r, vars) => afterEdit(r, vars.locked ? `已锁定 ${vars.s.song_code} 第 ${vars.s.task_no} 场` : `已解锁 ${vars.s.song_code} 第 ${vars.s.task_no} 场`),
  )
  const undoRedo = useAction(
    (vars: { vid: number; action: 'undo' | 'redo' }) => edit(vars.vid, vars.action, {}),
    (r) => afterEdit({ ...r, warnings: [] }, r.warnings[0] ?? ''),
  )
  const fork = useAction(
    (vid: number) => api<EditResult>(`/api/schedules/${vid}/fork`, { method: 'POST' }),
    (r) => {
      qc.setQueryData(keys.version(r.version.id), r.version)
      invalidate(id)
      setQuery({ v: String(r.version.id), diff: null })
      toast(`已以 v${list.find((v) => v.id === r.version.parent_version_id)?.version_no ?? ''} 为底稿新建草稿 v${r.version.version_no},原版本不变`)
    },
  )
  const reoptimize = useAction(
    async (vid: number) => {
      try {
        return await api<ReoptResult>(`/api/schedules/${vid}/reoptimize`, { method: 'POST' })
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) void qc.invalidateQueries({ queryKey: keys.version(vid) })
        throw err
      }
    },
    (r, vid) => setReopt({ ...r, vid }),
  )
  const applyReopt = useAction(
    async (r: ReoptResult & { vid: number }) => {
      try {
        return await api<EditResult>(`/api/schedules/${r.vid}/ops/batch`, {
          method: 'POST',
          json: { ops: r.ops, summary: `少改动解决冲突:挪动 ${r.ops.length} 场`, expected_revision: r.revision },
        })
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          setReopt(null)
          void qc.invalidateQueries({ queryKey: keys.version(r.vid) })
        }
        throw err
      }
    },
    (res, r) => {
      setReopt(null)
      afterEdit(res, `已挪动 ${r.ops.length} 场(可撤销)`)
    },
  )
  const setLocation = useAction(
    (vars: { vid: number; s: ScheduleSession; location: string }) =>
      api<{ version: ScheduleVersionDetail; notified: number }>(`/api/schedules/${vars.vid}/sessions/${vars.s.id}/location`, { method: 'POST', json: { location: vars.location } }),
    (r, vars) => {
      qc.setQueryData(keys.version(r.version.id), r.version)
      void qc.invalidateQueries({ queryKey: keys.published(id) })
      toast(vars.location ? `已保存地点${r.notified ? `,已通知 ${r.notified} 人` : current.status === 'published' ? '' : '(发布后成员可见)'}` : '已清空地点')
    },
  )
  const publish = useAction(
    async ({ vid, acknowledged, note }: { vid: number; acknowledged: string[]; note: string }) => {
      try {
        // 有冲突时带上管理员确认过的冲突清单(force,去重);服务器会核对清单是否包含现在的每一条
        const json = acknowledged.length
          ? { expected_revision: detail.data?.revision ?? null, force: true, acknowledged_issues: [...new Set(acknowledged)], note: note.trim() }
          : { expected_revision: detail.data?.revision ?? null }
        return await api<ScheduleVersion>(`/api/schedules/${vid}/publish`, { method: 'POST', json })
      } catch (err) {
        void qc.invalidateQueries({ queryKey: keys.versions(id) })
        if (err instanceof ApiError && err.status === 409 && acknowledged.length) {
          // 确认之后冲突又变了:窗口不关、说明保留,刷新清单后重新勾选确认
          await qc.refetchQueries({ queryKey: keys.version(vid) })
          throw err
        }
        // 其他情况(期间被改过、刚冒出冲突等):关掉窗口,刷新这一版让冲突显示出来
        setConfirm(null)
        void qc.invalidateQueries({ queryKey: keys.version(vid) })
        if (err instanceof ApiError && err.status === 422 && !acknowledged.length) {
          throw new Error('刚发现新的冲突,清单已刷新。可以先解决;确需时再点「发布这一版」逐条确认后带着冲突发布')
        }
        throw err
      }
    },
    (v) => {
      setConfirm(null)
      setForceNote('')
      invalidate(id)
      toast(
        v.forced_publish
          ? `已发布 v${v.version_no}(带 ${v.forced_publish.issues.length} 处冲突,已记录你的确认),成员现在可以看到并订阅日历`
          : `已发布 v${v.version_no},成员现在可以看到并订阅日历`,
      )
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
        <Heading title="排练表" subtitle="草稿仅管理员可见,确认无误后再发布。" />
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
  const issues = detail.data?.issues ?? []
  const conflictIds = new Set(issues.flatMap((i) => i.session_ids))
  // 以实时检查为准(保存的 validation_errors 可能是旧规则下的结果);详情还没载入时不允许发布。
  // 有冲突时也可以发布,但要在确认窗口里逐条看过并勾选确认
  const canPublish = current.status !== 'published' && detail.data?.issues !== undefined
  const forced = current.forced_publish ?? null
  const editable = current.status !== 'archived'
  const sessions = detail.data ? sessionsForMember(detail.data.sessions, memberFilter) : []
  const range = { formal_start_date: e.formal_start_date, formal_end_date: e.formal_end_date, eval_date: e.eval_date, day_start_hour: e.day_start_hour, day_end_hour: e.day_end_hour }
  const dayUrl = (date: string) => `/events/${e.id}/schedule/day/${date}?v=${current.id}${memberFilter != null ? `&m=${memberFilter}` : ''}`
  const others = list.filter((v) => v.id !== current.id)
  const conflictItems = conflicts.data?.items ?? []
  const busy =
    move.isPending ||
    lock.isPending ||
    swap.isPending ||
    undoRedo.isPending ||
    resize.isPending ||
    addSession.isPending ||
    deleteSession.isPending ||
    applyReopt.isPending ||
    reoptimize.isPending // 计算提案期间不让改,免得提案对应不上
  const skipped = new Set(current.skipped_songs)
  const songChoices = (songs.data?.songs ?? []).filter((x) => !skipped.has(x.code)).map((x) => ({ id: x.id, code: x.code, name: x.name }))

  // 一键把这一版画成长图,交给系统分享面板(可选微信)
  const onShare = async () => {
    if (!detail.data || sharing) return
    setSharing(true)
    try {
      const memberName = memberFilter != null ? members.data?.find((m) => m.member_id === memberFilter)?.display_name : null
      const blob = await renderScheduleImage({
        eventName: `${e.name} · 排练表`,
        subtitle: `${current.status === 'published' ? '已发布' : '草稿'} v${current.version_no} · ${sessions.length} 场${memberName ? ` · 只看 ${memberName}` : ''} · 演出 ${fmtMd(e.performance_date)}`,
        sessions,
        songOrder: songOrderOf(detail.data.sessions),
      })
      const how = await shareImage(blob, `排练表-v${current.version_no}.png`, `${e.name} 排练表`)
      if (how === 'downloaded') toast('已下载排练表图片,可以发到微信')
    } catch (err) {
      toast(`生成图片失败:${(err as Error).message}`)
    } finally {
      setSharing(false)
    }
  }

  return (
    <>
      <Back to={`/events/${e.id}`} label={`${e.name} · 工作台`} />
      <Heading title="排练表" subtitle={`正规排练 ${fmtMd(e.formal_start_date)}–${fmtMd(e.formal_end_date)},全员评估 ${fmtMd(e.eval_date)}。`} />

      <Panel>
        <div className="version-bar">
          <select value={current.id} disabled={reoptimize.isPending} onChange={(ev2) => setQuery({ v: ev2.target.value, diff: null })} aria-label="选择版本">
            {list.map((v) => (
              <option key={v.id} value={v.id}>
                v{v.version_no} · {fmtDateTime(v.created_at)} · {SOURCE_TEXT[v.source] ?? v.source}
                {v.status === 'published' ? ' · 已发布' : v.status === 'archived' ? ' · 已归档' : ''}
                {v.forced_publish ? ' · 带冲突' : ''}
              </option>
            ))}
          </select>
          <Badge tone={current.status === 'published' ? 'green' : 'neutral'}>{current.status === 'published' ? '已发布' : current.status === 'archived' ? '已归档' : '草稿'}</Badge>
          {current.level_used != null && <Badge tone={current.level_used === 0 ? 'green' : 'orange'}>{current.level_used === 0 ? '无计划外缺席' : `缺席层级 L${current.level_used}`}</Badge>}
          <Badge tone={current.exact_optimum ? 'accent' : 'neutral'}>{current.exact_optimum ? '严格最优' : SOURCE_TEXT[current.source] === '求解' ? '非严格最优' : (SOURCE_TEXT[current.source] ?? current.source)}</Badge>
          {current.locked_count > 0 && <Badge tone="orange">锁定 {current.locked_count} 场</Badge>}
          {forced && <Badge tone="red">带冲突发布</Badge>}
        </div>
        <p className="muted" style={{ marginTop: 8 }}>
          {current.session_count} 场 · 生成于 {fmtDateTime(current.created_at)}
          {current.parent_version_id != null && ` · 来自 v${list.find((v) => v.id === current.parent_version_id)?.version_no ?? '?'}`}
          {current.published_at && ` · 发布于 ${fmtDateTime(current.published_at)}`}
        </p>
        <div className="actions" style={{ justifyContent: 'flex-start', marginTop: 10 }}>
          <Button small loading={sharing} disabled={!detail.data} onClick={() => void onShare()}>
            分享到微信
          </Button>
          <span className="muted" style={{ fontSize: 11, alignSelf: 'center' }}>
            生成排练表长图{memberFilter != null ? '(当前筛选的成员)' : ''},在分享面板里选微信
          </span>
        </div>
        {forced && (
          <Note tone="warning">
            <b>
              这一版是管理员确认后带着 {forced.issues.length} 处冲突发布的
            </b>
            (由 {forced.by_name} 于 {fmtDateTime(forced.at)} 确认){forced.note && <>:「{forced.note}」</>}
            <details className="history">
              <summary>发布时的冲突({forced.issues.length})</summary>
              <ul className="issue-list">
                {forced.issues.map((x, k) => (
                  <li key={k}>{x}</li>
                ))}
              </ul>
            </details>
          </Note>
        )}
        {current.skipped_songs.length > 0 && <Note tone="warning">这一版跳过了曲目 {current.skipped_songs.join('、')}(求解时参演人员尚未全部提交空闲)。</Note>}
        {issues.length > 0 && (
          <Note tone="error">
            <b>
              有 {issues.length} 处冲突
              {current.status === 'draft' ? ',建议先解决' : ''}
            </b>
            (日历里标红;点一条跳到那一周{current.status === 'draft' ? ';确实需要时,也可以在发布时逐条确认后带着冲突发布' : ''})
            <ul className="issue-list">
              {issues.map((x, k) => {
                    const first = detail.data?.sessions.find((s2) => x.session_ids.includes(s2.id))
                    return (
                      <li key={k}>
                        <button
                          type="button"
                          onClick={() => {
                            if (!first) return
                            setView('week')
                            setJumpDate(`${first.date}|${Date.now()}`) // 带时间戳:重复点同一条也会跳
                          }}
                        >
                          {x.message}
                        </button>
                      </li>
                    )
                  })}
            </ul>
            {editable && (
              <div className="actions" style={{ justifyContent: 'flex-start', alignItems: 'center' }}>
                <Button small loading={reoptimize.isPending} disabled={busy} onClick={() => reoptimize.mutate(current.id)}>
                  少改动解决冲突
                </Button>
                <span className="muted" style={{ fontSize: 11 }}>
                  {reoptimize.isPending ? '正在找挪动最少的办法,最多约 20 秒…' : '锁定的场次不动,只挪必要的几场;先给你看,确认后才改'}
                </span>
              </div>
            )}
          </Note>
        )}
        {(detail.data?.notices?.length ?? 0) > 0 && (
          <Note>
            <b>提醒(不影响发布):</b>
            <ul className="issue-list">
              {detail.data!.notices!.map((x, k) => (
                <li key={k}>{x}</li>
              ))}
            </ul>
          </Note>
        )}
        {conflictItems.length > 0 && issues.length === 0 && (
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
        {current.status === 'draft' && (detail.data?.can_undo || detail.data?.can_redo) && (
          <div className="actions" style={{ justifyContent: 'flex-start' }}>
            <Button small disabled={!detail.data?.can_undo || busy} onClick={() => undoRedo.mutate({ vid: current.id, action: 'undo' })}>
              ↶ 撤销
            </Button>
            <Button small disabled={!detail.data?.can_redo || busy} onClick={() => undoRedo.mutate({ vid: current.id, action: 'redo' })}>
              ↷ 重做
            </Button>
          </div>
        )}
        {(detail.data?.history?.length ?? 0) > 0 && (
          <details className="history">
            <summary>修改记录({detail.data!.history!.length})</summary>
            <ol>
              {detail.data!.history!.map((h) => (
                <li key={h.id} className={h.undone ? 'is-undone' : ''}>
                  {h.summary}
                  <span className="muted"> · {fmtDateTime(h.created_at)}</span>
                </li>
              ))}
            </ol>
          </details>
        )}
        <div className="actions">
          <LinkButton to={`/events/${e.id}/solve`}>重新求解</LinkButton>
          {current.status !== 'draft' && (
            <Button loading={fork.isPending} onClick={() => fork.mutate(current.id)}>
              以这一版为底稿新建草稿
            </Button>
          )}
          {current.locked_count > 0 && <LinkButton to={`/events/${e.id}/solve?base=${current.id}`}>锁定后重排</LinkButton>}
          {others.length > 0 && !showDiff && <Button onClick={() => setQuery({ diff: String(current.parent_version_id ?? others[0].id) })}>对比版本</Button>}
          {current.status === 'published' ? (
            <Button variant="ghost-danger" onClick={() => setConfirm('unpublish')}>
              撤回发布
            </Button>
          ) : (
            <Button
              variant="primary"
              disabled={!canPublish}
              onClick={() => {
                setForceOk(false)
                setConfirm('publish')
              }}
            >
              {issues.length > 0 ? `发布这一版(有 ${issues.length} 处冲突)` : '发布这一版'}
            </Button>
          )}
        </div>
      </Panel>

      {editable && detail.data && (
        <AiEditPanel eventId={e.id} version={current} revision={detail.data.revision} disabled={busy} onApplied={(r) => afterEdit(r, '已按 AI 方案修改(可撤销)')} />
      )}

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
            onSwap={(a, b) => swap.mutate({ vid: current.id, a, b })}
            onResize={(s, start, duration) => resize.mutate({ vid: current.id, s, start, duration })}
            onDelete={(s) => deleteSession.mutate({ vid: current.id, s })}
            onCreate={(v) => addSession.mutate({ vid: current.id, songId: v.songId, date: v.date, start: v.startSlot, duration: v.durationSlots })}
            songs={songChoices}
            conflictIds={conflictIds}
            jumpDate={jumpDate}
            onLock={(s, locked) => lock.mutate({ vid: current.id, s, locked })}
            onLocation={(s, location) => setLocation.mutate({ vid: current.id, s, location })}
          />
        ) : view === 'list' ? (
          <SessionsByDate sessions={sessions} allSessions={detail.data.sessions} />
        ) : (
          <MemberTable d={detail.data} />
        )}
      </Panel>

      <Modal
        open={reopt !== null}
        title={`少改动解决冲突 · v${list.find((v) => v.id === reopt?.vid)?.version_no ?? ''}`}
        onClose={() => setReopt(null)}
        actions={
          reopt?.status === 'ok' ? (
            <>
              <Button onClick={() => setReopt(null)}>不用了</Button>
              <Button variant="primary" loading={applyReopt.isPending} onClick={() => reopt && applyReopt.mutate(reopt)}>
                应用(可撤销)
              </Button>
            </>
          ) : (
            <Button onClick={() => setReopt(null)}>知道了</Button>
          )
        }
      >
        {reopt && (
          <>
            <p>
              <b>{reopt.message}</b>
              {reopt.status === 'ok' && !reopt.optimal && <span className="muted">(时间有限,不一定是挪动最少的办法)</span>}
            </p>
            {reopt.preview && (
              <>
                <ol className="ai-edit__lines">
                  {reopt.preview.lines.map((x, i) => (
                    <li key={i}>{x}</li>
                  ))}
                </ol>
                {reopt.preview.issues.length > 0 ? (
                  <Note tone="warning">
                    挪动后还剩 {reopt.preview.issues.length} 处冲突(挪动解决不了的,需要手动处理):
                    <ul className="issue-list">
                      {reopt.preview.issues.map((x, i) => (
                        <li key={i}>{x}</li>
                      ))}
                    </ul>
                  </Note>
                ) : (
                  <p className="muted">挪动后没有冲突了。</p>
                )}
                {reopt.preview.notices.length > 0 && <p className="muted">提醒:{reopt.preview.notices.join(';')}</p>}
              </>
            )}
          </>
        )}
      </Modal>

      <Modal
        open={confirm !== null}
        title={confirm === 'publish' ? `发布 v${current.version_no}?` : `撤回 v${current.version_no} 的发布?`}
        onClose={() => setConfirm(null)}
        actions={
          confirm === 'publish' ? (
            issues.length > 0 ? (
              <>
                <Button onClick={() => setConfirm(null)}>先不发布</Button>
                <Button
                  variant="danger"
                  disabled={!forceOk || detail.isFetching}
                  loading={publish.isPending}
                  onClick={() => publish.mutate({ vid: current.id, acknowledged: issues.map((i) => i.message), note: forceNote })}
                >
                  仍然发布
                </Button>
              </>
            ) : (
              <Button variant="primary" loading={publish.isPending} onClick={() => publish.mutate({ vid: current.id, acknowledged: [], note: '' })}>
                发布
              </Button>
            )
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
        {confirm === 'publish' && issues.length > 0 && (
          <div className="force-publish">
            <Note tone="error">
              <b>这一版还有 {issues.length} 处冲突,不满足排练要求:</b>
              <ul className="issue-list force-publish__list">
                {issues.map((x, k) => (
                  <li key={k}>{x.message}</li>
                ))}
              </ul>
            </Note>
            <p className="muted">带着冲突发布后,成员会照这份排练表排练(例如有人在没空的时段被排了练习),请确认已经和相关成员沟通好。之后仍可修改并发布新的版本。</p>
            <label className="force-publish__check">
              <input type="checkbox" checked={forceOk} onChange={(ev2) => setForceOk(ev2.target.checked)} />
              <span>我已逐条看过以上 {issues.length} 处冲突,确认仍要发布</span>
            </label>
            <label className="field">
              <span>说明(可选,只有管理员看得到)</span>
              <textarea value={forceNote} maxLength={300} rows={2} placeholder="例如:A 那天会晚到,已当面确认" onChange={(ev2) => setForceNote(ev2.target.value)} />
            </label>
          </div>
        )}
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
