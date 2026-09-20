import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../api/client'
import { keys, useAction, useCalendarInfo } from '../api/hooks'
import type { CalendarInfo } from '../api/types'
import { Button, Panel, Spinner } from '../ui'
import { Modal } from '../ui/Modal'
import { useToast } from '../ui/Toast'

/** 日历订阅(CAL-01~03):私密链接,手机日历订阅后排练表更新自动同步。 */
export function CalendarPanel({ compact = false }: { compact?: boolean }) {
  const cal = useCalendarInfo()
  const qc = useQueryClient()
  const { toast } = useToast()
  const [confirm, setConfirm] = useState(false)
  const rotate = useAction(
    () => api<CalendarInfo>('/api/me/calendar/rotate', { method: 'POST' }),
    (info) => {
      qc.setQueryData(keys.calendar, info)
      setConfirm(false)
      toast('已生成新链接,旧链接失效')
    },
  )
  const copy = async () => {
    if (!cal.data) return
    try {
      await navigator.clipboard.writeText(cal.data.url)
      toast('链接已复制')
    } catch {
      window.prompt('复制这个链接:', cal.data.url)
    }
  }
  return (
    <Panel>
      <h3 className="card-title" style={{ fontSize: 15 }}>
        订阅到手机日历
      </h3>
      <p className="card-copy">{compact ? '订阅后排练表有变动会自动更新,每场提前 1 小时提醒。' : 'iPhone 直接点「添加」;Android / Google 日历用「复制链接」,在日历里「通过网址添加」。订阅后排练表有变动会自动更新,每场提前 1 小时提醒。'}</p>
      {cal.isPending ? (
        <Spinner />
      ) : cal.data ? (
        <div className="actions" style={{ justifyContent: 'flex-start' }}>
          <a className="btn btn--primary" href={cal.data.webcal_url}>
            添加到日历
          </a>
          <Button onClick={() => void copy()}>复制链接</Button>
          <Button variant="ghost" onClick={() => setConfirm(true)}>
            重置链接
          </Button>
        </div>
      ) : null}
      <Modal
        open={confirm}
        title="重置订阅链接?"
        onClose={() => setConfirm(false)}
        actions={
          <Button variant="danger" loading={rotate.isPending} onClick={() => rotate.mutate(undefined)}>
            重置
          </Button>
        }
      >
        <p>旧链接会立刻失效,已订阅的日历需要用新链接重新订阅。链接是私密的,只有不小心泄露时才需要重置。</p>
      </Modal>
    </Panel>
  )
}
