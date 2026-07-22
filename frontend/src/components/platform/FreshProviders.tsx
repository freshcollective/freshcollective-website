'use client'

import type { ReactNode } from 'react'
import { ToastProvider } from './Toast'
import { ConfirmProvider } from './useConfirm'

/**
 * Fresh Collective Providers
 *
 * A single client-boundary wrapper that hosts the app-wide Fresh Collective providers:
 *
 *   - ToastProvider   — enables `useToast()`
 *   - ConfirmProvider — enables `useConfirm()`
 *
 * Mount ONCE at the very root of the application, immediately inside
 * `<body>` in `app/layout.tsx`. Every descendant — server or client —
 * can then rely on the hooks and dialogs being available.
 *
 * Ordering: Confirm is nested inside Toast because a confirmation flow
 * may want to dispatch a toast on the promise resolution.
 */
export function FreshProviders({ children }: { children: ReactNode }) {
  return (
    <ToastProvider>
      <ConfirmProvider>{children}</ConfirmProvider>
    </ToastProvider>
  )
}
