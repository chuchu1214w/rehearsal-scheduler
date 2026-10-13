import { useEffect, useRef, type ReactNode } from 'react'

interface Props {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  actions?: ReactNode
}

export function Modal({ open, title, onClose, children, actions }: Props) {
  const openedAt = useRef(0)
  useEffect(() => {
    if (open) openedAt.current = performance.now()
  }, [open])
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
        // 刚打开时的同一次点按(手机点按后补发的鼠标事件、双击的第二下)不算点背景关闭
        if (e.target !== e.currentTarget || e.detail >= 2 || performance.now() - openedAt.current < 500) return
        onClose()
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
