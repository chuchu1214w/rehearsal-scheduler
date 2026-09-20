import { NavLink } from 'react-router-dom'

import { useUnreadCount } from '../api/hooks'
import { IconBell } from './icons'

/** 顶栏 / 侧栏的通知入口:未读数角标,每分钟刷新 */
export function Bell({ active, asNav = false }: { active: boolean; asNav?: boolean }) {
  const unread = useUnreadCount()
  const n = unread.data?.count ?? 0
  const cls = asNav ? 'navbtn' + (active ? ' is-active' : '') : 'bell' + (active ? ' is-active' : '')
  return (
    <NavLink to="/notifications" className={cls} aria-label={n ? `通知,${n} 条未读` : '通知'}>
      <span className="bell__icon">
        <IconBell />
        {n > 0 && <span className="bell__badge">{n > 99 ? '99+' : n}</span>}
      </span>
      {asNav && '通知'}
    </NavLink>
  )
}
