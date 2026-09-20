import { Link, useNavigate, useParams } from 'react-router-dom'

import { useEvent } from '../../api/hooks'
import type { Step } from '../../api/types'
import { Badge, Heading, LinkButton, Spinner, Steps } from '../../ui'
import { daysUntilText, fmtMd } from '../../utils'

const ROUTES: Record<string, string> = { info: 'info', members: 'people', songs: 'songs', rules: 'rules', availability: 'progress', solve: 'solve', schedule: 'schedule' }
const TITLES: Record<string, string> = { info: '演出信息', members: '人员', songs: '曲目', rules: '特殊排程要求', availability: '填报', solve: '排程', schedule: '排练表' }
const ACTIONS: Record<string, string> = { info: '修改信息', members: '管理人员', songs: '管理曲目', rules: '管理要求', availability: '查看进度', solve: '去排程', schedule: '查看排练表' }

function stateBadge(s: Step) {
  if (s.state === 'done') return <Badge tone="green">已完成</Badge>
  if (s.state === 'current') return <Badge>进行中</Badge>
  return <Badge tone="neutral">待开始</Badge>
}

export function WorkbenchPage() {
  const id = Number(useParams().id)
  const navigate = useNavigate()
  const ev = useEvent(id)
  if (ev.isPending) return <Spinner />
  if (ev.isError || !ev.data) {
    return (
      <div className="empty">
        <h1>找不到这场演出</h1>
        <p>
          <Link to="/">返回演出列表</Link>
        </p>
      </div>
    )
  }
  const e = ev.data
  const solveBlocked = e.member_count === 0 || e.song_count === 0
  return (
    <>
      <Heading title="工作台" subtitle={`${e.name} · ${fmtMd(e.performance_date)} 演出 · ${daysUntilText(e.days_until_performance)}`} action={<LinkButton to="/events/new">＋ 新建演出</LinkButton>} />
      <Steps steps={e.steps} eventId={e.id} />
      <div className="cards">
        {e.steps.map((s) => {
          const disabled = s.key === 'solve' && solveBlocked
          const extra = s.key === 'solve' && e.member_count > 0 && e.song_count > 0 && e.submitted_count < e.member_count ? `还差 ${e.member_count - e.submitted_count} 人;点进度条「排程」可先检查。` : ''
          return (
            <section key={s.key} className={'card' + (s.state === 'current' ? ' card--current' : '')}>
              <span className="card__num">{String(s.no).padStart(2, '0')}</span>
              <h3>
                {TITLES[s.key] ?? s.label} <span className="muted" style={{ marginLeft: 6 }}>{stateBadge(s)}</span>
              </h3>
              <p>{s.summary}</p>
              <button type="button" className="btn" disabled={disabled} onClick={() => navigate(`/events/${e.id}/${ROUTES[s.key]}`)}>
                {ACTIONS[s.key]}
              </button>
              {extra && <small className="muted">{extra}</small>}
            </section>
          )
        })}
      </div>
    </>
  )
}
