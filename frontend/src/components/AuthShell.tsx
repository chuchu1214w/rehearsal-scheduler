import type { ReactNode } from 'react'

import { Wordmark } from './Wordmark'

export function AuthShell({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children: ReactNode }) {
  return (
    <div className="rs-auth">
      <div className="rs-auth-card">
        <div className="rs-auth-brand">
          <Wordmark height={64} />
          <h1 className="rs-auth-title">{title}</h1>
          {subtitle && <p className="rs-auth-subtitle">{subtitle}</p>}
        </div>
        {children}
      </div>
    </div>
  )
}
