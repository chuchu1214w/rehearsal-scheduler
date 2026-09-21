import { Link, useNavigate } from 'react-router-dom'

import dayjs from 'dayjs'

import { useAvailability, useEventMembers, useEvents, usePublishedSchedule, useSongs } from '../../api/hooks'
import type { RehearsalEvent } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import { pickCurrentEvent } from '../../layout/currentEvent'
import { InstallPushPanel } from '../../components/InstallPushPanel'
import { sessionsForMember } from '../../components/ScheduleViews'
import { Badge, Button, Empty, Note, Panel, PrimaryBar, Spinner } from '../../ui'
import { daysUntilText, fmtMd, hourLabel, planText } from '../../utils'

export function MemberHomePage() {
  const { user } = useAuth()
  const events = useEvents()
  if (events.isPending) return <Spinner />
  const list = events.data ?? []
  const current = pickCurrentEvent(list)
  const name = user?.member_name ?? user?.username ?? ''
  if (!current || !user?.member_id) {
    return (
      <>
        <div className="kicker">你好,{name}</div>
        <h1>我的首页</h1>
        <Empty title="还没有被加入演出" text="管理员把你加进演出后,这里会出现待办。" />
      </>
    )
  }
  return <HomeForEvent event={current} memberId={user.member_id} name={name} others={list.filter((e) => e.id !== current.id)} />
}

function HomeForEvent({ event, memberId, name, others }: { event: RehearsalEvent; memberId: number; name: string; others: RehearsalEvent[] }) {
  const navigate = useNavigate()
  const avail = useAvailability(event.id, memberId)
  const members = useEventMembers(event.id)
  const songs = useSongs(event.id)
  const pub = usePublishedSchedule(event.id)
  if (avail.isPending || pub.isPending) return <Spinner />
  const a = avail.data
  const submitted = !!a?.submitted_at
  const pending = (members.data ?? []).filter((m) => !m.availability_submitted_at).length
  const mine = (songs.data?.songs ?? []).filter((s) => s.members.some((m) => m.id === memberId))
  const othersSongs = (songs.data?.songs ?? []).filter((s) => !mine.includes(s))

  let status = '待填写'
  let heading = '一起,把时间排好'
  let copy: JSX.Element
  const published = pub.data
  const todayStr = dayjs().format('YYYY-MM-DD')
  const upcoming = published ? sessionsForMember(published.sessions, memberId).filter((s) => s.date >= todayStr).sort((a, b) => a.date.localeCompare(b.date) || a.start_slot - b.start_slot) : []
  if (published) {
    status = '已发布'
    heading = upcoming.length ? '排练表已发布' : '排练全部结束'
    const next = upcoming[0]
    copy = next ? (
      <>
        下一场:{fmtMd(next.date)} {next.weekday} {next.time} · {next.kind === 'evaluation' ? '全员评估' : `${next.song_code} ${next.song_name}`}
        {next.location && ` · 📍 ${next.location}`}
        <br />
        共 {sessionsForMember(published.sessions, memberId).filter((s) => s.kind === 'formal').length} 场排练 + 1 场全员评估,可订阅到手机日历。
      </>
    ) : (
      <>这场演出的排练已全部结束,加油!</>
    )
  } else if (submitted) {
    status = '已提交'
    heading = '时间收到,等排练表吧'
    copy = <>{pending > 0 ? `还有 ${pending} 位成员未填。` : '全员已提交。'}排练表发布后,你会在这里看到自己的安排。</>
  } else if (a?.past_deadline) {
    status = '已过截止'
    heading = '请尽快填写空闲时间'
    copy = <>填报已过截止日 {a.deadline ? fmtMd(a.deadline) : ''},仍然可以填写,管理员正在等你。</>
  } else {
    copy = (
      <>
        {a?.deadline ? `请在 ${fmtMd(a.deadline)} 前填写空闲时间。` : '请填写空闲时间。'}
        <br />
        涂出你能来的时段,我们来安排排练。
      </>
    )
  }
  return (
    <>
      <div className="kicker">你好,{name}</div>
      <h1>我的首页</h1>
      <p className="lead">今天,只要处理这一件事。</p>
      <Panel>
        <div className="card-top">
          <span className="muted">{event.name}</span>
          <Badge tone={submitted ? 'green' : a?.past_deadline ? 'orange' : 'accent'}>{status}</Badge>
        </div>
        <h3 className="card-title">{heading}</h3>
        <p className="card-copy">{copy}</p>
        <div className="meta">
          正规排练 {fmtMd(event.formal_start_date)}–{fmtMd(event.formal_end_date)} · 全员评估 {fmtMd(event.eval_date)}
          <br />
          每天 {hourLabel(event.day_start_hour)}–{hourLabel(event.day_end_hour)} · {daysUntilText(event.days_until_performance)}
        </div>
      </Panel>
      <InstallPushPanel compact />
      <Panel>
        <div className="card-top" style={{ marginBottom: 10 }}>
          <h3 className="card-title" style={{ fontSize: 16 }}>
            这场演出
          </h3>
          <span className="muted">{event.member_count} 人 · {event.song_count} 首</span>
        </div>
        <div className="kicker" style={{ marginTop: 10 }}>我的曲目 · {mine.length} 首</div>
        {mine.map((s) => (
          <div key={s.id} className="session" style={{ gridTemplateColumns: '1fr' }}>
            <div>
              <div className="session__title">
                {s.code} · {s.name} <Badge tone="neutral">{s.difficulty}</Badge>
              </div>
              <p>
                {planText(s.durations)} · 和 {s.members.filter((m) => m.id !== memberId).map((m) => m.display_name).join('、') || '(独舞)'}
              </p>
            </div>
          </div>
        ))}
        {mine.length === 0 && <p className="muted">还没有你参演的曲目。</p>}
        {othersSongs.length > 0 && (
          <details>
            <summary>全部曲目 · {songs.data?.songs.length ?? 0} 首</summary>
            {othersSongs.map((s) => (
              <p key={s.id} className="muted" style={{ padding: '4px 0' }}>
                {s.code} · {s.name} · {s.members.map((m) => m.display_name).join('、')}
              </p>
            ))}
          </details>
        )}
        <details>
          <summary>人员 · {event.member_count} 人</summary>
          <p className="muted">{(members.data ?? []).map((m) => m.display_name).join('、')}</p>
        </details>
      </Panel>
      {others.length > 0 && (
        <Note>
          你还参加了 {others.map((e) => e.name).join('、')}。
          <br />
          {others.map((e) => (
            <Link key={e.id} to={`/events/${e.id}/availability`} style={{ marginRight: 10 }}>
              填 {e.name} 的空闲 →
            </Link>
          ))}
        </Note>
      )}
      <PrimaryBar note={published ? '有临时变动可在「账号 → 修改空闲时间」或排练表页修改。' : submitted ? '提交后仍可修改;修改后排练表可能受影响。' : '大约 2 分钟 · 支持连续涂格、复制上一天'}>
        {published ? (
          <Button variant="primary" full onClick={() => navigate('/schedule')}>
            查看我的排练表
          </Button>
        ) : (
          <Button variant="primary" full onClick={() => navigate(`/events/${event.id}/availability`)}>
            {submitted ? '修改空闲时间' : '去填写空闲时间'}
          </Button>
        )}
      </PrimaryBar>
    </>
  )
}
