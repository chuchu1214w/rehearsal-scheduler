import { useParams } from 'react-router-dom'

import { useEvent, usePrecheck } from '../../api/hooks'
import { Back, Badge, Button, CheckRow, Heading, LinkButton, Note, Panel, Spinner } from '../../ui'

export function SolvePage() {
  const id = Number(useParams().id)
  const ev = useEvent(id)
  const check = usePrecheck(id)
  if (ev.isPending) return <Spinner />
  if (!ev.data) return null
  const e = ev.data
  const items = check.data?.items ?? []
  const attention = items.filter((i) => i.level !== 'ok').length
  return (
    <>
      <Back to={`/events/${e.id}`} label={`${e.name} · 工作台`} />
      <Heading title="排程" subtitle="先检查,再开始求解。" />
      <Panel>
        <div className="section">
          <h2>求解前检查</h2>
          {check.data && (attention ? <Badge tone="orange">{attention} 项需注意</Badge> : <Badge tone="green">全部通过</Badge>)}
        </div>
        {check.isPending ? (
          <Spinner text="检查中…" />
        ) : (
          items.map((i) => (
            <CheckRow key={i.key} level={i.level}>
              {i.label}
              {i.detail && <span className="muted"> · {i.detail}</span>}
            </CheckRow>
          ))
        )}
        {check.data && !check.data.can_solve && <Note tone="error">请先补齐上面标红的项目。</Note>}
        {check.data?.can_solve && attention > 0 && <Note tone="warning">可以先排已就绪的曲目;未满足的要求会显示在结果诊断中。</Note>}
        <Note>一键求解与结果诊断在下一阶段(M3)接入;现在这一步用来确认数据是否齐全。</Note>
        <div className="actions">
          <LinkButton to={`/events/${e.id}/progress`}>回填报进度</LinkButton>
          <Button variant="primary" disabled title="求解功能尚未接入">
            开始求解
          </Button>
        </div>
      </Panel>
    </>
  )
}
