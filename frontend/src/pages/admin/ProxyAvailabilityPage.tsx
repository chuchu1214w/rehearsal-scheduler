import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { api } from '../../api/client'
import { useAction, useAvailability, useEvent, useInvalidateEvent } from '../../api/hooks'
import type { Availability } from '../../api/types'
import { AvailabilityGrid, countFilled } from '../../components/AvailabilityGrid'
import { Back, Badge, Button, Heading, Note, Panel, PrimaryBar, Spinner } from '../../ui'
import { useToast } from '../../ui/Toast'
import { fmtDateTime } from '../../utils'

export function ProxyAvailabilityPage() {
  const params = useParams()
  const id = Number(params.id)
  const memberId = Number(params.memberId)
  const navigate = useNavigate()
  const invalidate = useInvalidateEvent()
  const { toast } = useToast()
  const ev = useEvent(id)
  const avail = useAvailability(id, memberId)
  const [days, setDays] = useState<Record<string, string> | null>(null)
  useEffect(() => {
    if (avail.data && days === null) setDays(avail.data.days)
  }, [avail.data, days])
  const save = useAction(
    (submit: boolean) => api<Availability>(`/api/events/${id}/availability/${memberId}`, { method: 'PUT', json: { days, submit } }),
    (_r, submit) => {
      invalidate(id)
      toast(submit ? '已保存并标记为已提交(管理员代填)' : '已保存')
      navigate(`/events/${id}/progress`)
    },
  )
  if (ev.isPending || avail.isPending || days === null) return <Spinner />
  if (!ev.data || !avail.data) return null
  const a = avail.data
  return (
    <>
      <Back to={`/events/${id}/progress`} label="填报进度" />
      <Heading title={`代填 · ${a.display_name}`} subtitle={<>{a.submitted_at ? `本人已于 ${fmtDateTime(a.submitted_at)} 提交` : '尚未提交'} · 已填 {countFilled(days)} / {a.dates.length} 天</>} action={<Badge tone="orange">管理员代填</Badge>} />
      <Panel>
        <AvailabilityGrid availability={a} days={days} onChange={setDays} />
      </Panel>
      {a.past_deadline && <Note tone="warning">已过填报截止日,仍可修改。</Note>}
      <PrimaryBar note={`保存后会标注“管理员代填”;${a.submitted_at ? '成员的提交状态保持不变' : '可选择同时标记为已提交'}。`}>
        <div className="inline" style={{ flexWrap: 'nowrap' }}>
          <Button full loading={save.isPending} onClick={() => save.mutate(false)}>
            仅保存
          </Button>
          <Button full variant="primary" loading={save.isPending} onClick={() => save.mutate(true)}>
            保存并标记已提交
          </Button>
        </div>
      </PrimaryBar>
    </>
  )
}
