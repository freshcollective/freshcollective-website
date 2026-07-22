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
  size?: 'sm' | 'md'
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

  const maxWidth = size === 'sm' ? 'max-w-sm' : 'max-w-md'

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
      <div
        className={cn(
          'relative w-full',
          maxWidth,
          'rounded-[var(--fc-radius-2xl)] bg-[color:var(--fc-surface-card)] shadow-[var(--fc-elev-5)]',
        )}
        style={{ animation: 'fc-modal-in 180ms ease-out' }}
      >
        <header className="flex items-start justify-between gap-3 px-6 pt-5">
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

        {children && <div className="px-6 py-4">{children}</div>}

        {actions && (
          <footer className="flex flex-wrap items-center justify-end gap-2 px-6 pb-5 pt-1">
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
