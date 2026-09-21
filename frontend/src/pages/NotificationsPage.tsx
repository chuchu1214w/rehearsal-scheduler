import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import { keys, useAction, useNotifications } from '../api/hooks'
import type { Notification } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { Back, Badge, Button, Empty, Heading, Panel, Spinner } from '../ui'
import { fmtDateTime } from '../utils'

const TYPE_TEXT: Record<string, { label: string; tone: 'accent' | 'green' | 'orange' | 'red' | 'neutral' }> = {
  joined: { label: '待办', tone: 'accent' },
  remind: { label: '催办', tone: 'orange' },
  deadline: { label: '截止', tone: 'orange' },
  published: { label: '发布', tone: 'green' },
  unpublished: { label: '撤回', tone: 'neutral' },
  tomorrow: { label: '明天', tone: 'accent' },
  conflict: { label: '受影响', tone: 'red' },
  all_submitted: { label: '可排程', tone: 'green' },
  location: { label: '地点', tone: 'accent' },
}

export function NotificationsPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const list = useNotifications()
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: keys.notifications })
    void qc.invalidateQueries({ queryKey: keys.unread })
  }
  const readAll = useAction(() => api<{ count: number }>('/api/notifications/read', { method: 'POST', json: {} }), refresh)
  const readOne = useAction((id: number) => api<{ count: number }>('/api/notifications/read', { method: 'POST', json: { ids: [id] } }), refresh)
  const open = (n: Notification) => {
    if (!n.read_at) readOne.mutate(n.id)
    if (n.link) navigate(n.link)
  }
  const items = list.data ?? []
  const unread = items.filter((n) => !n.read_at).length
  return (
    <>
      <Back to="/" label={user?.role === 'admin' ? '演出列表' : '返回首页'} />
      <Heading
        title="通知"
        subtitle={unread ? `${unread} 条未读` : '没有未读通知'}
        action={
          unread > 0 ? (
            <Button small loading={readAll.isPending} onClick={() => readAll.mutate(undefined)}>
              全部已读
            </Button>
          ) : undefined
        }
      />
      {list.isPending ? (
        <Spinner />
      ) : items.length === 0 ? (
        <Empty title="还没有通知" text="排练表发布、填报提醒、明天的排练等都会出现在这里。" />
      ) : (
        <Panel>
          {items.map((n) => {
            const t = TYPE_TEXT[n.type] ?? { label: n.type, tone: 'neutral' as const }
            return (
              <button key={n.id} type="button" className={'notif' + (n.read_at ? '' : ' is-unread')} onClick={() => open(n)}>
                <span className="notif__dot" aria-hidden />
                <span className="notif__main">
                  <span className="notif__title">
                    <Badge tone={t.tone}>{t.label}</Badge> {n.title}
                  </span>
                  {n.body && <span className="notif__body">{n.body}</span>}
                  <span className="notif__time">{fmtDateTime(n.created_at)}</span>
                </span>
              </button>
            )
          })}
        </Panel>
      )}
    </>
  )
}
