import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { api } from './api/client'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { AdminShell } from './layout/AdminShell'
import { MemberShell } from './layout/MemberShell'
import { AccountPage } from './pages/AccountPage'
import { LoginPage } from './pages/LoginPage'
import { SetupPage } from './pages/SetupPage'
import { EventsPage } from './pages/admin/EventsPage'
import { EditorPage } from './pages/admin/EditorPage'
import { ProgressPage } from './pages/admin/ProgressPage'
import { ProxyAvailabilityPage } from './pages/admin/ProxyAvailabilityPage'
import { SchedulePage } from './pages/admin/SchedulePage'
import { SolvePage } from './pages/admin/SolvePage'
import { NewEventPage, WizardPage } from './pages/admin/WizardPage'
import { WorkbenchPage } from './pages/admin/WorkbenchPage'
import { MemberAvailabilityPage } from './pages/member/MemberAvailabilityPage'
import { MemberHomePage } from './pages/member/MemberHomePage'
import { MemberSchedulePage } from './pages/member/MemberSchedulePage'
import { Spinner } from './ui'
import { ToastProvider } from './ui/Toast'

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } })

function FullSpin() {
  return (
    <div className="auth">
      <Spinner />
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

function RoleRoutes() {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <FullSpin />
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />
  if (user.role === 'admin') {
    return (
      <Routes>
        <Route element={<AdminShell />}>
          <Route path="/" element={<EventsPage />} />
          <Route path="/events/new" element={<NewEventPage />} />
          <Route path="/events/:id/wizard/:step" element={<WizardPage />} />
          <Route path="/events/:id" element={<WorkbenchPage />} />
          <Route path="/events/:id/info" element={<EditorPage kind="info" />} />
          <Route path="/events/:id/people" element={<EditorPage kind="people" />} />
          <Route path="/events/:id/songs" element={<EditorPage kind="songs" />} />
          <Route path="/events/:id/rules" element={<EditorPage kind="rules" />} />
          <Route path="/events/:id/progress" element={<ProgressPage />} />
          <Route path="/events/:id/solve" element={<SolvePage />} />
          <Route path="/events/:id/schedule" element={<SchedulePage />} />
          <Route path="/events/:id/availability/:memberId" element={<ProxyAvailabilityPage />} />
          <Route path="/account" element={<AccountPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    )
  }
  return (
    <Routes>
      <Route element={<MemberShell />}>
        <Route path="/" element={<MemberHomePage />} />
        <Route path="/events/:id/availability" element={<MemberAvailabilityPage />} />
        <Route path="/schedule" element={<MemberSchedulePage />} />
        <Route path="/account" element={<AccountPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <AuthProvider>
          <BrowserRouter>
            <SetupGate>
              <Routes>
                <Route path="/setup" element={<SetupPage />} />
                <Route path="/login" element={<LoginPage />} />
                <Route path="*" element={<RoleRoutes />} />
              </Routes>
            </SetupGate>
          </BrowserRouter>
        </AuthProvider>
      </ToastProvider>
    </QueryClientProvider>
  )
}
