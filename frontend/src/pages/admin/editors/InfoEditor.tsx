import dayjs from 'dayjs'
import { useMemo, useState, type FormEvent } from 'react'

import { api } from '../../../api/client'
import { useAction, useInvalidateEvent, useObjectives } from '../../../api/hooks'
import { DIFFICULTIES, type EventSettings, type RehearsalEvent } from '../../../api/types'
import { Button, Field, Note } from '../../../ui'
import { useToast } from '../../../ui/Toast'
import { fmtMd, hourLabel, parsePlan, planText } from '../../../utils'

const DEFAULT_SETTINGS: EventSettings = {
  soft_daily_limit: 8,
  hard_daily_limit: 8,
  merge_visit_gap: 1,
  free_gap: 1,
  eval_durations: [3, 2],
  eval_min_contiguous: 2,
  same_song_different_days: true,
  difficulty_templates: { 简单: [2, 2], 一般: [3, 2, 2], 困难: [3, 3, 3] },
  stage_time_limit: 90,
  objectives: ['absent', 'eval_attendance', 'spacing', 'focus_days', 'trips', 'gaps', 'overtime', 'soft_avoid'],
}

interface Props {
  event?: RehearsalEvent
  submitLabel?: string
  onSaved: (ev: RehearsalEvent) => void
}

export function InfoEditor({ event, submitLabel = '保存', onSaved }: Props) {
  const invalidate = useInvalidateEvent()
  const { toast } = useToast()
  const s = event?.settings ?? DEFAULT_SETTINGS
  const [name, setName] = useState(event?.name ?? '')
  const [perf, setPerf] = useState(event?.performance_date ?? dayjs().add(30, 'day').format('YYYY-MM-DD'))
  const [start, setStart] = useState(event?.formal_start_date ?? dayjs().add(1, 'day').format('YYYY-MM-DD'))
  const [deadline, setDeadline] = useState(event?.availability_deadline ?? '')
  const [dayStart, setDayStart] = useState(event?.day_start_hour ?? 10)
  const [dayEnd, setDayEnd] = useState(event?.day_end_hour ?? 23)
  const [soft, setSoft] = useState(s.soft_daily_limit)
  const [hard, setHard] = useState(s.hard_daily_limit)
  const [evalDur, setEvalDur] = useState(s.eval_durations.join(','))
  const [sameDay, setSameDay] = useState(s.same_song_different_days)
  const [tpl, setTpl] = useState<Record<string, string>>(Object.fromEntries(DIFFICULTIES.map((d) => [d, planText(s.difficulty_templates[d])])))
  const [objectives, setObjectives] = useState<string[]>(s.objectives ?? DEFAULT_SETTINGS.objectives)
  const objectiveDefs = useObjectives()
  const [err, setErr] = useState('')

  const derived = useMemo(() => {
    const p = dayjs(perf)
    const st = dayjs(start)
    if (!p.isValid() || !st.isValid()) return { text: '请选择演出日期和排练开始日期', bad: true }
    const end = p.subtract(2, 'day')
    const days = end.diff(st, 'day') + 1
    if (days < 1) return { text: '排练开始日期不能晚于演出前两天。', bad: true }
    return {
      text: `正规排练 ${fmtMd(start)} – ${fmtMd(end.format('YYYY-MM-DD'))}(${days} 天)· 全员评估 ${fmtMd(p.subtract(1, 'day').format('YYYY-MM-DD'))} · 每天 ${hourLabel(dayStart)}–${hourLabel(dayEnd)}`,
      bad: false,
    }
  }, [perf, start, dayStart, dayEnd])

  const save = useAction(
    async () => {
      const templates = {} as Record<string, number[]>
      for (const d of DIFFICULTIES) {
        const plan = parsePlan(tpl[d])
        if (!plan) throw new Error(`难度「${d}」的排练方案无法识别`)
        templates[d] = plan
      }
      const evalPlan = parsePlan(evalDur)
      if (!evalPlan) throw new Error('评估场时长无法识别')
      const body = {
        name,
        performance_date: perf,
        formal_start_date: start,
        availability_deadline: deadline || null,
        day_start_hour: dayStart,
        day_end_hour: dayEnd,
        settings: { ...s, soft_daily_limit: soft, hard_daily_limit: hard, eval_durations: evalPlan, same_song_different_days: sameDay, difficulty_templates: templates, objectives },
      }
      if (event) return api<RehearsalEvent>(`/api/events/${event.id}`, { method: 'PATCH', json: body })
      return api<RehearsalEvent>('/api/events', { method: 'POST', json: body })
    },
    (ev) => {
      invalidate(ev.id)
      toast(event ? '已保存' : '演出已创建')
      onSaved(ev)
    },
  )

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return setErr('请填写演出名称')
    if (derived.bad) return setErr(derived.text)
    setErr('')
    save.mutate(undefined)
  }

  const hours = Array.from({ length: 25 }, (_, i) => i)
  return (
    <form onSubmit={submit}>
      <div className="fields">
        <Field label="演出名称" full>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="例如 2026 秋季路演" maxLength={120} />
        </Field>
        <Field label="演出日期">
          <input type="date" value={perf} onChange={(e) => setPerf(e.target.value)} />
        </Field>
        <Field label="排练开始日期">
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        </Field>
      </div>
      <Note tone={derived.bad ? 'error' : 'info'}>{derived.text}</Note>
      <details>
        <summary>更多设置 · 默认值可以直接用</summary>
        <div className="fields">
          <Field label="每天最早">
            <select value={dayStart} onChange={(e) => setDayStart(Number(e.target.value))}>
              {hours.slice(0, 24).map((h) => (
                <option key={h} value={h}>
                  {hourLabel(h)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="每天最晚">
            <select value={dayEnd} onChange={(e) => setDayEnd(Number(e.target.value))}>
              {hours.slice(1).map((h) => (
                <option key={h} value={h}>
                  {hourLabel(h)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="填报截止日" hint="到期只提醒,不锁定">
            <input type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} />
          </Field>
          <Field label="评估场时长(小时)" hint="按总到场人时最多选择">
            <input value={evalDur} onChange={(e) => setEvalDur(e.target.value)} placeholder="3,2" />
          </Field>
          <Field label="单日软上限(小时)">
            <input type="number" min={1} max={24} value={soft} onChange={(e) => setSoft(Number(e.target.value))} />
          </Field>
          <Field label="单日硬上限(小时)">
            <input type="number" min={1} max={24} value={hard} onChange={(e) => setHard(Number(e.target.value))} />
          </Field>
          {DIFFICULTIES.map((d) => (
            <Field key={d} label={`难度「${d}」的排练方案`} hint="如 1 场 3h + 2 场 2h">
              <input value={tpl[d]} onChange={(e) => setTpl({ ...tpl, [d]: e.target.value })} />
            </Field>
          ))}
          <label className="check" style={{ alignSelf: 'end' }}>
            <input type="checkbox" checked={sameDay} onChange={(e) => setSameDay(e.target.checked)} />
            同一曲目的场次必须在不同日期
          </label>
        </div>
        <div className="objectives">
          <div className="kicker">优化优先级 · 从上到下依次满足,勾掉的不参与</div>
          {(objectiveDefs.data ?? []).length === 0 ? (
            <p className="muted">加载中…</p>
          ) : (
            [...objectives.map((k) => ({ key: k, on: true })), ...(objectiveDefs.data ?? []).filter((o) => !objectives.includes(o.key)).map((o) => ({ key: o.key, on: false }))].map((item, i) => {
              const def = (objectiveDefs.data ?? []).find((o) => o.key === item.key)
              const idx = objectives.indexOf(item.key)
              const move = (delta: number) => {
                const next = [...objectives]
                const j = idx + delta
                if (idx < 0 || j < 0 || j >= next.length) return
                ;[next[idx], next[j]] = [next[j], next[idx]]
                setObjectives(next)
              }
              return (
                <div key={item.key} className={'objective' + (item.on ? '' : ' is-off')}>
                  <label className="check">
                    <input type="checkbox" checked={item.on} onChange={(e) => setObjectives(e.target.checked ? [...objectives, item.key] : objectives.filter((k) => k !== item.key))} />
                    {item.on ? `${i + 1}. ` : ''}
                    {def?.label ?? item.key}
                  </label>
                  {item.on && (
                    <span className="objective__btns">
                      <button type="button" className="btn btn--sm btn--ghost" disabled={idx <= 0} onClick={() => move(-1)} aria-label="上移">
                        ↑
                      </button>
                      <button type="button" className="btn btn--sm btn--ghost" disabled={idx >= objectives.length - 1} onClick={() => move(1)} aria-label="下移">
                        ↓
                      </button>
                    </span>
                  )}
                </div>
              )
            })
          )}
        </div>
      </details>
      {err && <p className="error-text" role="alert">{err}</p>}
      <div className="actions">
        <Button type="submit" variant="primary" loading={save.isPending}>
          {submitLabel}
        </Button>
      </div>
    </form>
  )
}
