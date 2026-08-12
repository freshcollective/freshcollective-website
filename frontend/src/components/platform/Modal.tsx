'use client'

import { useEffect, type ReactNode } from 'react'
import { Heading } from './Heading'
import { IconButton, Button } from './Button'
import { cn } from './utils'

/**
 * Modal
 *
 * Centred, blocking dialog. Reserved for confirmation and short focused
 * decisions per §14. Longer interactions should use `<Drawer>`.
 *
 * @see docs/fresh-design-language.md §14
 */

interface ModalProps {
  open: boolean
  onClose: () => void
  title: string
  /** Optional icon rendered above the title. */
  icon?: ReactNode
  /** ``sm`` (confirmations) · ``md`` (default) · ``lg`` (form-heavy
   *  Creator Studio editors that need more horizontal room). */
  size?: 'sm' | 'md' | 'lg'
  children?: ReactNode
  /** Action row content (buttons). Right-aligned. */
  actions?: ReactNode
  ariaLabel?: string
}

export function Modal({
  open, onClose, title, icon, size = 'md', children, actions, ariaLabel,
}: ModalProps) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prev }
  }, [open])

  if (!open) return null

  const maxWidth =
    size === 'sm' ? 'max-w-sm'
    : size === 'lg' ? 'max-w-2xl'
    : 'max-w-md'

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={ariaLabel ?? title}
      className="fixed inset-0 z-[var(--fc-z-modal)] flex items-center justify-center p-4"
    >
      <div
        aria-hidden="true"
        onClick={onClose}
        className="absolute inset-0 bg-black/40"
        style={{ animation: 'fc-fade-in 180ms ease-out' }}
      />
      {/*
        Height model. The card caps at the viewport with a small
        gutter (32px), then lays out as a column so the body can
        scroll independently while the header and footer remain
        visible. ``100dvh`` preferred over ``100vh`` so mobile
        browsers' shrinking address bars don't clip the footer.
        Falls back to ``100vh`` in browsers that lack ``dvh``.
      */}
      <div
        className={cn(
          'relative flex w-full flex-col',
          maxWidth,
          'rounded-[var(--fc-radius-2xl)] bg-[color:var(--fc-surface-card)] shadow-[var(--fc-elev-5)]',
        )}
        style={{
          animation: 'fc-modal-in 180ms ease-out',
          maxHeight: 'calc(100dvh - 2rem)',
        }}
      >
        <header className="flex shrink-0 items-start justify-between gap-3 border-b border-[color:var(--fc-border-hairline)] px-6 pt-5 pb-4">
          <div className="flex items-start gap-3">
            {icon && (
              <span aria-hidden="true" className="mt-0.5 text-[color:var(--fc-accent-500)]">
                {icon}
              </span>
            )}
            <Heading variant="subsection" as="h2">{title}</Heading>
          </div>
          <IconButton
            ariaLabel="Close"
            variant="tertiary"
            size="sm"
            onClick={onClose}
            className="-mr-2 -mt-1"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
              <path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </IconButton>
        </header>

        {children && (
          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
            {children}
          </div>
        )}

        {actions && (
          <footer className="flex shrink-0 flex-wrap items-center justify-end gap-2 border-t border-[color:var(--fc-border-hairline)] px-6 py-4">
            {actions}
          </footer>
        )}
      </div>
    </div>
  )
}

/**
 * ConfirmDialog — pre-composed confirmation modal. Replaces native `confirm()`.
 *
 * Usage:
 *   <ConfirmDialog
 *     open={open}
 *     onCancel={close}
 *     onConfirm={handleDelete}
 *     title="Delete Week 1 Workbook?"
 *     body="This cannot be undone."
 *     confirmLabel="Delete"
 *     tone="danger"
 *   />
 */
interface ConfirmDialogProps {
  open: boolean
  onCancel: () => void
  onConfirm: () => void
  title: string
  body?: string
  confirmLabel?: string
  cancelLabel?: string
  tone?: 'danger' | 'default'
  loading?: boolean
}

export function ConfirmDialog({
  open, onCancel, onConfirm, title, body,
  confirmLabel = 'Confirm', cancelLabel = 'Cancel',
  tone = 'default', loading = false,
}: ConfirmDialogProps) {
  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={title}
      size="sm"
      actions={
        <>
          <Button variant="tertiary" size="md" onClick={onCancel} disabled={loading}>
            {cancelLabel}
          </Button>
          <Button
            variant={tone === 'danger' ? 'danger' : 'primary'}
            size="md"
            onClick={onConfirm}
            loading={loading}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      {body && (
        <p className="text-[length:var(--fc-fs-body)] leading-[var(--fc-lh-body)] text-[color:var(--fc-ink-primary)]">
          {body}
        </p>
      )}
    </Modal>
  )
}
