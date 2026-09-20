import { useNavigate, useParams } from 'react-router-dom'

import { useEvent } from '../../api/hooks'
import { Back, Heading, Panel, Spinner } from '../../ui'
import { InfoEditor } from './editors/InfoEditor'
import { PeopleEditor } from './editors/PeopleEditor'
import { RulesEditor } from './editors/RulesEditor'
import { SongsEditor } from './editors/SongsEditor'

const META = {
  info: { title: '演出设置', desc: '只填三项,排练区间与评估日自动算出。' },
  people: { title: '人员与账号', desc: '人员直接属于这场演出,下一场可以沿用;在这里给大家开通账号。' },
  songs: { title: '曲目', desc: '难度自动给出排练次数与时长,也可以手动改。' },
  rules: { title: '特殊排程要求', desc: '硬性要求必须满足;“尽量”用于排不开时的取舍。' },
} as const

export function EditorPage({ kind }: { kind: keyof typeof META }) {
  const id = Number(useParams().id)
  const navigate = useNavigate()
  const ev = useEvent(id)
  if (ev.isPending) return <Spinner />
  if (!ev.data) return <p className="muted">找不到这场演出。</p>
  const e = ev.data
  return (
    <>
      <Back to={`/events/${e.id}`} label={`${e.name} · 工作台`} />
      <Heading title={META[kind].title} subtitle={META[kind].desc} />
      <Panel>
        {kind === 'info' && <InfoEditor event={e} onSaved={() => navigate(`/events/${e.id}`)} />}
        {kind === 'people' && <PeopleEditor event={e} />}
        {kind === 'songs' && <SongsEditor event={e} />}
        {kind === 'rules' && <RulesEditor event={e} />}
      </Panel>
    </>
  )
}
