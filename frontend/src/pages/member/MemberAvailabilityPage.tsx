import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { api } from '../../api/client'
import { useAction, useAvailability, useEvent, useInvalidateEvent, usePublishedSchedule } from '../../api/hooks'
import type { Availability } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import { AvailabilityGrid, countFilled } from '../../components/AvailabilityGrid'
import { Back, Button, Note, PrimaryBar, Spinner } from '../../ui'
import { useToast } from '../../ui/Toast'
import { fmtMd } from '../../utils'

export function MemberAvailabilityPage() {
  const id = Number(useParams().id)
  const { user } = useAuth()
  const memberId = user?.member_id ?? NaN
  const navigate = useNavigate()
  const invalidate = useInvalidateEvent()
  const { toast } = useToast()
  const ev = useEvent(id)
  const avail = useAvailability(id, memberId)
  const pub = usePublishedSchedule(id)
  const [days, setDays] = useState<Record<string, string> | null>(null)
  const [dirty, setDirty] = useState(false)
  useEffect(() => {
    if (avail.data && days === null) setDays(avail.data.days)
  }, [avail.data, days])
  const save = useAction(
    (submit: boolean) => api<Availability>(`/api/events/${id}/availability/${memberId}`, { method: 'PUT', json: { days, submit } }),
    (_r, submit) => {
      invalidate(id)
      void avail.refetch()
      setDirty(false)
      if (submit) {
        toast('空闲时间已提交,等待管理员安排排练')
        navigate('/')
      } else toast('已保存草稿')
    },
  )
  if (ev.isPending || avail.isPending || days === null) return <Spinner />
  if (!ev.data || !avail.data) return null
  const a = avail.data
  const filled = countFilled(days)
  const unfilled = a.dates.length - filled
  const editing = !!a.submitted_at
  return (
    <>
      <Back to="/" label="返回首页" />
      <div className="heading" style={{ marginBottom: 6 }}>
        <h1>填空闲时间</h1>
        <span className="muted" style={{ whiteSpace: 'nowrap' }}>
          已填 {filled} / {a.dates.length} 天
        </span>
      </div>
      <p className="lead">选一种画笔,点一下或按住滑过时段。</p>
      {pub.data ? (
        <Note tone="warning">排练表已发布(v{pub.data.version_no})。修改后重新提交,管理员会看到哪些场次受影响,并决定是否重排;你的排练表在管理员发布新版本前不变。</Note>
      ) : (
        editing && <Note>你已提交过;修改后需重新提交,排练表可能受影响。</Note>
      )}
      {a.past_deadline && <Note tone="warning">已过截止日 {a.deadline ? fmtMd(a.deadline) : ''},仍可填写。</Note>}
      <AvailabilityGrid
        availability={a}
        days={days}
        onChange={(d) => {
          setDays(d)
          setDirty(true)
        }}
      />
      <PrimaryBar note={unfilled > 0 ? `${unfilled} 天未填写,将按「不可排」提交。` : '全部天数已填写。'}>
        <div className="inline" style={{ flexWrap: 'nowrap' }}>
          <Button full loading={save.isPending} disabled={!dirty} onClick={() => save.mutate(false)}>
            保存草稿
          </Button>
          <Button full variant="primary" loading={save.isPending} disabled={filled === 0} onClick={() => save.mutate(true)}>
            {editing ? '重新提交' : '提交空闲时间'}
          </Button>
        </div>
      </PrimaryBar>
    </>
  )
}
