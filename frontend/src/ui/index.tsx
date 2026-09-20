import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Link } from 'react-router-dom'

import type { Step } from '../api/types'

export function Wordmark({ big = false, to }: { big?: boolean; to?: string }) {
  const cls = 'wordmark' + (big ? ' wordmark--big' : '')
  const inner = (
    <>
      Season<span className="star">✦</span>
    </>
  )
  return to ? (
    <Link to={to} className={cls} aria-label="Season">
      {inner}
    </Link>
  ) : (
    <span className={cls}>{inner}</span>
  )
}

type Variant = 'default' | 'primary' | 'ghost' | 'danger' | 'ghost-danger'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  full?: boolean
  small?: boolean
  loading?: boolean
}

export function Button({ variant = 'default', full, small, loading, className = '', children, disabled, type = 'button', ...rest }: ButtonProps) {
  const cls = [
    'btn',
    variant === 'primary' && 'btn--primary',
    (variant === 'ghost' || variant === 'ghost-danger') && 'btn--ghost',
    (variant === 'danger' || variant === 'ghost-danger') && 'btn--danger',
    full && 'btn--full',
    small && 'btn--sm',
    className,
  ]
    .filter(Boolean)
    .join(' ')
  return (
    <button type={type} className={cls} disabled={disabled || loading} {...rest}>
      {loading ? '处理中…' : children}
    </button>
  )
}

export function LinkButton({ to, variant = 'default', full, small, children }: { to: string; variant?: Variant; full?: boolean; small?: boolean; children: ReactNode }) {
  const cls = ['btn', variant === 'primary' && 'btn--primary', variant === 'ghost' && 'btn--ghost', full && 'btn--full', small && 'btn--sm'].filter(Boolean).join(' ')
  return (
    <Link to={to} className={cls}>
      {children}
    </Link>
  )
}

export function Badge({ tone = 'accent', children }: { tone?: 'accent' | 'green' | 'orange' | 'red' | 'neutral'; children: ReactNode }) {
  return <span className={'badge' + (tone !== 'accent' ? ` badge--${tone}` : '')}>{children}</span>
}

export function Note({ tone = 'info', children }: { tone?: 'info' | 'warning' | 'error'; children: ReactNode }) {
  return <div className={'note' + (tone !== 'info' ? ` note--${tone}` : '')}>{children}</div>
}

export function Panel({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={'panel ' + className}>{children}</section>
}

export function Heading({ title, subtitle, action }: { title: string; subtitle?: ReactNode; action?: ReactNode }) {
  return (
    <div className="heading">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {action}
    </div>
  )
}

export function Back({ to, label = '返回' }: { to: string; label?: string }) {
  return (
    <Link to={to} className="back">
      ← {label}
    </Link>
  )
}

export function Field({ label, hint, full, children }: { label: ReactNode; hint?: ReactNode; full?: boolean; children: ReactNode }) {
  return (
    <label className={'field' + (full ? ' field--full' : '')}>
      <span>
        <span>{label}</span>
        {hint && <span className="muted">{hint}</span>}
      </span>
      {children}
    </label>
  )
}

export function Spinner({ text = '加载中…' }: { text?: string }) {
  return <div className="spinner">{text}</div>
}

export function Empty({ title, text, action }: { title: string; text?: string; action?: ReactNode }) {
  return (
    <div className="empty">
      <h1>{title}</h1>
      {text && <p>{text}</p>}
      {action}
    </div>
  )
}

export function KV({ label, children, title }: { label: string; children: ReactNode; title?: boolean }) {
  return (
    <div className={'kv' + (title ? ' kv--title' : '')}>
      <span>{label}</span>
      <div>{children}</div>
    </div>
  )
}

export function Steps({ steps, eventId }: { steps: Step[]; eventId: number }) {
  const routes: Record<string, string> = {
    info: 'info',
    members: 'people',
    songs: 'songs',
    rules: 'rules',
    availability: 'progress',
    solve: 'solve',
    schedule: 'schedule',
  }
  const short: Record<string, string> = { info: '信息', members: '人员', songs: '曲目', rules: '要求', availability: '填报', solve: '排程', schedule: '排练表' }
  return (
    <div className="steps" aria-label="七步筹备进度">
      {steps.map((s) => (
        <Link key={s.key} to={`/events/${eventId}/${routes[s.key]}`} className={`step step--${s.state}`}>
          <b>{s.state === 'done' ? '✓' : s.no}</b>
          {short[s.key] ?? s.label}
        </Link>
      ))}
    </div>
  )
}

export function CheckRow({ level, children }: { level: 'ok' | 'warn' | 'error'; children: ReactNode }) {
  return (
    <div className="checkrow">
      <span className={'checkmark' + (level === 'warn' ? ' checkmark--warn' : level === 'error' ? ' checkmark--error' : '')}>{level === 'ok' ? '✓' : '!'}</span>
      <span>{children}</span>
    </div>
  )
}

export function PrimaryBar({ note, children }: { note?: ReactNode; children: ReactNode }) {
  return (
    <div className="primary-bar">
      {note && <p>{note}</p>}
      {children}
    </div>
  )
}

export function Tabs<T extends string>({ value, options, onChange }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="tabs">
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={value === o.value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  )
}
