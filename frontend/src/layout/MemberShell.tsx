import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { useEvents } from '../api/hooks'
import { useAuth } from '../auth/AuthContext'
import { Wordmark } from '../ui'
import { Bell } from './Bell'
import { IconCalendar, IconUser } from './icons'
import { pickCurrentEvent } from './currentEvent'

export function MemberShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const events = useEvents()
  const current = pickCurrentEvent(events.data ?? [])
  const isSchedule = location.pathname.startsWith('/schedule')
  const isAccount = location.pathname === '/account'
  const isNotif = location.pathname === '/notifications'

  const nav = (
    <>
      <NavLink to="/schedule" className={'navbtn' + (isSchedule ? ' is-active' : '')}>
        <IconCalendar />
        排练表
      </NavLink>
      <NavLink to="/account" className={'navbtn' + (isAccount ? ' is-active' : '')}>
        <IconUser />
        账号
      </NavLink>
    </>
  )

  return (
    <div className="shell shell-member">
      <aside className="sidebar">
        <div className="brand">
          <Wordmark to="/" />
          <small>排练排程 · 成员</small>
        </div>
        <NavLink to="/" className={'navbtn' + (location.pathname === '/' ? ' is-active' : '')} end>
          我的首页
        </NavLink>
        {nav}
        <Bell active={isNotif} asNav />
        <div className="sidebar__bottom">
          {user?.member_name ?? user?.username}
          <span>成员</span>
          <button type="button" className="btn btn--ghost" style={{ paddingLeft: 0 }} onClick={() => void logout().then(() => navigate('/login', { replace: true }))}>
            退出登录
          </button>
        </div>
      </aside>
      <div className="shell__work">
        <header className="shell__top">
          <Wordmark to="/" />
          <span className="shell__top-right">
            <small>{current ? `${current.name}` : '排练排程'}</small>
            <Bell active={isNotif} />
          </span>
        </header>
        <main className="shell__main">
          <Outlet />
        </main>
      </div>
      <nav className="shell__nav" aria-label="成员导航">
        {nav}
      </nav>
    </div>
  )
}
