import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { App as AntApp, ConfigProvider, Spin } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import type { ReactNode } from 'react'
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'

import { api } from './api/client'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { AppLayout } from './components/AppLayout'
import { AccountPage } from './pages/AccountPage'
import { EventPage } from './pages/EventPage'
import { EventsPage } from './pages/EventsPage'
import { InvitePage } from './pages/InvitePage'
import { LoginPage } from './pages/LoginPage'
import { RosterPage } from './pages/RosterPage'
import { SetupPage } from './pages/SetupPage'
import { SongsPage } from './pages/SongsPage'
import { theme } from './theme'

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } })

function FullSpin() {
  return (
    <div className="rs-auth">
      <Spin size="large" />
    </div>
  )
}

function SetupGate({ children }: { children: ReactNode }) {
  const location = useLocation()
  const status = useQuery({ queryKey: ['setup-status'], queryFn: () => api<{ needs_setup: boolean }>('/api/setup/status') })
  if (status.isPending) return <FullSpin />
  if (status.data?.needs_setup && location.pathname !== '/setup') return <Navigate to="/setup" replace />
  if (status.data && !status.data.needs_setup && location.pathname === '/setup') return <Navigate to="/login" replace />
  return <>{children}</>
}

function RequireAuth({ admin }: { admin?: boolean }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <FullSpin />
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />
  if (admin && user.role !== 'admin') return <Navigate to="/" replace />
  return <Outlet />
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider theme={theme} locale={zhCN}>
        <AntApp>
          <AuthProvider>
            <BrowserRouter>
              <SetupGate>
                <Routes>
                  <Route path="/setup" element={<SetupPage />} />
                  <Route path="/login" element={<LoginPage />} />
                  <Route path="/invite/:token" element={<InvitePage />} />
                  <Route element={<RequireAuth />}>
                    <Route element={<AppLayout />}>
                      <Route path="/" element={<EventsPage />} />
                      <Route path="/events/:id" element={<EventPage />} />
                      <Route path="/events/:id/songs" element={<SongsPage />} />
                      <Route path="/account" element={<AccountPage />} />
                      <Route element={<RequireAuth admin />}>
                        <Route path="/roster" element={<RosterPage />} />
                      </Route>
                    </Route>
                  </Route>
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
              </SetupGate>
            </BrowserRouter>
          </AuthProvider>
        </AntApp>
      </ConfigProvider>
    </QueryClientProvider>
  )
}
