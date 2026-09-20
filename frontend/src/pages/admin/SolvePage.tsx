import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'

import { api } from '../../api/client'
import { keys, useAction, useEvent, useInvalidateEvent, useLatestJob, usePrecheck } from '../../api/hooks'
import type { Diagnosis, SolveJob } from '../../api/types'
import { Back, Badge, Button, CheckRow, Heading, LinkButton, Note, Panel, Spinner } from '../../ui'
import { Modal } from '../../ui/Modal'
import { fmtDateTime, fmtMd } from '../../utils'

const ATTEMPT_TEXT: Record<string, string> = { 无候选: '有排练没有候选时段', INFEASIBLE: '无解', 可行: '可行', UNKNOWN: '超时未定', MODEL_INVALID: '模型错误' }

const STATUS_TEXT: Record<SolveJob['status'], string> = {
  queued: '排队中',
  running: '求解中',
  succeeded: '已生成草稿',
  infeasible: '无可行方案',
  failed: '求解失败',
  cancelled: '已取消',
}

export function SolvePage() {
  const id = Number(useParams().id)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const invalidate = useInvalidateEvent()
  const ev = useEvent(id)
  const check = usePrecheck(id)
  const latest = useLatestJob(id)
  const [confirm, setConfirm] = useState(false)
  const [startedId, setStartedId] = useState<number | null>(null)

  const job = latest.data ?? null
  const running = !!job && (job.status === 'running' || job.status === 'queued')

  const start = useAction(
    (onlyReady: boolean) => api<SolveJob>(`/api/events/${id}/solve`, { method: 'POST', json: { only_ready_songs: onlyReady } }),
    (created) => {
      setConfirm(false)
      setStartedId(created.id)
      qc.setQueryData(keys.latestJob(id), created)
    },
  )
  const cancel = useAction(
    (jobId: number) => api<SolveJob>(`/api/solve-jobs/${jobId}/cancel`, { method: 'POST' }),
    (updated) => qc.setQueryData(keys.latestJob(id), updated),
  )

  // 任务结束:刷新工作台进度;本页发起且成功 → 直接跳到排练表
  const status = job?.status
  useEffect(() => {
    if (!job || running) return
    invalidate(id)
    if (job.id === startedId && job.status === 'succeeded' && job.version_id) {
      navigate(`/events/${id}/schedule?v=${job.version_id}`)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, job?.id])

  if (ev.isPending) return <Spinner />
  if (!ev.data) return null
  const e = ev.data
  const items = check.data?.items ?? []
  const attention = items.filter((i) => i.level !== 'ok').length
  const canSolve = !!check.data?.can_solve && !running

  const onSolve = () => {
    if (attention > 0) setConfirm(true)
    else start.mutate(false)
  }

  return (
    <>
      <Back to={`/events/${e.id}`} label={`${e.name} · 工作台`} />
      <Heading title="排程" subtitle="先检查,再开始求解。求解在后台进行,通常几秒到一两分钟。" />

      <Panel>
        <div className="section">
          <h2>求解前检查</h2>
          {check.data && (attention ? <Badge tone="orange">{attention} 项需注意</Badge> : <Badge tone="green">全部通过</Badge>)}
        </div>
        {check.isPending ? (
          <Spinner text="检查中…" />
        ) : (
          items.map((i) => (
            <CheckRow key={i.key} level={i.level}>
              {i.label}
              {i.detail && <span className="muted"> · {i.detail}</span>}
            </CheckRow>
          ))
        )}
        {check.data && !check.data.can_solve && <Note tone="error">请先补齐上面标红的项目。</Note>}
        {check.data?.can_solve && attention > 0 && !running && <Note tone="warning">可以先排已就绪的曲目,或直接求解;未提交空闲的人会被视为全程没空。</Note>}
        <div className="actions">
          <LinkButton to={`/events/${e.id}/progress`}>回填报进度</LinkButton>
          <Button variant="primary" disabled={!canSolve} loading={start.isPending} onClick={onSolve}>
            {job && !running ? '重新求解' : '开始求解'}
          </Button>
        </div>
      </Panel>

      {job && running && (
        <Panel>
          <div className="section">
            <h2>正在求解</h2>
            <Badge>{STATUS_TEXT[job.status]}</Badge>
          </div>
          <div className="progressbar progressbar--busy">
            <span />
          </div>
          <p className="muted">
            {job.progress || '准备中…'}
            {job.elapsed_seconds != null && ` · 已用 ${Math.round(job.elapsed_seconds)} 秒`}
          </p>
          {job.skipped_songs.length > 0 && <Note tone="warning">本次跳过未就绪的曲目:{job.skipped_songs.join('、')}</Note>}
          <div className="actions">
            <Button variant="ghost-danger" loading={cancel.isPending} onClick={() => cancel.mutate(job.id)}>
              取消
            </Button>
          </div>
        </Panel>
      )}

      {job && !running && <ResultPanel job={job} eventId={e.id} evalDate={fmtMd(e.eval_date)} />}

      <Modal
        open={confirm}
        title="检查中有需注意的项目"
        onClose={() => setConfirm(false)}
        actions={
          <>
            <LinkButton to={`/events/${e.id}/progress`}>返回补充</LinkButton>
            <Button loading={start.isPending} onClick={() => start.mutate(true)}>
              先排已就绪曲目
            </Button>
            <Button variant="primary" loading={start.isPending} onClick={() => start.mutate(false)}>
              仍然求解
            </Button>
          </>
        }
      >
        <p>
          还有 {attention} 项需注意。「先排已就绪曲目」会跳过参演人员未全部提交空闲的曲目;「仍然求解」把未提交的人视为全程没空,可能导致无解。
        </p>
      </Modal>
    </>
  )
}

function ResultPanel({ job, eventId, evalDate }: { job: SolveJob; eventId: number; evalDate: string }) {
  const when = fmtDateTime(job.finished_at)
  const tone = job.status === 'succeeded' ? 'green' : job.status === 'infeasible' ? 'orange' : job.status === 'failed' ? 'red' : 'neutral'
  return (
    <Panel>
      <div className="section">
        <h2>上次求解结果</h2>
        <Badge tone={tone}>{STATUS_TEXT[job.status]}</Badge>
      </div>
      <p className="muted">
        {when}
        {job.elapsed_seconds != null && ` · 用时 ${job.elapsed_seconds} 秒`}
        {job.only_ready_songs && ' · 只排已就绪曲目'}
      </p>
      {job.skipped_songs.length > 0 && <Note tone="warning">跳过了曲目:{job.skipped_songs.join('、')}(参演人员未全部提交空闲)。</Note>}

      {job.status === 'succeeded' && (
        <>
          <Note>{job.summary}</Note>
          <StageList job={job} />
          <div className="actions">
            <LinkButton to={`/events/${eventId}/schedule?v=${job.version_id}`} variant="primary">
              查看排练表
            </LinkButton>
          </div>
        </>
      )}

      {job.status === 'infeasible' && (
        <>
          <Note tone="error">
            <b>无解:</b>
            {job.summary}
          </Note>
          {job.attempts.length > 0 && (
            <p className="muted">已尝试的缺席层级:{job.attempts.map((a) => `${a.层级} ${ATTEMPT_TEXT[a.状态] ?? a.状态}`).join('、')}</p>
          )}
          {job.diagnosis && <DiagnosisView d={job.diagnosis} evalDate={evalDate} />}
          <div className="actions">
            <LinkButton to={`/events/${eventId}/progress`}>去填报进度协调</LinkButton>
            <LinkButton to={`/events/${eventId}/rules`}>调整特殊要求</LinkButton>
          </div>
        </>
      )}

      {job.status === 'failed' && (
        <Note tone="error">
          {job.error?.includes('数据有误') || job.error?.includes('没有可排') ? job.error : '求解过程出错,可重试;若反复失败请检查数据。'}
          {job.error && !(job.error.includes('数据有误') || job.error.includes('没有可排')) && (
            <details style={{ marginTop: 6 }}>
              <summary className="muted">错误详情</summary>
              <pre style={{ whiteSpace: 'pre-wrap', fontSize: 11 }}>{job.error}</pre>
            </details>
          )}
        </Note>
      )}
      {job.status === 'cancelled' && <Note>已取消。可以随时重新求解。</Note>}
    </Panel>
  )
}

function StageList({ job }: { job: SolveJob }) {
  if (!job.stage_records.length) return null
  return (
    <ul className="stages">
      {job.stage_records.map((s) => (
        <li key={s.key}>
          <span>{s.label}</span>
          <b>
            {s.value ?? '—'}
            <small className="muted"> {s.status}</small>
          </b>
        </li>
      ))}
    </ul>
  )
}

/** 把逐格的调整建议按成员、日期合并成「10/12 周一 19:00–23:00」 */
function groupAdjustments(rows: { 成员: string; 日期: string; 星期: string; 需开放的格: string }[]) {
  const byMember = new Map<string, Map<string, { weekday: string; hours: number[] }>>()
  for (const r of rows) {
    const h = Number(r.需开放的格.slice(0, 2))
    const days = byMember.get(r.成员) ?? new Map()
    const day = days.get(r.日期) ?? { weekday: r.星期, hours: [] }
    day.hours.push(h)
    days.set(r.日期, day)
    byMember.set(r.成员, days)
  }
  return [...byMember.entries()].map(([member, days]) => {
    let hours = 0
    const parts: string[] = []
    for (const [date, day] of [...days.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
      const hs = [...new Set(day.hours)].sort((a, b) => a - b)
      hours += hs.length
      const ranges: string[] = []
      let start = hs[0]
      let prev = hs[0]
      for (const h of hs.slice(1).concat([NaN])) {
        if (h === prev + 1) {
          prev = h
          continue
        }
        ranges.push(`${String(start).padStart(2, '0')}:00–${String(prev + 1).padStart(2, '0')}:00`)
        start = h
        prev = h
      }
      parts.push(`${fmtMd(date)} ${day.weekday} ${ranges.join('、')}`)
    }
    return { member, hours, text: parts.join(';') }
  })
}

export function DiagnosisView({ d, evalDate }: { d: Diagnosis; evalDate: string }) {
  const gaps = (d.各曲缺口 ?? []).filter((r) => r.全局缺口 > 0 || r.单曲缺口 > 0)
  const near = d.只差一人的时段 ?? []
  const adj = d.最小调整建议
  const ev = d.评估场
  const nearByMember = new Map<string, number>()
  for (const r of near) nearByMember.set(r.只差成员, (nearByMember.get(r.只差成员) ?? 0) + 1)
  const topBlockers = [...nearByMember.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3)

  return (
    <>
      {d.最大覆盖 && (
        <details className="diag" open>
          <summary>
            每首曲目的缺口
            <span className="muted">
              最多可排 {d.最大覆盖.最多可排场次} / {d.最大覆盖.要求场次} 场
            </span>
          </summary>
          {gaps.length === 0 ? (
            <p className="muted">每首曲目单独都排得下,但合在一起冲突;可考虑减少排练次数或放宽要求。</p>
          ) : (
            <div className="tbl-wrap">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>曲目</th>
                    <th className="num">要求</th>
                    <th className="num">单独最多</th>
                    <th className="num">合并后</th>
                    <th className="num">缺口</th>
                  </tr>
                </thead>
                <tbody>
                  {gaps.map((r) => (
                    <tr key={r.曲目} className={r.全局缺口 > 0 ? 'bad' : ''}>
                      <td>
                        {r.曲目} · {r.曲目名}
                      </td>
                      <td className="num">{r.要求场次}</td>
                      <td className="num">{r.单曲最多可排}</td>
                      <td className="num">{r.全局方案已排}</td>
                      <td className="num">{r.全局缺口}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {(d.无候选任务?.length ?? 0) > 0 && <p className="muted">完全没有全员共同时段的排练:{d.无候选任务!.join('、')}</p>}
        </details>
      )}

      {adj && (
        <details className="diag" open={adj.可行}>
          <summary>
            最小调整建议
            <span className="muted">{adj.可行 ? `${adj.受影响成员数} 人 · ${adj.调整小时数} 小时` : '无法给出'}</span>
          </summary>
          {adj.可行 ? (
            <>
              <p className="muted">下面这些人把对应时段改为「有空」后,正规排练基本就能排下(这个估算只看共同空闲和每日上限,不含全部特殊要求,可能还需再调一点):</p>
              <div className="tbl-wrap">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>成员</th>
                      <th className="num">小时</th>
                      <th>需开放的时段</th>
                    </tr>
                  </thead>
                  <tbody>
                    {groupAdjustments(adj.调整).map((g) => (
                      <tr key={g.member}>
                        <td>{g.member}</td>
                        <td className="num">{g.hours}</td>
                        <td style={{ whiteSpace: 'normal' }}>{g.text}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <p className="muted">{adj.状态 ?? '即使放开个人空闲也排不下,请检查每日窗口、特殊要求或排练次数。'}</p>
          )}
        </details>
      )}

      {near.length > 0 && (
        <details className="diag">
          <summary>
            只差一个人的时段
            <span className="muted">
              {near.length} 个{topBlockers.length > 0 && ` · 常卡在 ${topBlockers.map(([m, n]) => `${m}(${n})`).join('、')}`}
            </span>
          </summary>
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>曲目</th>
                  <th>时间</th>
                  <th>只差</th>
                  <th>需开放</th>
                </tr>
              </thead>
              <tbody>
                {near.slice(0, 12).map((r, i) => (
                  <tr key={i}>
                    <td>
                      {r.曲目} · {r.时长}h
                    </td>
                    <td>
                      {fmtMd(r.日期)} {r.星期} {r.时间段}
                    </td>
                    <td>{r.只差成员}</td>
                    <td>{r.需开放的格.join('、')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {near.length > 12 && <p className="muted">只显示最容易补齐的 12 个。</p>}
        </details>
      )}

      {ev && (
        <details className="diag" open={!ev.可行}>
          <summary>
            全员评估({evalDate})<span className="muted">{ev.可行 ? '可以安排' : '没有全员都能到的时段'}</span>
          </summary>
          {ev.可行 ? (
            <p className="muted">评估日有 {ev.可行窗口数} 个可用窗口,正规排练排下后即可安排。</p>
          ) : (
            <>
              <p className="muted">最接近的窗口(缺的人数越少越好):</p>
              <div className="tbl-wrap">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>时段</th>
                      <th className="num">缺人</th>
                      <th>需要协调</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ev.最接近的窗口.slice(0, 5).map((w, i) => (
                      <tr key={i}>
                        <td>
                          {w.时间段}({w.时长}h)
                        </td>
                        <td className="num">{w.缺少人数}</td>
                        <td>
                          {Object.entries(w.阻塞成员)
                            .map(([m, n]) => `${m} ${n}h`)
                            .join('、')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </details>
      )}
    </>
  )
}
