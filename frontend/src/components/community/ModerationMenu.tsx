'use client'

import { useState, useRef, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import ReportModal from './ReportModal'

/**
 * ModerationMenu — three-dot overflow menu attached to a post or comment.
 *
 * For a post the menu can offer, when the caller opts in:
 *   - Edit — hands off to `onEdit` (parent renders an inline editor)
 *   - Pin / Unpin — uses the creator-only pin endpoint
 *   - Remove — soft-hide (member endpoint; author-or-moderator-only)
 *
 * For a comment only Remove is offered from the moderator side.
 *
 * Report… — appears for every viewer who is not the author. Opens the
 * Community Care report intake modal.
 */

interface Props {
  spaceSlug: string
  postId: string
  commentId?: string
  onRemoved?: () => void
  /** Whether the current viewer can remove this content. Caretakers
   *  (creators / moderators / admins) get this; ordinary members do
   *  not. Defaults to true so existing caretaker callers keep working
   *  without a code change. */
  canRemove?: boolean
  // Post-only creator affordances. When both `canPin` and `isPinned` are
  // provided, a Pin/Unpin action appears above Remove.
  canPin?: boolean
  isPinned?: boolean
  onPinChanged?: (nextPinned: boolean) => void
  // Edit — parent-controlled. When provided, an Edit item appears in
  // the menu that simply invokes this callback.
  onEdit?: () => void
  // When true, the "Report…" item is hidden — used when the viewer is
  // the author of the target content. Defaults to false so callers who
  // don't know can still get the safe default (report is shown).
  hideReport?: boolean
}

export default function ModerationMenu({
  spaceSlug, postId, commentId, onRemoved,
  canRemove = true,
  canPin, isPinned, onPinChanged, onEdit,
  hideReport = false,
}: Props) {
  const router = useRouter()
  const [open, setOpen] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pinBusy, setPinBusy] = useState(false)
  const [reporting, setReporting] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false)
        setConfirming(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  async function handleRemove() {
    setLoading(true)
    setError(null)
    const url = commentId
      ? apiUrl(`/api/spaces/${spaceSlug}/community/${postId}/comments/${commentId}`)
      : apiUrl(`/api/spaces/${spaceSlug}/community/${postId}`)
    try {
      const res = await fetch(url, { method: 'DELETE', credentials: 'include' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError(body.detail ?? 'Could not remove. Please try again.')
        setLoading(false)
        return
      }
      setOpen(false)
      setConfirming(false)
      onRemoved?.()
      router.refresh()
    } catch {
      setError('Could not remove. Please try again.')
      setLoading(false)
    }
  }

  async function handleTogglePin() {
    setPinBusy(true)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/community/${postId}/pin`),
        { method: 'PATCH', credentials: 'include' },
      )
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError(body.detail ?? 'Could not update pin. Please try again.')
        return
      }
      const next = !isPinned
      onPinChanged?.(next)
      setOpen(false)
      router.refresh()
    } catch {
      setError('Could not update pin. Please try again.')
    } finally {
      setPinBusy(false)
    }
  }

  const label = commentId ? 'comment' : 'post'
  const showPin = !commentId && canPin
  const showEdit = !commentId && !!onEdit
  const showRemove = canRemove
  const showReport = !hideReport
  const showDivider = showRemove && (showEdit || showPin || showReport)

  return (
    <div className="relative shrink-0" ref={menuRef}>
      <button
        type="button"
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen(v => !v); setConfirming(false); setError(null) }}
        className="flex h-7 w-7 items-center justify-center rounded-full text-slate-300 transition-colors hover:bg-slate-100 hover:text-slate-500"
        aria-label={commentId ? 'Comment options' : 'Post options'}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <circle cx="5" cy="12" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="19" cy="12" r="2" />
        </svg>
      </button>

      {open && (
        <div
          className="absolute right-0 z-50 mt-1 w-52 rounded-xl border border-slate-200 bg-white py-1 shadow-lg"
          onClick={(e) => e.stopPropagation()}
        >
          {!confirming ? (
            <>
              {showEdit && (
                <button
                  type="button"
                  onClick={() => { setOpen(false); onEdit?.() }}
                  className="w-full px-4 py-2.5 text-left text-[13px] text-navy-900 transition-colors hover:bg-slate-50"
                >
                  Edit post
                </button>
              )}
              {showPin && (
                <button
                  type="button"
                  onClick={handleTogglePin}
                  disabled={pinBusy}
                  className="w-full px-4 py-2.5 text-left text-[13px] text-navy-900 transition-colors hover:bg-slate-50 disabled:opacity-50"
                >
                  {pinBusy ? 'Updating…' : (isPinned ? 'Remove from Start here' : 'Add to Start here')}
                </button>
              )}
              {showReport && (
                <button
                  type="button"
                  onClick={() => { setOpen(false); setReporting(true) }}
                  className="w-full px-4 py-2.5 text-left text-[13px] text-navy-900 transition-colors hover:bg-slate-50"
                >
                  Report {label}…
                </button>
              )}
              {showDivider && (
                <div className="my-1 h-px bg-slate-100" aria-hidden="true" />
              )}
              {showRemove && (
                <button
                  type="button"
                  onClick={() => setConfirming(true)}
                  className="w-full px-4 py-2.5 text-left text-[13px] text-red-600 transition-colors hover:bg-red-50"
                >
                  Remove {label}
                </button>
              )}
              {error && <p className="px-4 pb-2 text-[11px] text-red-600">{error}</p>}
            </>
          ) : (
            <div className="px-4 py-3">
              <p className="mb-3 text-[12px] leading-relaxed text-black">
                Are you sure you want to remove this {label}? This cannot be undone.
              </p>
              {error && <p className="mb-2 text-[11px] text-red-600">{error}</p>}
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={handleRemove}
                  disabled={loading}
                  className="flex-1 rounded-lg bg-red-600 px-3 py-1.5 text-[12px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
                >
                  {loading ? 'Removing…' : 'Yes, remove'}
                </button>
                <button
                  type="button"
                  onClick={() => { setConfirming(false); setError(null) }}
                  className="flex-1 rounded-lg border border-slate-200 px-3 py-1.5 text-[12px] font-medium text-black transition-colors hover:bg-slate-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {reporting && (
        <ReportModal
          kind={commentId ? 'comment' : 'post'}
          targetId={commentId ?? postId}
          onClose={() => setReporting(false)}
        />
      )}
    </div>
  )
}
