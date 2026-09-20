import { NavLink, Outlet, useLocation, useMatch, useNavigate } from 'react-router-dom'

import { useEvents } from '../api/hooks'
import { useAuth } from '../auth/AuthContext'
import { Wordmark } from '../ui'
import { IconCalendar, IconHome, IconUser } from './icons'

export function AdminShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const match = useMatch('/events/:id/*')
  const eventId = match?.params.id && match.params.id !== 'new' ? Number(match.params.id) : null
  const events = useEvents()

  const homeTo = eventId ? `/events/${eventId}` : '/'
  const scheduleTo = eventId ? `/events/${eventId}/schedule` : '/'
  const isHome = eventId ? location.pathname === homeTo || (!location.pathname.includes('/schedule') && location.pathname !== '/account') : location.pathname === '/'
  const isSchedule = eventId ? location.pathname.includes('/schedule') : false
  const isAccount = location.pathname === '/account'

  const nav = (
    <>
      <NavLink to={homeTo} className={'navbtn' + (isHome ? ' is-active' : '')} end>
        <IconHome />
        工作台
      </NavLink>
      <NavLink to={scheduleTo} className={'navbtn' + (isSchedule ? ' is-active' : '')}>
        <IconCalendar />
        排练表
      </NavLink>
      <NavLink to="/account" className={'navbtn' + (isAccount ? ' is-active' : '')}>
        <IconUser />
        账号
      </NavLink>
    </>
  )

  const showbar = eventId !== null && (
    <div className="showbar">
      <button type="button" className="showbar__back" aria-label="返回演出列表" onClick={() => navigate('/')}>
        ‹
      </button>
      <select
        aria-label="切换演出"
        value={String(eventId)}
        onChange={(e) => {
          if (e.target.value === 'new') navigate('/events/new')
          else if (e.target.value === 'list') navigate('/')
          else navigate(`/events/${e.target.value}`)
        }}
      >
        {(events.data ?? []).map((ev) => (
          <option key={ev.id} value={ev.id}>
            {ev.name}
          </option>
        ))}
        {events.data && !events.data.some((ev) => ev.id === eventId) && <option value={String(eventId)}>当前演出</option>}
        <option value="list">全部演出…</option>
        <option value="new">＋ 新建演出</option>
      </select>
    </div>
  )

  return (
    <div className="shell shell-admin">
      <aside className="sidebar">
        <div className="brand">
          <Wordmark to="/" />
          <small>排练排程 · 管理员</small>
        </div>
        {nav}
        <div className="sidebar__bottom">
          {user?.username}
          <span>管理员</span>
          <button type="button" className="btn btn--ghost" style={{ paddingLeft: 0 }} onClick={() => void logout().then(() => navigate('/login', { replace: true }))}>
            退出登录
          </button>
        </div>
      </aside>
      <div className="shell__work">
        <header className="shell__top">
          <div className="brand">
            <Wordmark to="/" />
            <small>排练排程</small>
          </div>
          <span className="tag-role">管理员</span>
        </header>
        {showbar}
        <main className="shell__main">
          <Outlet />
        </main>
      </div>
      <nav className="shell__nav" aria-label="主导航">
        {nav}
      </nav>
    </div>
  )
}
