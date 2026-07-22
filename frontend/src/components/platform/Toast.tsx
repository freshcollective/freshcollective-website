'use client'

import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef,
  useState, type ReactNode,
} from 'react'
import { cn } from './utils'

/**
 * Toast
 *
 * Quiet, non-blocking confirmation. Bottom-right, 4-second dwell, single
 * toast at a time (queue after). Use `useToast()` from any component to
 * dispatch.
 *
 * @see docs/fresh-design-language.md §17.1
 */

export type ToastTone = 'info' | 'success' | 'error'

interface ToastMessage {
  id: number
  message: string
  tone: ToastTone
  duration: number
}

interface ToastContextValue {
  show: (message: string, options?: { tone?: ToastTone; duration?: number }) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

const DEFAULT_DURATION = 4000

export function ToastProvider({ children }: { children: ReactNode }) {
  const [queue, setQueue] = useState<ToastMessage[]>([])
  const idRef = useRef(0)

  const show = useCallback(
    (message: string, options?: { tone?: ToastTone; duration?: number }) => {
      idRef.current += 1
      const item: ToastMessage = {
        id: idRef.current,
        message,
        tone: options?.tone ?? 'info',
        duration: options?.duration ?? DEFAULT_DURATION,
      }
      setQueue((prev) => [...prev, item])
    },
    [],
  )

  const value = useMemo<ToastContextValue>(() => ({ show }), [show])

  const active = queue[0]

  useEffect(() => {
    if (!active) return
    const timer = setTimeout(() => {
      setQueue((prev) => prev.slice(1))
    }, active.duration)
    return () => clearTimeout(timer)
  }, [active])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="true"
        className="pointer-events-none fixed bottom-6 right-6 z-[80] flex flex-col gap-2"
      >
        {active && (
          <div
            key={active.id}
            role={active.tone === 'error' ? 'alert' : 'status'}
            className={cn(
              'pointer-events-auto max-w-sm rounded-[var(--fc-radius-lg)] px-4 py-3',
              'shadow-[var(--fc-elev-4)]',
              toneClass(active.tone),
            )}
            style={{ animation: 'fc-toast-in 220ms ease-out' }}
          >
            <p className="text-[length:var(--fc-fs-body)] leading-[var(--fc-lh-body)]">
              {active.message}
            </p>
          </div>
        )}
      </div>
    </ToastContext.Provider>
  )
}

function toneClass(tone: ToastTone): string {
  switch (tone) {
    case 'success':
      return 'bg-[color:var(--fc-surface-card)] text-[color:var(--fc-ink-primary)] border border-[color:var(--fc-status-success)]/25'
    case 'error':
      return 'bg-[color:var(--fc-surface-card)] text-[color:var(--fc-status-error-text)] border border-[color:var(--fc-status-error)]/30'
    case 'info':
    default:
      return 'bg-[color:var(--fc-surface-inverse)] text-[color:var(--fc-ink-inverse)]'
  }
}

/**
 * useToast — dispatch a toast from anywhere below <ToastProvider>.
 */
export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext)
  if (!ctx) {
    throw new Error(
      '[FreshProviders] useToast must be used inside <ToastProvider>. Wrap your app root.',
    )
  }
  return ctx
}
