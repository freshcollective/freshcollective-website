'use client'

import {
  createContext, useCallback, useContext, useMemo, useRef, useState,
  type ReactNode,
} from 'react'
import { ConfirmDialog } from './Modal'

/**
 * useConfirm
 *
 * A promise-based replacement for native `window.confirm()`. Backed by
 * `<ConfirmDialog>` from `Modal.tsx`, hosted by `<ConfirmProvider>`
 * (mounted by `FreshProviders` in the root layout).
 *
 * Example:
 *
 *   const confirm = useConfirm()
 *   const yes = await confirm({
 *     title: 'Delete Week 1 Workbook?',
 *     body:  'This cannot be undone.',
 *     confirmLabel: 'Delete',
 *     tone: 'danger',
 *   })
 *   if (yes) await patchResource(...)
 *
 * @see docs/fresh-design-language.md §14
 */

export interface ConfirmOptions {
  title: string
  body?: string
  confirmLabel?: string
  cancelLabel?: string
  tone?: 'default' | 'danger'
}

type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>

const ConfirmContext = createContext<ConfirmFn | null>(null)

interface DialogState {
  open: boolean
  options: ConfirmOptions
  loading: boolean
}

const CLOSED_STATE: DialogState = {
  open: false,
  options: { title: '' },
  loading: false,
}

/**
 * ConfirmProvider — hosts the shared confirm dialog.
 * Wrap once at the root; every descendant may call `useConfirm()`.
 */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<DialogState>(CLOSED_STATE)
  const resolverRef = useRef<((v: boolean) => void) | null>(null)

  const confirm = useCallback<ConfirmFn>((options) => {
    return new Promise<boolean>((resolve) => {
      // If a previous prompt is somehow still open, resolve it as cancelled
      // before showing the new one — Fresh Collective forbids stacked dialogs.
      if (resolverRef.current) {
        resolverRef.current(false)
      }
      resolverRef.current = resolve
      setState({ open: true, options, loading: false })
    })
  }, [])

  const handleCancel = useCallback(() => {
    const resolver = resolverRef.current
    resolverRef.current = null
    setState(CLOSED_STATE)
    resolver?.(false)
  }, [])

  const handleConfirm = useCallback(() => {
    const resolver = resolverRef.current
    resolverRef.current = null
    setState(CLOSED_STATE)
    resolver?.(true)
  }, [])

  const contextValue = useMemo(() => confirm, [confirm])

  return (
    <ConfirmContext.Provider value={contextValue}>
      {children}
      <ConfirmDialog
        open={state.open}
        onCancel={handleCancel}
        onConfirm={handleConfirm}
        title={state.options.title}
        body={state.options.body}
        confirmLabel={state.options.confirmLabel}
        cancelLabel={state.options.cancelLabel}
        tone={state.options.tone}
        loading={state.loading}
      />
    </ConfirmContext.Provider>
  )
}

/**
 * useConfirm — call to prompt for confirmation. Resolves to `true` when the
 * user confirms, `false` when they cancel (or press Escape / click backdrop).
 */
export function useConfirm(): ConfirmFn {
  const ctx = useContext(ConfirmContext)
  if (!ctx) {
    throw new Error(
      '[FreshProviders] useConfirm must be used inside <ConfirmProvider>. Wrap your app root with <FreshProviders>.',
    )
  }
  return ctx
}
