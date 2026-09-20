import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { useEvent, useEventMembers, useVersion, useVersions } from '../../api/hooks'
import { DayView, sessionsForMember } from '../../components/ScheduleViews'
import { Back, Badge, Heading, Panel, Spinner } from '../../ui'

/** 管理员:某一天的排练日程(从周日历点日期进来) */
export function ScheduleDayPage() {
  const { id: idParam, date = '' } = useParams()
  const id = Number(idParam)
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const ev = useEvent(id)
  const members = useEventMembers(id)
  const versions = useVersions(id)
  const list = versions.data ?? []
  const requested = Number(params.get('v'))
  const selectedId = list.some((v) => v.id === requested) ? requested : (list.find((v) => v.status === 'published')?.id ?? list[0]?.id ?? null)
  const detail = useVersion(selectedId)
  const memberId = params.get('m') ? Number(params.get('m')) : null

  if (ev.isPending || versions.isPending || detail.isPending) return <Spinner />
  if (!ev.data) return null
  const e = ev.data
  const current = list.find((v) => v.id === selectedId)
  const back = `/events/${e.id}/schedule${current ? `?v=${current.id}` : ''}`
  const memberName = memberId != null ? (members.data ?? []).find((m) => m.member_id === memberId)?.display_name : null
  const range = { formal_start_date: e.formal_start_date, formal_end_date: e.formal_end_date, eval_date: e.eval_date, day_start_hour: e.day_start_hour, day_end_hour: e.day_end_hour }
  return (
    <>
      <Back to={back} label="排练表" />
      <Heading
        title="当天日程"
        subtitle={
          current ? (
            <>
              v{current.version_no} <Badge tone={current.status === 'published' ? 'green' : 'neutral'}>{current.status === 'published' ? '已发布' : '草稿'}</Badge>
              {memberName && <> · 只看 {memberName}</>}
            </>
          ) : (
            '还没有排练表'
          )
        }
      />
      <Panel>
        {detail.data ? (
          <DayView date={date} sessions={sessionsForMember(detail.data.sessions, memberId)} range={range} memberId={memberId} onNavigate={(d) => navigate(`/events/${e.id}/schedule/day/${d}?${params.toString()}`)} />
        ) : (
          <p className="muted">还没有生成排练表。</p>
        )}
      </Panel>
    </>
  )
}
