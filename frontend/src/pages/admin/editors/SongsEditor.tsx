import { useState } from 'react'

import { api } from '../../../api/client'
import { useAction, useEventMembers, useInvalidateEvent, useSongs } from '../../../api/hooks'
import { DIFFICULTIES, type Difficulty, type EventMember, type RehearsalEvent, type Song } from '../../../api/types'
import { Badge, Button, Field, KV, Note, Spinner } from '../../../ui'
import { Modal } from '../../../ui/Modal'
import { parsePlan, planText, templatePlan } from '../../../utils'

interface Props {
  event: RehearsalEvent
}

function nextCode(songs: Song[]): string {
  const used = new Set(songs.map((s) => s.code.toLowerCase()))
  for (let i = 0; i < 26; i++) {
    const c = String.fromCharCode(97 + i)
    if (!used.has(c)) return c
  }
  return `s${songs.length + 1}`
}

export function SongsEditor({ event }: Props) {
  const invalidate = useInvalidateEvent()
  const songs = useSongs(event.id)
  const members = useEventMembers(event.id)
  const [modal, setModal] = useState<'add' | 'paste' | Song | null>(null)
  const remove = useAction((s: Song) => api(`/api/songs/${s.id}`, { method: 'DELETE' }), () => invalidate(event.id))
  const list = songs.data?.songs ?? []
  const people = members.data ?? []
  return (
    <>
      <div className="section">
        <h3>曲目与排练方案</h3>
        <div className="inline">
          <Button onClick={() => setModal('paste')} disabled={people.length === 0}>
            粘贴录入
          </Button>
          <Button onClick={() => setModal('add')} disabled={people.length === 0}>
            ＋ 添加曲目
          </Button>
        </div>
      </div>
      {people.length === 0 && <Note tone="warning">还没有人员,先回第 ② 步添加人员,再录曲目。</Note>}
      {songs.isPending ? (
        <Spinner />
      ) : (
        <div className="rows">
          {list.map((s) => (
            <div key={s.id} className="row">
              <KV label="代号 / 曲目" title>
                <strong>
                  {s.code} · {s.name}
                </strong>
              </KV>
              <KV label="难度">
                <Badge tone={s.difficulty === '困难' ? 'orange' : s.difficulty === '一般' ? 'accent' : 'neutral'}>{s.difficulty}</Badge>
              </KV>
              <KV label="参演人员">{s.members.map((m) => m.display_name).join('、')}</KV>
              <KV label="排练方案">
                {planText(s.durations)} {s.session_plan && <Badge tone="neutral">自定义</Badge>}
              </KV>
              <KV label="场次">{s.session_count}</KV>
              <KV label="操作">
                <span className="inline">
                  <Button variant="ghost" small onClick={() => setModal(s)}>
                    编辑
                  </Button>
                  <Button variant="ghost-danger" small onClick={() => { if (window.confirm(`删除曲目「${s.name}」?`)) remove.mutate(s) }}>
                    删除
                  </Button>
                </span>
              </KV>
            </div>
          ))}
          {list.length === 0 && <p className="muted" style={{ padding: '12px 0' }}>还没有曲目。</p>}
        </div>
      )}
      {songs.data && songs.data.songs.length > 0 && (
        <Note>
          {songs.data.songs.length} 首 · {songs.data.total_sessions} 场正规排练 + 1 场全员评估
        </Note>
      )}
      {songs.data?.warnings.map((w) => (
        <Note key={w} tone="warning">
          {w}
        </Note>
      ))}
      {(modal === 'add' || (modal && typeof modal === 'object')) && (
        <SongModal event={event} people={people} songs={list} initial={typeof modal === 'object' ? modal : undefined} onClose={() => setModal(null)} onSaved={() => { invalidate(event.id); setModal(null) }} />
      )}
      {modal === 'paste' && <PasteModal event={event} people={people} songs={list} onClose={() => setModal(null)} onSaved={() => { invalidate(event.id); setModal(null) }} />}
    </>
  )
}

function SongModal({ event, people, songs, initial, onClose, onSaved }: { event: RehearsalEvent; people: EventMember[]; songs: Song[]; initial?: Song; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(initial?.name ?? '')
  const [code, setCode] = useState(initial?.code ?? nextCode(songs))
  const [difficulty, setDifficulty] = useState<Difficulty>(initial?.difficulty ?? '一般')
  const [plan, setPlan] = useState(planText(initial?.durations ?? templatePlan(event.settings, initial?.difficulty ?? '一般')))
  const [selected, setSelected] = useState<Set<number>>(new Set(initial?.members.map((m) => m.id) ?? []))
  const [err, setErr] = useState('')

  const parsed = parsePlan(plan)
  const template = templatePlan(event.settings, difficulty)
  const isTemplate = parsed !== null && parsed.join(',') === template.join(',')

  const save = useAction(async () => {
    if (!name.trim()) throw new Error('请填写曲目名称')
    if (selected.size === 0) throw new Error('至少选择 1 位参演人员')
    if (!parsed) throw new Error('排练方案无法识别,例如「1 场 3h + 2 场 2h」')
    const body = { name: name.trim(), code: code.trim() || null, difficulty, member_ids: [...selected], session_plan: isTemplate ? null : parsed }
    if (initial) return api<Song>(`/api/songs/${initial.id}`, { method: 'PATCH', json: { ...body, code: body.code ?? initial.code, clear_session_plan: isTemplate } })
    return api<Song>(`/api/events/${event.id}/songs`, { method: 'POST', json: body })
  }, onSaved)

  const toggle = (id: number) => {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelected(next)
  }
  return (
    <Modal open title={initial ? '编辑曲目' : '添加曲目'} onClose={onClose} actions={<Button variant="primary" loading={save.isPending} onClick={() => { setErr(''); save.mutate(undefined, { onError: (e) => setErr(e instanceof Error ? e.message : String(e)) }) }}>{initial ? '保存' : '添加曲目'}</Button>}>
      <div className="fields">
        <Field label="曲目名称" full>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="例如 aespa-lemonadeB" maxLength={120} autoFocus />
        </Field>
        <Field label="代号">
          <input value={code} onChange={(e) => setCode(e.target.value)} maxLength={16} />
        </Field>
        <Field label="难度">
          <select
            value={difficulty}
            onChange={(e) => {
              const d = e.target.value as Difficulty
              setDifficulty(d)
              setPlan(planText(templatePlan(event.settings, d)))
            }}
          >
            {DIFFICULTIES.map((d) => (
              <option key={d} value={d}>
                {d}({planText(templatePlan(event.settings, d))})
              </option>
            ))}
          </select>
        </Field>
        <Field label="排练方案 · 可直接修改" full hint={parsed ? `共 ${parsed.length} 场${isTemplate ? '(难度模板)' : '(自定义)'}` : '无法识别'}>
          <input value={plan} onChange={(e) => setPlan(e.target.value)} placeholder="1 场 3h + 2 场 2h" />
        </Field>
      </div>
      <div className="field" style={{ marginTop: 15 }}>
        <span>参演人员</span>
        <div className="checks">
          {people.map((m) => (
            <label key={m.member_id} className="check">
              <input type="checkbox" checked={selected.has(m.member_id)} onChange={() => toggle(m.member_id)} />
              {m.display_name}
            </label>
          ))}
        </div>
      </div>
      {err && <p className="error-text" role="alert">{err}</p>}
    </Modal>
  )
}

interface ParsedRow {
  name: string
  difficulty: string
  names: string[]
  unknown: string[]
  ok: boolean
}

function PasteModal({ event, people, songs, onClose, onSaved }: { event: RehearsalEvent; people: EventMember[]; songs: Song[]; onClose: () => void; onSaved: () => void }) {
  const [text, setText] = useState('')
  const [rows, setRows] = useState<ParsedRow[] | null>(null)
  const byName = new Map(people.map((m) => [m.display_name, m.member_id]))
  const preview = () => {
    const parsed = text
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean)
      .map<ParsedRow>((line) => {
        const parts = line.split(/[/／|]/).map((s) => s.trim())
        const names = (parts[2] ?? '').split(/[\s,，、]+/).filter(Boolean)
        const unknown = names.filter((n) => !byName.has(n))
        const difficulty = parts[1] ?? ''
        return { name: parts[0] ?? '', difficulty, names, unknown, ok: !!parts[0] && DIFFICULTIES.includes(difficulty as Difficulty) && names.length > 0 && unknown.length === 0 }
      })
    setRows(parsed)
  }
  const create = useAction(async () => {
    const used = new Set(songs.map((s) => s.code.toLowerCase()))
    for (const r of rows ?? []) {
      if (!r.ok) continue
      let code = ''
      for (let i = 0; i < 26; i++) {
        const c = String.fromCharCode(97 + i)
        if (!used.has(c)) {
          code = c
          used.add(c)
          break
        }
      }
      await api(`/api/events/${event.id}/songs`, { method: 'POST', json: { name: r.name, code: code || null, difficulty: r.difficulty, member_ids: r.names.map((n) => byName.get(n)) } })
    }
  }, onSaved)
  const okCount = rows?.filter((r) => r.ok).length ?? 0
  return (
    <Modal
      open
      title="粘贴录入曲目"
      onClose={onClose}
      actions={
        rows ? (
          <>
            <Button onClick={() => setRows(null)}>返回修改</Button>
            <Button variant="primary" disabled={okCount === 0} loading={create.isPending} onClick={() => create.mutate(undefined)}>
              录入 {okCount} 首
            </Button>
          </>
        ) : (
          <Button variant="primary" disabled={!text.trim()} onClick={preview}>
            预览识别结果
          </Button>
        )
      }
    >
      {!rows ? (
        <Field label="一行一首:曲名 / 难度 / 人员1 人员2 …">
          <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder={'LOVE DIVE / 一般 / 菁 若 思\n新舞台 / 简单 / 衿 幸'} rows={6} />
        </Field>
      ) : (
        <div className="rows">
          {rows.map((r, i) => (
            <div key={i} className="row">
              <KV label="曲目" title>
                {r.name || <span className="error-text">缺少曲名</span>}
              </KV>
              <KV label="识别结果">
                {r.ok ? (
                  <Badge tone="green">可创建 · {r.difficulty} · {r.names.join('、')}</Badge>
                ) : (
                  <span className="error-text">
                    {!DIFFICULTIES.includes(r.difficulty as Difficulty) && `难度「${r.difficulty}」无法识别;`}
                    {r.names.length === 0 && '没有人员;'}
                    {r.unknown.length > 0 && `未识别的人员:${r.unknown.join('、')}`}
                  </span>
                )}
              </KV>
            </div>
          ))}
        </div>
      )}
    </Modal>
  )
}
