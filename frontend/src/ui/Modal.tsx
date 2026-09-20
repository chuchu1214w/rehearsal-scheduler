import { useEffect, type ReactNode } from 'react'

interface Props {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  actions?: ReactNode
}

export function Modal({ open, title, onClose, children, actions }: Props) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [open, onClose])
  if (!open) return null
  return (
    <div
      className="layer"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <section className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <div className="section">
          <h2>{title}</h2>
          <button type="button" className="btn btn--ghost" onClick={onClose}>
            关闭
          </button>
        </div>
        {children}
        {actions && <div className="actions">{actions}</div>}
      </section>
    </div>
  )
}
