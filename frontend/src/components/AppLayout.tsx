import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext'
import { Wordmark } from './Wordmark'

export function AppLayout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const links = [
    { to: '/', label: '活动' },
    ...(user?.role === 'admin' ? [{ to: '/roster', label: '名册' }] : []),
    { to: '/account', label: '账号' },
  ]
  return (
    <div className="rs-shell">
      <header className="rs-header">
        <Link to="/" className="rs-brand">
          <Wordmark height={42} />
          <span className="rs-brand-sub">排练排程</span>
        </Link>
        <nav className="rs-nav">
          {links.map((l) => (
            <NavLink key={l.to} to={l.to} end={l.to === '/'} className={({ isActive }) => 'rs-nav-link' + (isActive ? ' is-active' : '')}>
              {l.label}
            </NavLink>
          ))}
          <button
            type="button"
            className="rs-nav-link"
            onClick={async () => {
              await logout()
              navigate('/login', { replace: true })
            }}
          >
            退出
          </button>
        </nav>
      </header>
      <main className="rs-main">
        <Outlet />
      </main>
      <footer className="rs-footer">✦ Season · 舞团排练排程 ✦</footer>
    </div>
  )
}

export function PageHeader({ title, subtitle, extra }: { title: string; subtitle?: string; extra?: React.ReactNode }) {
  return (
    <div className="rs-page-header">
      <div>
        <h1 className="rs-title">{title}</h1>
        {subtitle && <p className="rs-subtitle">{subtitle}</p>}
      </div>
      {extra && <div>{extra}</div>}
    </div>
  )
}
