import { useParams } from 'react-router-dom'

import { useEvent } from '../../api/hooks'
import { Back, Badge, Heading, LinkButton, Panel, Spinner } from '../../ui'
import { fmtMd } from '../../utils'

export function SchedulePage() {
  const id = Number(useParams().id)
  const ev = useEvent(id)
  if (ev.isPending) return <Spinner />
  if (!ev.data) return null
  const e = ev.data
  return (
    <>
      <Back to={`/events/${e.id}`} label={`${e.name} · 工作台`} />
      <Heading title="排练表" subtitle="草稿仅管理员可见,校验通过后再发布。" />
      <Panel>
        <Badge tone="neutral">尚未生成</Badge>
        <h2 style={{ marginTop: 15 }}>排程完成后,排练表会出现在这里</h2>
        <p className="muted" style={{ marginTop: 8 }}>
          周视图 / 列表 / 按成员三种视图、拖拽微调、锁定后重排、版本对比与发布,在 M4 接入。正规排练 {fmtMd(e.formal_start_date)}–{fmtMd(e.formal_end_date)},全员评估 {fmtMd(e.eval_date)}。
        </p>
        <div className="actions">
          <LinkButton to={`/events/${e.id}/solve`} variant="primary">
            去排程
          </LinkButton>
        </div>
      </Panel>
    </>
  )
}
