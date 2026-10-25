'use client'

/**
 * Removed people — and the restrictions the creator has imposed.
 *
 * ``GET /members`` filters on ``status='active'``, so before this there
 * was no surface showing who had been removed, why, or who was blocked
 * from returning. A creator could impose a restriction and then had no
 * way to see it, let alone lift it.
 *
 * Deliberately not a moderation dashboard. It answers four questions and
 * stops: who was removed, why, may they come back, and is there money
 * still outstanding. Lifting a block is the one action, and only the
 * Collective's owner sees it — the server refuses anybody else.
 *
 * The explanation is shown here and nowhere else. It never reaches a
 * member-facing payload.
 */

import Link from 'next/link'
import { useCallback, useState } from 'react'
import { apiUrl } from '@/lib/api'
import type { RemovedMember } from '@/types/platform'

const REASON_LABELS: Record<string, string> = {
  member_requested:        'Member requested removal',
  no_longer_required:      'Membership no longer required',
  inappropriate_behaviour: 'Inappropriate behaviour',
  payment_issues:          'Payment issues',
  other:                   'Other',
}

const KIND_LABELS: Record<string, string> = {
  voluntary: 'Left on their own',
  creator:   'Removed by the collective',
  admin:     'Removed by Fresh Collective',
  auto_role: 'Removed automatically',
}

function formatDate(iso: string | null): string {
  if (!iso) return 'Date not recorded'
  return new Date(iso).toLocaleDateString('en-AU', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

/**
 * Block future membership — the same decision as the removal dialog's
 * rejoin control, taken after the fact.
 *
 * Same chrome as ``RemoveMemberModal`` in ``PeopleClient``: the
 * backdrop, the rounded card, the destructive-primary-plus-cancel
 * footer. Deliberately no new design — this is one more instance of a
 * dialog this surface already has, not a new kind of thing.
 *
 * The reason is required, matching the server (``RejoinPolicyRequest``
 * refuses a blank note) and matching the removal dialog. The confirm
 * button stays disabled until there is something written, so the
 * requirement is visible before it is enforced.
 */
function BlockRejoiningDialog({ name, busy, onCancel, onConfirm }: {
  name: string
  busy: boolean
  onCancel: () => void
  onConfirm: (note: string) => void
}) {
  const [note, setNote] = useState('')
  const ready = note.trim().length > 0

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.45)' }}
      role="dialog"
      aria-modal="true"
      aria-label={`Block future membership for ${name}`}
    >
      <div className="max-h-[calc(100dvh-2rem)] w-full max-w-sm overflow-y-auto rounded-2xl border border-border bg-white shadow-xl">
        <div className="px-6 py-5">
          <h3 className="text-[16px] font-semibold text-navy-900">
            Block future membership?
          </h3>
          <p className="mt-3 text-[14px] leading-relaxed text-black">
            <span className="font-medium">{name}</span> will not be able to
            rejoin this collective, and will not be able to make new purchases
            from it — including free offerings.
          </p>
          <p className="mt-2 text-[13px] leading-relaxed text-black">
            Anything they have already bought stays theirs. You can lift this
            at any time.
          </p>

          <label className="mt-4 block text-[13px] font-medium text-navy-800">
            Reason (required)
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              disabled={busy}
              rows={3}
              autoFocus
              placeholder="What happened?"
              className="mt-1.5 w-full rounded-xl border border-border bg-white px-3 py-2 text-[14px] text-navy-900"
            />
          </label>
          <p className="mt-1 text-[12px] text-black">
            Recorded for your reference. Only you and your moderators can see
            it.
          </p>
        </div>
        <div className="flex gap-2 border-t border-border px-6 py-4">
          <button
            onClick={() => onConfirm(note.trim())}
            disabled={busy || !ready}
            className="flex-1 rounded-xl px-4 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            style={{ background: '#dc2626' }}
          >
            {busy ? 'Blocking…' : 'Block future membership'}
          </button>
          <button
            onClick={onCancel}
            disabled={busy}
            className="flex-1 rounded-xl border border-border px-4 py-2.5 text-[14px] font-medium text-black hover:bg-slate-50 disabled:opacity-50"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}


export default function RemovedPeople({
  spaceSlug, removed, canManage,
}: {
  spaceSlug: string
  removed: RemovedMember[]
  /** Owner-only. Imposing and lifting a block is the founder's call. */
  canManage: boolean
}) {
  const [rows, setRows] = useState<RemovedMember[]>(removed)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [blocking, setBlocking] = useState<RemovedMember | null>(null)

  const setPolicy = useCallback(async (
    userId: string, blocked: boolean, note: string | null,
  ) => {
    setBusyId(userId)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/members/${userId}/rejoin-policy`),
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ rejoin_blocked: blocked, note }),
        },
      )
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError(
          typeof body?.detail === 'string'
            ? body.detail
            : 'Could not update this. Please try again.',
        )
        return
      }
      setRows((prev) => prev.map((r) => (
        r.user_id === userId
          ? { ...r, rejoin_blocked: blocked, may_rejoin: !blocked }
          : r
      )))
    } catch {
      setError('Could not update this. Please try again.')
    } finally {
      setBusyId(null)
    }
  }, [spaceSlug])

  if (rows.length === 0) return null

  return (
    <section className="mt-10">
      <h2 className="text-[15px] font-semibold text-navy-900">Removed people</h2>
      <p className="mt-1 text-[13px] text-black">
        Only you and your moderators can see this. Explanations are never
        shown to members.
      </p>

      {error && (
        <p className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-700">
          {error}
        </p>
      )}

      <div className="mt-4 flex flex-col gap-3">
        {rows.map((r) => (
          <div
            key={r.user_id}
            className="rounded-2xl border border-border bg-white px-5 py-4"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[14px] font-medium text-navy-800">
                  {r.display_name}
                </p>
                <p className="mt-0.5 text-[12px] text-black">{r.email}</p>
                <p className="mt-1.5 text-[12px] text-black">
                  {KIND_LABELS[r.removal_kind ?? ''] ?? 'Removal not recorded'}
                  {' · '}
                  {formatDate(r.removed_at)}
                  {r.removed_by_display_name ? ` · by ${r.removed_by_display_name}` : ''}
                </p>
                {r.removal_reason && (
                  <p className="mt-1 text-[12px] text-black">
                    Reason: {REASON_LABELS[r.removal_reason] ?? r.removal_reason}
                  </p>
                )}
                {r.note && (
                  <p className="mt-1.5 whitespace-pre-line text-[13px] leading-relaxed text-navy-800">
                    {r.note}
                  </p>
                )}
              </div>

              <div className="flex shrink-0 flex-col items-end gap-2">
                <span
                  className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${
                    r.rejoin_blocked
                      ? 'border border-red-200 bg-red-50 text-red-700'
                      : 'border border-slate-200 bg-slate-50 text-slate-600'
                  }`}
                >
                  {r.rejoin_blocked ? 'Blocked from rejoining' : 'Can rejoin'}
                </span>
                {canManage && (
                  r.rejoin_blocked ? (
                    <button
                      type="button"
                      disabled={busyId === r.user_id}
                      onClick={() => setPolicy(r.user_id, false, 'Restriction lifted.')}
                      className="rounded-xl border border-border px-3 py-1.5 text-[12px] font-medium text-black transition-colors hover:bg-slate-50 disabled:opacity-50"
                    >
                      {busyId === r.user_id ? 'Updating…' : 'Allow rejoining'}
                    </button>
                  ) : (
                    <button
                      type="button"
                      disabled={busyId === r.user_id}
                      onClick={() => setBlocking(r)}
                      className="rounded-xl border border-border px-3 py-1.5 text-[12px] font-medium text-black transition-colors hover:bg-slate-50 disabled:opacity-50"
                    >
                      Block rejoining
                    </button>
                  )
                )}
              </div>
            </div>

            {/*
              Driven by ``payment_action_outstanding``, which the server
              derives from the plans themselves — NOT by
              ``payment_action_required``, which is the audit fact that
              the removal was taken with a plan live and stays true
              forever. So this clears itself when the plan is cancelled
              (by this creator or by an administrator) or ends
              naturally, and a FAILED cancellation leaves the plan live
              and the warning standing.
            */}
            {r.payment_action_outstanding && (
              <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2.5">
                <p className="text-[12.5px] font-semibold text-amber-900">
                  Payment arrangement requires attention
                </p>
                <p className="mt-1 text-[12px] leading-relaxed text-amber-900">
                  This member has an active instalment plan. Their membership
                  has been removed, but future payments may continue until the
                  plan is cancelled.
                </p>
                <Link
                  href={`/creator-studio/payment-plans?member=${encodeURIComponent(r.email)}`}
                  className="mt-1.5 inline-flex items-center gap-1 text-[12px] font-semibold text-amber-900 underline decoration-amber-400 underline-offset-2 transition-colors hover:text-amber-950"
                >
                  Manage payment plan
                  <span aria-hidden="true">&rarr;</span>
                </Link>
              </div>
            )}
          </div>
        ))}
      </div>

      {blocking && (
        <BlockRejoiningDialog
          name={blocking.display_name}
          busy={busyId === blocking.user_id}
          onCancel={() => setBlocking(null)}
          onConfirm={async (note) => {
            const target = blocking.user_id
            await setPolicy(target, true, note)
            setBlocking(null)
          }}
        />
      )}
    </section>
  )
}
