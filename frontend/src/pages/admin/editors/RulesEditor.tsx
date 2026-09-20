import { useState } from 'react'

import { useToast } from '../../../ui/Toast'
import { api } from '../../../api/client'
import { useAction, useEventMembers, useInvalidateEvent, useRuleTypes, useRules, useSongs } from '../../../api/hooks'
import type { RehearsalEvent, Rule, RuleType } from '../../../api/types'
import { Badge, Button, Note, Spinner } from '../../../ui'
import { Modal } from '../../../ui/Modal'
import { hourLabel } from '../../../utils'

interface Props {
  event: RehearsalEvent
}

export function RulesEditor({ event }: Props) {
  const invalidate = useInvalidateEvent()
  const rules = useRules(event.id)
  const [adding, setAdding] = useState(false)
  const toggle = useAction((r: Rule) => api(`/api/rules/${r.id}`, { method: 'PATCH', json: { enabled: !r.enabled } }), () => invalidate(event.id))
  const remove = useAction((r: Rule) => api(`/api/rules/${r.id}`, { method: 'DELETE' }), () => invalidate(event.id))
  const list = rules.data ?? []
  return (
    <>
      <div className="section">
        <h3>用一句话描述特殊情况</h3>
        <Button onClick={() => setAdding(true)}>＋ 添加要求</Button>
      </div>
      {rules.isPending ? (
        <Spinner />
      ) : (
        <div>
          {list.map((r) => (
            <div key={r.id} className={'ruleline' + (r.enabled ? '' : ' ruleline--disabled')}>
              <label aria-label="启用">
                <input type="checkbox" checked={r.enabled} onChange={() => toggle.mutate(r)} />
              </label>
              <div className="sentence">{r.sentence}</div>
              <Badge tone={r.hardness === 'soft' ? 'accent' : 'neutral'}>{r.hardness === 'soft' ? '尽量' : '硬性'}</Badge>
              <Button variant="ghost-danger" small onClick={() => { if (window.confirm(`删除这条要求?\n${r.sentence}`)) remove.mutate(r) }}>
                删除
              </Button>
            </div>
          ))}
          {list.length === 0 && <p className="muted" style={{ padding: '12px 0' }}>还没有特殊要求。没有也可以直接进入下一步。</p>}
        </div>
      )}
      <Note>“某人某天不方便”由成员在空闲时间中填写,无需重复添加为特殊要求。</Note>
      {adding && <RuleModal event={event} onClose={() => setAdding(false)} onSaved={() => { invalidate(event.id); setAdding(false) }} />}
    </>
  )
}

function RuleModal({ event, onClose, onSaved }: { event: RehearsalEvent; onClose: () => void; onSaved: () => void }) {
  const { toast } = useToast()
  const types = useRuleTypes()
  const members = useEventMembers(event.id)
  const songs = useSongs(event.id)
  const [type, setType] = useState<RuleType>('member_song_max_absent')
  const [memberId, setMemberId] = useState<number | ''>('')
  const [songId, setSongId] = useState<number | ''>('')
  const [n, setN] = useState(1)
  const [date, setDate] = useState(event.formal_start_date)
  const [startHour, setStartHour] = useState(event.day_start_hour + 8)
  const [endHour, setEndHour] = useState(event.day_start_hour + 11)
  const [duration, setDuration] = useState(2)
  const [err, setErr] = useState('')

  const info = types.data?.find((t) => t.type === type)
  const people = members.data ?? []
  const songList = songs.data?.songs ?? []
  const memberOptions = songId && (type === 'member_song_max_absent' || type === 'member_song_max_attendance') ? people.filter((p) => songList.find((s) => s.id === songId)?.members.some((m) => m.id === p.member_id)) : people

  const params = (): Record<string, unknown> => {
    switch (type) {
      case 'member_song_max_absent':
      case 'member_song_max_attendance':
        return { member_id: memberId, song_id: songId, n }
      case 'blocked_day':
        return { date }
      case 'blocked_slots':
        return { date, start_hour: startHour, end_hour: endHour }
      case 'max_sessions_per_date':
        return { date, n }
      case 'fixed_session':
        return { song_id: songId, date, start_hour: startHour, duration }
      case 'focus_member':
        return { member_id: memberId }
    }
  }
  const save = useAction(
    () => api<Rule>(`/api/events/${event.id}/rules`, { method: 'POST', json: { type, params: params() } }),
    (r) => {
      if (r.warning) toast(r.warning, 'error')
      onSaved()
    },
  )

  const hourOptions = Array.from({ length: event.day_end_hour - event.day_start_hour + 1 }, (_, i) => event.day_start_hour + i)
  const memberSelect = (
    <select value={memberId} onChange={(e) => setMemberId(e.target.value ? Number(e.target.value) : '')} aria-label="成员" className="input" style={{ width: 'auto', display: 'inline-block', padding: '7px 9px' }}>
      <option value="">选成员</option>
      {memberOptions.map((p) => (
        <option key={p.member_id} value={p.member_id}>
          {p.display_name}
        </option>
      ))}
    </select>
  )
  const songSelect = (
    <select value={songId} onChange={(e) => { setSongId(e.target.value ? Number(e.target.value) : ''); setMemberId('') }} aria-label="曲目" className="input" style={{ width: 'auto', display: 'inline-block', padding: '7px 9px' }}>
      <option value="">选曲目</option>
      {songList.map((s) => (
        <option key={s.id} value={s.id}>
          {s.code} · {s.name}
        </option>
      ))}
    </select>
  )
  const num = (min: number, max: number, value: number, set: (v: number) => void) => <input type="number" min={min} max={max} value={value} onChange={(e) => set(Number(e.target.value))} className="input" style={{ width: 70, display: 'inline-block', padding: '7px 9px' }} aria-label="数字" />
  const dateInput = <input type="date" value={date} min={event.formal_start_date} max={event.formal_end_date} onChange={(e) => setDate(e.target.value)} className="input" style={{ width: 'auto', display: 'inline-block', padding: '7px 9px' }} aria-label="日期" />
  const hourSelect = (value: number, set: (v: number) => void, opts: number[]) => (
    <select value={value} onChange={(e) => set(Number(e.target.value))} className="input" style={{ width: 'auto', display: 'inline-block', padding: '7px 9px' }} aria-label="时间">
      {opts.map((h) => (
        <option key={h} value={h}>
          {hourLabel(h)}
        </option>
      ))}
    </select>
  )

  let sentence: JSX.Element
  switch (type) {
    case 'member_song_max_absent':
      sentence = <>{songSelect} 里的 {memberSelect} 最多可缺席 {num(1, 20, n, setN)} 次</>
      break
    case 'member_song_max_attendance':
      sentence = <>{songSelect} 里的 {memberSelect} 最多参加 {num(0, 20, n, setN)} 场</>
      break
    case 'blocked_day':
      sentence = <>{dateInput} 整天不排练</>
      break
    case 'blocked_slots':
      sentence = <>{dateInput} 的 {hourSelect(startHour, setStartHour, hourOptions.slice(0, -1))} – {hourSelect(endHour, setEndHour, hourOptions.filter((h) => h > startHour))} 不排练</>
      break
    case 'max_sessions_per_date':
      sentence = <>{dateInput} 最多排 {num(0, 20, n, setN)} 场</>
      break
    case 'fixed_session':
      sentence = <>{songSelect} 有一场固定在 {dateInput} {hourSelect(startHour, setStartHour, hourOptions.slice(0, -1))} 开始,时长 {num(1, 6, duration, setDuration)} 小时</>
      break
    case 'focus_member':
      sentence = <>尽量把 {memberSelect} 的排练集中在少数几天</>
      break
  }

  return (
    <Modal open title="添加特殊排程要求" onClose={onClose} actions={<Button variant="primary" loading={save.isPending} onClick={() => { setErr(''); save.mutate(undefined, { onError: (e) => setErr(e instanceof Error ? e.message : String(e)) }) }}>保存要求</Button>}>
      <label className="field">
        <span>要求类型</span>
        <select value={type} onChange={(e) => setType(e.target.value as RuleType)}>
          {(types.data ?? []).map((t) => (
            <option key={t.type} value={t.type}>
              {t.template.replace(/\{member\}/g, '某人').replace(/\{song\}/g, '某曲目').replace(/\{n\}/g, 'N').replace(/\{date\}/g, '某天').replace(/\{start\}–\{end\}/g, '某时段').replace(/\{start\}/g, '某时')}
            </option>
          ))}
        </select>
      </label>
      <div className="inline" style={{ marginTop: 18, lineHeight: 2.4 }}>{sentence}</div>
      <Note>{info?.hardness === 'soft' ? '尽量:优先全到或集中,排不开时才取舍。' : '硬性:排程必须满足。'} {info?.description}</Note>
      {err && <p className="error-text" role="alert">{err}</p>}
    </Modal>
  )
}
