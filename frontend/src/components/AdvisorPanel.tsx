import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import { keys, useAction, useInvalidateEvent, useLatestAdvisor } from '../api/hooks'
import type { AdvisorRun } from '../api/types'
import { Badge, Button, Note, Panel, Spinner } from '../ui'
import { Modal } from '../ui/Modal'
import { useToast } from '../ui/Toast'
import { AiConsentModal, AiLog, useAiConsent } from './AiShared'

/** AI 调度员:无解时让 Claude 试算调整、给出方案;管理员逐条允许后才执行(开发文档 §5.11) */
export function AdvisorPanel({ eventId, onResolve, resolving }: { eventId: number; onResolve: () => void; resolving: boolean }) {
  const qc = useQueryClient()
  const invalidate = useInvalidateEvent()
  const { toast } = useToast()
  const latest = useLatestAdvisor(eventId)
  const run = latest.data ?? null
  const running = !!run && (run.status === 'running' || run.status === 'queued')
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const [confirm, setConfirm] = useState(false)

  // 新方案出来时默认全选(已执行的除外)
  const proposalKey = run?.status === 'done' ? run.id : null
  useEffect(() => {
    if (run?.status !== 'done' || !run.proposal) return
    setPicked(new Set(run.proposal.changes.map((_, i) => i).filter((i) => !run.applied.includes(i))))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [proposalKey])

  const setRun = (r: AdvisorRun) => qc.setQueryData(keys.latestAdvisor(eventId), r)
  const start = useAction(() => api<AdvisorRun>(`/api/events/${eventId}/advisor`, { method: 'POST', json: { consent: true } }), (r) => {
    consent.close()
    setRun(r)
  })
  const consent = useAiConsent(() => start.mutate(undefined))
  const begin = consent.ask
  const cancel = useAction(() => api<AdvisorRun>(`/api/advisor-runs/${run?.id}/cancel`, { method: 'POST' }), setRun)
  const apply = useAction(
    (indices: number[]) => api<AdvisorRun>(`/api/advisor-runs/${run?.id}/apply`, { method: 'POST', json: { indices } }),
    (r) => {
      setRun(r)
      setConfirm(false)
      invalidate(eventId)
      void qc.invalidateQueries({ queryKey: ['precheck', eventId] })
      toast('已按所选调整修改,可以重新求解了')
    },
  )

  if (latest.isPending) return <Spinner />

  const changes = run?.proposal?.changes ?? []
  const selected = [...picked].filter((i) => !run?.applied.includes(i)).sort((a, b) => a - b)
  const toggle = (i: number) =>
    setPicked((s) => {
      const next = new Set(s)
      if (next.has(i)) next.delete(i)
      else next.add(i)
      return next
    })
  const check = run?.proposal?.check
  const appliedAny = (run?.applied.length ?? 0) > 0

  return (
    <Panel>
      <div className="section">
        <h2>AI 调度员</h2>
        {run && <Badge tone={run.status === 'done' ? 'green' : run.status === 'failed' ? 'red' : running ? 'accent' : 'neutral'}>{{ queued: '排队中', running: '思考中', done: '方案已生成', failed: '出错', cancelled: '已取消' }[run.status]}</Badge>}
      </div>

      {!running && run?.status !== 'done' && (
        <>
          <p className="muted">
            让 Claude 读诊断、试算各种调整(提高允许的缺席、放宽特殊要求、拆分场次),用求解器逐一验证,最后给你一份能直接执行的方案。不会动成员的空闲时间;也不会自动改任何东西,每一条都要你允许。
          </p>
          {run?.status === 'failed' && <Note tone="error">{run.error?.split('\n')[0] || '出错了'},可以重试。</Note>}
          <div className="actions">
            <Button variant="primary" loading={start.isPending} onClick={begin}>
              让 AI 调度员想办法
            </Button>
          </div>
        </>
      )}

      {run && (running || run.status === 'done') && <AiLog run={run} running={running} />}

      {running && (
        <>
          <div className="progressbar progressbar--busy">
            <span />
          </div>
          <p className="muted">{run?.progress || '准备中…'}</p>
          <div className="actions">
            <Button variant="ghost-danger" loading={cancel.isPending} onClick={() => cancel.mutate(undefined)}>
              停止
            </Button>
          </div>
        </>
      )}

      {run?.status === 'done' && run.proposal && (
        <>
          <Note>{run.proposal.summary}</Note>
          {check && (
            <p className="muted">
              按全部调整试算:
              {check.全部排完 ? `能全部排完(${check.使用层级}${check.缺席场次 ? `,缺席 ${check.缺席场次} 场` : ',全员到齐'})` : (check.最多能排 ?? check.说明 ?? '仍然无解')}
              {check.注意 && `;${check.注意}`}
            </p>
          )}
          {(run.proposal.song_plans?.length ?? 0) > 0 && (
            <>
              <div className="kicker">按曲目的场次建议 · 改成这样就能排下</div>
              <table className="tbl advisor-plans">
                <thead>
                  <tr>
                    <th>曲目</th>
                    <th>现在</th>
                    <th>建议</th>
                    <th>说明</th>
                  </tr>
                </thead>
                <tbody>
                  {run.proposal.song_plans!.map((p, i) => (
                    <tr key={i}>
                      <td>
                        {p.song} · {p.song_name}
                      </td>
                      <td>{p.current}</td>
                      <td>
                        <b>{p.suggested}</b>
                      </td>
                      <td className="muted">{p.note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="kicker">推荐执行的调整</div>
            </>
          )}
          <ul className="advisor-changes">
            {changes.map((c, i) => {
              const done = run.applied.includes(i)
              return (
                <li key={i} className={done ? 'is-done' : ''}>
                  <label>
                    <input type="checkbox" checked={done || picked.has(i)} disabled={done} onChange={() => toggle(i)} />
                    <span>
                      <Badge tone={c.kind === 'setting' ? 'orange' : 'neutral'}>{c.kind_label}</Badge> {c.description}
                      {done && <b className="advisor-changes__done"> · 已执行</b>}
                      {c.reason && <span className="muted advisor-changes__reason">{c.reason}</span>}
                    </span>
                  </label>
                </li>
              )
            })}
          </ul>
          <div className="actions">
            <Button variant="ghost" loading={start.isPending} onClick={begin}>
              再想一次
            </Button>
            <Button disabled={selected.length === 0} loading={apply.isPending} onClick={() => setConfirm(true)}>
              允许并执行所选({selected.length})
            </Button>
            {appliedAny && (
              <Button variant="primary" loading={resolving} onClick={onResolve}>
                重新求解
              </Button>
            )}
          </div>
        </>
      )}

      <AiConsentModal open={consent.open} loading={start.isPending} onClose={consent.close} onAgree={consent.agree} />

      <Modal
        open={confirm}
        title="执行所选调整"
        onClose={() => setConfirm(false)}
        actions={
          <>
            <Button onClick={() => setConfirm(false)}>再看看</Button>
            <Button variant="primary" loading={apply.isPending} onClick={() => apply.mutate(selected)}>
              允许并执行
            </Button>
          </>
        }
      >
        <ul className="advisor-confirm">
          {selected.map((i) => (
            <li key={i}>{changes[i]?.description}</li>
          ))}
        </ul>
      </Modal>
    </Panel>
  )
}
