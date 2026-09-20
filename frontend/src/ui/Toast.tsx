import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'

interface ToastState {
  text: string
  kind: 'info' | 'error'
}

interface ToastApi {
  toast: (text: string, kind?: 'info' | 'error') => void
  error: (text: string) => void
}

const ToastContext = createContext<ToastApi | null>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ToastState | null>(null)
  const timer = useRef<number | undefined>(undefined)
  const toast = useCallback((text: string, kind: 'info' | 'error' = 'info') => {
    window.clearTimeout(timer.current)
    setState({ text, kind })
    timer.current = window.setTimeout(() => setState(null), kind === 'error' ? 5000 : 3200)
  }, [])
  const api = useMemo<ToastApi>(() => ({ toast, error: (t) => toast(t, 'error') }), [toast])
  return (
    <ToastContext.Provider value={api}>
      {children}
      {state && (
        <div className={'toast' + (state.kind === 'error' ? ' toast--error' : '')} role="status">
          {state.text}
        </div>
      )}
    </ToastContext.Provider>
  )
}

export function useToast(): ToastApi {
  const v = useContext(ToastContext)
  if (!v) throw new Error('useToast 必须在 ToastProvider 内使用')
  return v
}
