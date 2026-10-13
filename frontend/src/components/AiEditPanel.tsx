import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { ApiError, api } from '../api/client'
import { keys, useAction, useLatestAiEdit } from '../api/hooks'
import type { AiEditRun, EditResult, ScheduleVersion } from '../api/types'
import { Badge, Button, Note, Panel } from '../ui'
import { AiConsentModal, AiLog, useAiConsent } from './AiShared'

const EXAMPLES = ['把第一首周三那场挪到周四晚上 7 点', '第二首最后一场缩短一小时', '10 月 12 日不排练,那天的场次挪到附近大家有空的时间']

/** 用一句话修改排练表:Claude 只给方案(开发文档 §4.8 EDIT-12),管理员看过每条修改与冲突后点「应用」才写入,可撤销 */
export function AiEditPanel({
  eventId,
  version,
  revision,
  disabled,
  onApplied,
}: {
  eventId: number
  version: ScheduleVersion
  /** 页面上这一版当前的修改次数(用来判断方案是否已过期) */
  revision: number | undefined
  disabled: boolean
  onApplied: (r: EditResult) => void
}) {
  const qc = useQueryClient()
  const latest = useLatestAiEdit(eventId)
  const [text, setText] = useState('')
  const [dismissed, setDismissed] = useState<number | null>(null)
  const run = latest.data ?? null
  const running = !!run && (run.status === 'running' || run.status === 'queued')
  const here = !!run && run.version_id === version.id
  const setRun = (r: AiEditRun) => qc.setQueryData(keys.latestAiEdit(eventId), r)

  const start = useAction(
    (instruction: string) => api<AiEditRun>(`/api/schedules/${version.id}/ai-edit`, { method: 'POST', json: { instruction, consent: true } }),
    (r) => {
      consent.close()
      setRun(r)
    },
  )
  const consent = useAiConsent(() => start.mutate(text.trim()))
  const cancel = useAction(() => api<AiEditRun>(`/api/advisor-runs/${run?.id}/cancel`, { method: 'POST' }), setRun)
  const apply = useAction(
    async (r: AiEditRun) => {
      try {
        return await api<EditResult>(`/api/schedules/${version.id}/ops/batch`, {
          method: 'POST',
          // 按字符截断(不拆开 emoji 等占两个 UTF-16 单位的字符)
          json: { ops: r.proposal!.ops, summary: Array.from(`AI 修改:${r.instruction}`).slice(0, 200).join(''), expected_revision: r.proposal!.revision ?? null, ai_run_id: r.id },
        })
      } catch (err) {
        // 409:排练表期间改过 / 方案已应用过 → 刷新这一版与方案状态,界面会提示重新生成
        if (err instanceof ApiError && err.status === 409) {
          void qc.invalidateQueries({ queryKey: keys.version(version.id) })
          void qc.invalidateQueries({ queryKey: keys.latestAiEdit(eventId) })
        }
        throw err
      }
    },
    (r, applied) => {
      setText('')
      // 先在缓存里记下「已应用」,免得新版本写进缓存后短暂显示「方案已过期」
      qc.setQueryData<AiEditRun | null>(keys.latestAiEdit(eventId), (old) => (old && old.id === applied.id ? { ...old, applied: [r.version.id] } : old))
      void qc.invalidateQueries({ queryKey: keys.latestAiEdit(eventId) })
      onApplied(r)
    },
  )

  const p = here && run?.status === 'done' && dismissed !== run.id ? run.proposal : null
  const applied = (run?.applied.length ?? 0) > 0
  // 方案生成后这一版又被改过(或改过后发布了):应用时会对不上修改次数,直接提示重新生成
  const stale = !!p && p.revision != null && revision != null && p.revision < revision
  // 方案比页面上的这一版还新(别的窗口 / 设备改过):是页面过期了,刷新这一版
  const behind = !!p && p.revision != null && revision != null && p.revision > revision
  useEffect(() => {
    if (behind) void qc.invalidateQueries({ queryKey: keys.version(version.id) })
  }, [behind, qc, version.id])

  return (
    <Panel className="ai-edit">
      <div className="section">
        <h2>AI 修改</h2>
        {here && run && <Badge tone={run.status === 'done' ? 'green' : run.status === 'failed' ? 'red' : running ? 'accent' : 'neutral'}>{{ queued: '排队中', running: '思考中', done: applied ? '已应用' : '方案已生成', failed: '出错', cancelled: '已取消' }[run.status]}</Badge>}
      </div>
      <p className="muted">用一句话说要怎么改,AI 会先试算再给出方案。它不会直接改排练表:你看过每条修改和会不会冲突,点「应用」才生效,而且可以撤销。</p>

      {!running && !p && (
        <>
          <label className="field">
            <textarea value={text} maxLength={500} rows={2} placeholder={`例如:${EXAMPLES[0]}`} onChange={(ev) => setText(ev.target.value)} aria-label="修改要求" />
          </label>
          <div className="ai-edit__examples">
            {EXAMPLES.map((x) => (
              <button key={x} type="button" onClick={() => setText(x)}>
                {x}
              </button>
            ))}
          </div>
          {here && run?.status === 'failed' && <Note tone="error">{run.error?.split('\n')[0] || '出错了'},可以重试。</Note>}
          <div className="actions">
            <Button variant="primary" disabled={disabled || text.trim().length < 2} loading={start.isPending} onClick={consent.ask}>
              让 AI 出方案
            </Button>
          </div>
        </>
      )}

      {running && (
        <>
          {!here && <Note>AI 正在处理另一版排练表的修改,请稍候。</Note>}
          {here && run && <p className="ai-edit__ask">「{run.instruction}」</p>}
          {here && run && <AiLog run={run} running />}
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

      {p && run && (
        <>
          <p className="ai-edit__ask">「{run.instruction}」</p>
          <AiLog run={run} running={false} />
          <Note tone={p.ops.length ? 'info' : 'warning'}>{p.summary || (p.ops.length ? '' : 'AI 没有给出修改')}</Note>
          {p.lines.length > 0 && (
            <ol className="ai-edit__lines">
              {p.lines.map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ol>
          )}
          {p.new_issues.length > 0 && (
            <Note tone="error">
              <b>应用后会新增 {p.new_issues.length} 处冲突</b>(仍可应用,冲突会标红,发布前要解决):
              <ul className="issue-list">
                {p.new_issues.map((x, i) => (
                  <li key={i}>{x}</li>
                ))}
              </ul>
            </Note>
          )}
          {p.ops.length > 0 && p.new_issues.length === 0 && <p className="muted">试算结果:不会带来新的冲突{p.issues.length ? `(原有的 ${p.issues.length} 处冲突仍在)` : ''}。</p>}
          {p.notices.length > 0 && <p className="muted">提醒:{p.notices.join(';')}</p>}
          {stale && !applied && <Note tone="warning">方案生成后排练表又改过了,请重新生成。</Note>}
          {version.status !== 'draft' && p.ops.length > 0 && !applied && <p className="muted">这一版已{version.status === 'published' ? '发布' : '归档'},应用时会先复制成新草稿。</p>}
          <div className="actions">
            <Button variant="ghost" onClick={() => setDismissed(run.id)}>
              {applied || !p.ops.length ? '收起' : '不用了'}
            </Button>
            {p.ops.length > 0 && !applied && (
              <Button variant="primary" disabled={disabled || stale} loading={apply.isPending} onClick={() => apply.mutate(run)}>
                应用(可撤销)
              </Button>
            )}
          </div>
        </>
      )}

      <AiConsentModal open={consent.open} loading={start.isPending} onClose={consent.close} onAgree={consent.agree} />
    </Panel>
  )
}
