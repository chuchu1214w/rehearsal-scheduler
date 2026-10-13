import { useEffect, useRef, useState } from 'react'

import type { AdvisorRun } from '../api/types'
import { API_BASE, isNative, onExternalLinkClick } from '../native'
import { Button } from '../ui'
import { Modal } from '../ui/Modal'

// v2:同意的范围扩大到「AI 修改」(会发送排练表与修改要求),之前同意过的也再确认一次
const CONSENT_KEY = 'season.ai-consent.v2'

const LOG_LABEL: Record<AdvisorRun['log'][number]['kind'], string> = {
  info: '开始',
  think: '思考',
  text: '说明',
  tool: '操作',
  result: '结果',
  done: '完成',
}

/** 第一次使用 AI 前说明数据去向并征得同意;同意过的浏览器 / App 不再重复询问 */
export function useAiConsent(onAgree: () => void) {
  const [open, setOpen] = useState(false)
  const ask = () => {
    let agreed = false
    try {
      agreed = localStorage.getItem(CONSENT_KEY) === '1'
    } catch {
      /* 存储不可用时每次都询问 */
    }
    if (agreed) onAgree()
    else setOpen(true)
  }
  const agree = () => {
    try {
      localStorage.setItem(CONSENT_KEY, '1')
    } catch {
      /* 忽略 */
    }
    setOpen(false) // 先关掉;出错(如服务器没配置密钥)时提示会显示在页面上
    onAgree()
  }
  return { open, close: () => setOpen(false), ask, agree }
}

export function AiConsentModal({ open, loading, onClose, onAgree }: { open: boolean; loading: boolean; onClose: () => void; onAgree: () => void }) {
  return (
    <Modal
      open={open}
      title="使用 AI 前请确认"
      onClose={onClose}
      actions={
        <>
          <Button onClick={onClose}>不用了</Button>
          <Button variant="primary" loading={loading} onClick={onAgree}>
            同意并开始
          </Button>
        </>
      }
    >
      <p className="advisor-consent">
        AI 调度员和 AI 修改由 Anthropic 公司的 Claude 提供。开始后,服务器会把<b>本演出的排程数据</b>发送给 Anthropic:演出日期、曲目、成员昵称、各人的空闲时间和特殊要求;用 AI 修改时还包括那一版排练表和你输入的修改要求。
      </p>
      <p className="advisor-consent">不会发送用户名、密码、推送令牌或联系方式。按 Anthropic 的商业服务条款,这些数据不会被用于训练模型。AI 只给建议,任何改动都要你确认后才生效。</p>
      <p className="advisor-consent">
        详见{' '}
        <a href={isNative() ? `${API_BASE}/api/go/privacy` : '/privacy'} target="_blank" rel="noreferrer" onClick={onExternalLinkClick}>
          隐私政策
        </a>
        。
      </p>
    </Modal>
  )
}

/** AI 的思考过程(运行中展开并滚到最新一步) */
export function AiLog({ run, running }: { run: Pick<AdvisorRun, 'log' | 'elapsed_seconds' | 'cost_usd'>; running: boolean }) {
  const ref = useRef<HTMLOListElement>(null)
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight })
  }, [run.log.length])
  if (run.log.length === 0) return null
  return (
    <details className="advisor-log" open={running}>
      <summary className="muted">
        思考过程 · {run.log.length} 步{run.elapsed_seconds != null && ` · ${Math.round(run.elapsed_seconds)} 秒`}
        {run.cost_usd != null && run.cost_usd > 0 && ` · 约 $${run.cost_usd.toFixed(2)}`}
      </summary>
      <ol ref={ref}>
        {run.log.map((x, i) => (
          <li key={i} className={`advisor-log__item advisor-log__item--${x.kind}`}>
            <span className="advisor-log__tag">{LOG_LABEL[x.kind] ?? x.kind}</span>
            <span>{x.text}</span>
          </li>
        ))}
      </ol>
    </details>
  )
}
