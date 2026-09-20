import { useState, type KeyboardEvent } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../../../api/client'
import { useAction, useEventMembers, useEvents, useInvalidateEvent, useRoster } from '../../../api/hooks'
import type { Credentials, EventMember, RehearsalEvent } from '../../../api/types'
import { Badge, Button, Field, KV, Note, Spinner } from '../../../ui'
import { Modal } from '../../../ui/Modal'
import { useToast } from '../../../ui/Toast'
import { copyText, fmtDateTime, splitNames } from '../../../utils'

interface Props {
  event: RehearsalEvent
  wizard?: boolean
}

type ModalState =
  | { type: 'reuse' }
  | { type: 'note'; member: EventMember }
  | { type: 'open'; member: EventMember }
  | { type: 'manage'; member: EventMember }
  | { type: 'batch' }
  | { type: 'credentials'; list: Credentials[]; title: string }
  | null

export function PeopleEditor({ event, wizard = false }: Props) {
  const invalidate = useInvalidateEvent()
  const { toast } = useToast()
  const members = useEventMembers(event.id)
  const [input, setInput] = useState('')
  const [modal, setModal] = useState<ModalState>(null)

  const add = useAction(
    (names: string[]) => api<EventMember[]>(`/api/events/${event.id}/members`, { method: 'POST', json: { names } }),
    () => {
      invalidate(event.id)
      setInput('')
    },
  )
  const remove = useAction(
    (m: EventMember) => api(`/api/events/${event.id}/members/${m.member_id}`, { method: 'DELETE' }),
    () => invalidate(event.id),
  )

  const submitNames = () => {
    const names = splitNames(input)
    if (names.length) add.mutate(names)
  }
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      submitNames()
    }
  }

  const list = members.data ?? []
  const noAccount = list.filter((m) => !m.account && m.active)
  return (
    <>
      <div className="section">
        <h3>本场人员 · {list.length} 人</h3>
        <Button onClick={() => setModal({ type: 'reuse' })}>带入上次演出的人员</Button>
      </div>
      <Field label="添加人员">
        <div className="inline" style={{ flexWrap: 'nowrap' }}>
          <input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={onKey} placeholder="输入昵称,回车添加;支持粘贴逗号或换行分隔的多个名字" />
          <Button onClick={submitNames} loading={add.isPending} disabled={!input.trim()}>
            添加
          </Button>
        </div>
      </Field>
      {members.isPending ? (
        <Spinner />
      ) : (
        <div className="chips">
          {list.map((m) => (
            <span key={m.member_id} className="chip">
              <button type="button" className="chip__name" onClick={() => setModal({ type: 'note', member: m })} title="添加备注">
                {m.display_name}
                {m.note && <span className="muted"> · {m.note}</span>}
              </button>
              <button type="button" aria-label={`移除 ${m.display_name}`} onClick={() => remove.mutate(m)}>
                ×
              </button>
            </span>
          ))}
          {list.length === 0 && <span className="muted">还没有人员,在上面输入昵称添加。</span>}
        </div>
      )}
      {wizard ? (
        <Note>先录好曲目和要求,再到第 ⑤ 步给大家开通账号。点名字可添加管理员备注。</Note>
      ) : (
        <div style={{ marginTop: 22 }}>
          <div className="rows">
            {list.map((m) => (
              <div key={m.member_id} className="row">
                <KV label="昵称" title>
                  {m.display_name}
                  {!m.active && <Badge tone="neutral">已停用</Badge>}
                </KV>
                <KV label="账号">{m.account ? <>{m.account.username} {m.account.is_active ? <Badge tone="green">已开通</Badge> : <Badge tone="neutral">已停用</Badge>}{m.account.must_change_password && <span className="muted"> · 初始密码未改</span>}</> : <Badge tone="neutral">未开通</Badge>}</KV>
                <KV label="填报">{m.availability_submitted_at ? `已提交 ${fmtDateTime(m.availability_submitted_at)}${m.availability_filled_by === 'admin' ? '(管理员代填)' : ''}` : m.availability_filled_days > 0 ? `已填 ${m.availability_filled_days} 天,未提交` : '未提交'}</KV>
                <KV label="操作">
                  <span className="inline">
                    {m.account ? (
                      <Button variant="ghost" small onClick={() => setModal({ type: 'manage', member: m })}>
                        账号管理
                      </Button>
                    ) : (
                      <Button variant="ghost" small onClick={() => setModal({ type: 'open', member: m })} disabled={!m.active}>
                        开通账号
                      </Button>
                    )}
                    <Link to={`/events/${event.id}/availability/${m.member_id}`} className="btn btn--ghost btn--sm">
                      {m.availability_submitted_at ? '查看 / 改填' : '代填'}
                    </Link>
                  </span>
                </KV>
              </div>
            ))}
          </div>
          {noAccount.length > 0 && (
            <div className="actions">
              <Button onClick={() => setModal({ type: 'batch' })}>开通全部未开通的人员({noAccount.length})</Button>
            </div>
          )}
        </div>
      )}

      <ReuseModal open={modal?.type === 'reuse'} event={event} existing={list} onClose={() => setModal(null)} onPick={(names) => add.mutate(names)} />
      {modal?.type === 'note' && <NoteModal member={modal.member} onClose={() => setModal(null)} onSaved={() => invalidate(event.id)} />}
      {modal?.type === 'open' && (
        <OpenAccountModal member={modal.member} onClose={() => setModal(null)} onDone={(c) => { invalidate(event.id); setModal({ type: 'credentials', list: [c], title: `已为 ${c.display_name} 开通账号` }) }} />
      )}
      {modal?.type === 'manage' && <ManageAccountModal member={modal.member} onClose={() => setModal(null)} onChanged={() => invalidate(event.id)} onReset={(c) => { invalidate(event.id); setModal({ type: 'credentials', list: [c], title: `已重置 ${c.display_name} 的密码` }) }} />}
      {modal?.type === 'batch' && (
        <BatchModal event={event} count={noAccount.length} onClose={() => setModal(null)} onDone={(list) => { invalidate(event.id); setModal({ type: 'credentials', list, title: `已开通 ${list.length} 个账号` }) }} />
      )}
      {modal?.type === 'credentials' && <CredentialsModal title={modal.title} list={modal.list} onClose={() => setModal(null)} onCopied={() => toast('已复制,可以发给成员了')} />}
    </>
  )
}

function ReuseModal({ open, event, existing, onClose, onPick }: { open: boolean; event: RehearsalEvent; existing: EventMember[]; onClose: () => void; onPick: (names: string[]) => void }) {
  const events = useEvents()
  const roster = useRoster(open)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [seeded, setSeeded] = useState(false)
  const previous = (events.data ?? []).filter((e) => e.id !== event.id).sort((a, b) => b.performance_date.localeCompare(a.performance_date))[0]
  const have = new Set(existing.map((m) => m.display_name))
  const candidates = (roster.data ?? []).filter((m) => m.active && !have.has(m.display_name)).map((m) => m.display_name)
  if (open && !seeded && roster.data) {
    setChecked(new Set(candidates))
    setSeeded(true)
  }
  const close = () => {
    setSeeded(false)
    onClose()
  }
  return (
    <Modal
      open={open}
      title="带入以前的人员"
      onClose={close}
      actions={
        <Button variant="primary" disabled={checked.size === 0} onClick={() => { onPick([...checked]); close() }}>
          带入所选 {checked.size} 人
        </Button>
      }
    >
      <p>{previous ? `上次:${previous.name}。` : ''}这里是以前所有演出出现过、但还不在本场的人员。</p>
      {roster.isPending ? (
        <Spinner />
      ) : candidates.length === 0 ? (
        <p>没有可带入的人员。</p>
      ) : (
        <div className="checks">
          {candidates.map((n) => (
            <label key={n} className="check">
              <input
                type="checkbox"
                checked={checked.has(n)}
                onChange={(e) => {
                  const next = new Set(checked)
                  if (e.target.checked) next.add(n)
                  else next.delete(n)
                  setChecked(next)
                }}
              />
              {n}
            </label>
          ))}
        </div>
      )}
    </Modal>
  )
}

function NoteModal({ member, onClose, onSaved }: { member: EventMember; onClose: () => void; onSaved: () => void }) {
  const [note, setNote] = useState(member.note)
  const save = useAction(() => api(`/api/members/${member.member_id}`, { method: 'PATCH', json: { note } }), () => { onSaved(); onClose() })
  return (
    <Modal open title={`${member.display_name} · 管理员备注`} onClose={onClose} actions={<Button variant="primary" loading={save.isPending} onClick={() => save.mutate(undefined)}>保存备注</Button>}>
      <Field label="仅管理员可见">
        <textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="例如:住得远、周三有课" maxLength={500} />
      </Field>
    </Modal>
  )
}

function OpenAccountModal({ member, onClose, onDone }: { member: EventMember; onClose: () => void; onDone: (c: Credentials) => void }) {
  const [username, setUsername] = useState(member.display_name)
  const [password, setPassword] = useState('')
  const open = useAction(() => api<Credentials>(`/api/members/${member.member_id}/account`, { method: 'POST', json: { username: username.trim() || null, password } }), onDone)
  return (
    <Modal open title={`为 ${member.display_name} 开通账号`} onClose={onClose} actions={<Button variant="primary" loading={open.isPending} disabled={password.length < 8} onClick={() => open.mutate(undefined)}>开通并显示账号信息</Button>}>
      <div className="fields">
        <Field label="用户名" hint="默认用昵称">
          <input value={username} onChange={(e) => setUsername(e.target.value)} />
        </Field>
        <Field label="初始密码" hint="至少 8 位">
          <input value={password} onChange={(e) => setPassword(e.target.value)} placeholder="由你设定,成员登录后可改" autoComplete="off" />
        </Field>
      </div>
      <p>开通后会显示一段可复制的文字,把它发给成员即可。</p>
    </Modal>
  )
}

function ManageAccountModal({ member, onClose, onChanged, onReset }: { member: EventMember; onClose: () => void; onChanged: () => void; onReset: (c: Credentials) => void }) {
  const [password, setPassword] = useState('')
  const account = member.account!
  const reset = useAction(() => api<Credentials>(`/api/members/${member.member_id}/account/reset`, { method: 'POST', json: { password } }), onReset)
  const toggle = useAction(() => api(`/api/members/${member.member_id}/account`, { method: 'PATCH', json: { is_active: !account.is_active } }), () => { onChanged(); onClose() })
  return (
    <Modal open title={`${member.display_name} · 账号`} onClose={onClose}>
      <p>用户名 <strong>{account.username}</strong> · {account.is_active ? '正常' : '已停用'} · 上次登录 {fmtDateTime(account.last_login_at)}</p>
      <div className="fields" style={{ marginTop: 14 }}>
        <Field label="重置密码" hint="输入新密码,至少 8 位">
          <div className="inline" style={{ flexWrap: 'nowrap' }}>
            <input value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="off" />
            <Button loading={reset.isPending} disabled={password.length < 8} onClick={() => reset.mutate(undefined)}>
              重置
            </Button>
          </div>
        </Field>
      </div>
      <Note>重置后旧密码立即失效,成员在其他设备上的登录会退出。</Note>
      <div className="actions">
        <Button variant={account.is_active ? 'danger' : 'default'} loading={toggle.isPending} onClick={() => toggle.mutate(undefined)}>
          {account.is_active ? '停用账号' : '启用账号'}
        </Button>
      </div>
    </Modal>
  )
}

function BatchModal({ event, count, onClose, onDone }: { event: RehearsalEvent; count: number; onClose: () => void; onDone: (list: Credentials[]) => void }) {
  const [password, setPassword] = useState('')
  const run = useAction(() => api<Credentials[]>(`/api/events/${event.id}/accounts`, { method: 'POST', json: { password } }), onDone)
  return (
    <Modal open title={`开通 ${count} 个账号`} onClose={onClose} actions={<Button variant="primary" loading={run.isPending} disabled={password.length < 8} onClick={() => run.mutate(undefined)}>一次开通</Button>}>
      <Field label="统一初始密码" hint="至少 8 位">
        <input value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="off" />
      </Field>
      <p>用户名默认用昵称;开通后会生成每人一行的账号清单,可整体复制。建议提醒成员登录后各自改密码。</p>
    </Modal>
  )
}

function CredentialsModal({ title, list, onClose, onCopied }: { title: string; list: Credentials[]; onClose: () => void; onCopied: () => void }) {
  const text = list.length === 1 ? list[0].copy_text : list.map((c) => `${c.display_name}:用户名 ${c.username} 密码 ${c.password}`).join('\n') + `\n\n${list[0]?.copy_text.split('\n')[0] ?? ''}\n登录后请在「账号」页修改密码。`
  return (
    <Modal open title={title} onClose={onClose} actions={<Button variant="primary" onClick={() => void copyText(text).then((ok) => ok && onCopied())}>复制全部</Button>}>
      <p>关闭后这里不会再显示密码;需要时可在「账号管理」里重置。</p>
      <pre className="code">{text}</pre>
    </Modal>
  )
}
