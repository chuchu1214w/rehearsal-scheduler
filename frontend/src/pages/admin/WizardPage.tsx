import { useNavigate, useParams } from 'react-router-dom'

import { useEvent } from '../../api/hooks'
import { Button, Heading, LinkButton, Panel, Spinner } from '../../ui'
import { InfoEditor } from './editors/InfoEditor'
import { PeopleEditor } from './editors/PeopleEditor'
import { RulesEditor } from './editors/RulesEditor'
import { SongsEditor } from './editors/SongsEditor'

const STEPS = ['演出信息', '人员', '曲目', '特殊要求']

function WizardTabs({ step, eventId }: { step: number; eventId: number | null }) {
  const navigate = useNavigate()
  return (
    <div className="wizardsteps">
      {STEPS.map((t, i) => (
        <button key={t} type="button" className={step === i + 1 ? 'is-active' : ''} disabled={eventId === null && i > 0} onClick={() => eventId !== null && navigate(`/events/${eventId}/wizard/${i + 1}`)}>
          {i + 1} {t}
        </button>
      ))}
    </div>
  )
}

/** /events/new:第 ① 步,创建演出后进入第 ② 步 */
export function NewEventPage() {
  const navigate = useNavigate()
  return (
    <>
      <Heading title="新建演出" subtitle="每一步都可稍后填写,退出后保留草稿。" action={<LinkButton to="/">取消</LinkButton>} />
      <WizardTabs step={1} eventId={null} />
      <Panel>
        <InfoEditor submitLabel="下一步 →" onSaved={(ev) => navigate(`/events/${ev.id}/wizard/2`, { replace: true })} />
      </Panel>
    </>
  )
}

export function WizardPage() {
  const params = useParams()
  const id = Number(params.id)
  const step = Math.min(4, Math.max(1, Number(params.step) || 1))
  const navigate = useNavigate()
  const ev = useEvent(id)
  if (ev.isPending) return <Spinner />
  if (!ev.data) return <p className="muted">找不到这场演出。</p>
  const e = ev.data
  const go = (s: number) => (s > 4 ? navigate(`/events/${e.id}`) : navigate(`/events/${e.id}/wizard/${s}`))
  return (
    <>
      <Heading title="新建演出" subtitle={`${e.name} · 每一步都可稍后填写,退出后保留草稿。`} action={<Button onClick={() => navigate(`/events/${e.id}`)}>保存并退出</Button>} />
      <WizardTabs step={step} eventId={e.id} />
      <Panel>
        {step === 1 && <InfoEditor event={e} submitLabel="保存,下一步 →" onSaved={() => go(2)} />}
        {step === 2 && <PeopleEditor event={e} wizard />}
        {step === 3 && <SongsEditor event={e} />}
        {step === 4 && <RulesEditor event={e} />}
      </Panel>
      {step > 1 && (
        <div className="wizardfoot">
          <Button variant="ghost" onClick={() => go(step + 1)}>
            稍后再填
          </Button>
          <div className="inline">
            <Button onClick={() => go(step - 1)}>上一步</Button>
            <Button variant="primary" onClick={() => go(step + 1)}>
              {step === 4 ? '完成,进入工作台' : '下一步 →'}
            </Button>
          </div>
        </div>
      )}
    </>
  )
}
