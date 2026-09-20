import { Link } from 'react-router-dom'

import { useAvailability, useEvents } from '../../api/hooks'
import { useAuth } from '../../auth/AuthContext'
import { pickCurrentEvent } from '../../layout/currentEvent'
import { Back, Badge, Empty, Panel, PrimaryBar, LinkButton, Spinner } from '../../ui'
import { fmtMd, weekdayShort } from '../../utils'

export function MemberSchedulePage() {
  const { user } = useAuth()
  const events = useEvents()
  const current = pickCurrentEvent(events.data ?? [])
  const avail = useAvailability(current?.id ?? NaN, user?.member_id ?? NaN)
  if (events.isPending) return <Spinner />
  if (!current) {
    return (
      <>
        <Back to="/" label="返回首页" />
        <h1>我的排练表</h1>
        <Empty title="还没有演出" />
      </>
    )
  }
  const submitted = !!avail.data?.submitted_at
  return (
    <>
      <Back to="/" label="返回首页" />
      <div className="heading">
        <h1>我的排练表</h1>
        <Badge tone="neutral">尚未发布</Badge>
      </div>
      <p className="lead">{current.name}</p>
      <Panel>
        <Badge tone="neutral">尚未发布</Badge>
        <h3 className="card-title" style={{ marginTop: 18 }}>
          排练表正在准备中
        </h3>
        <p className="card-copy">{submitted ? '你的空闲时间已提交,管理员发布后会在这里显示。' : '先填好你的空闲时间,管理员才能安排排练。'}</p>
        <div className="evaluation">
          <strong>
            全员评估 · {fmtMd(current.eval_date)} 周{weekdayShort(current.eval_date)}
          </strong>
          <p>演出前一天只有这一场,全员参加,2–3 小时;具体时段等排练表发布。</p>
        </div>
        <p className="muted">
          发布后这里会按日期列出你的每一场排练,并提供「添加到手机日历」。有临时变动可随时 <Link to={`/events/${current.id}/availability`}>修改空闲时间</Link>。
        </p>
      </Panel>
      <PrimaryBar>
        {submitted ? (
          <LinkButton to="/" variant="primary" full>
            返回首页
          </LinkButton>
        ) : (
          <LinkButton to={`/events/${current.id}/availability`} variant="primary" full>
            去填写空闲时间
          </LinkButton>
        )}
      </PrimaryBar>
    </>
  )
}
