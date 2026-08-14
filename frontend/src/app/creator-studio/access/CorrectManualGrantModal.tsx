'use client'

import { useState } from 'react'
import { apiUrl } from '@/lib/api'
import type { AccessPassAdminSummary } from '@/types/platform'

/**
 * Correct a manually-granted Access record.
 *
 * Two safe operations, per U1 refinement §5 (final pass):
 *
 *   Save correction   — safe reason/note patch via
 *                       ``PATCH /commerce/manual-grant/{txn_id}``.
 *                       No amount / payment-method editing —
 *                       Grant Access is an access operation.
 *
 *   Cancel this grant — ``DELETE /commerce/manual-grant/{txn_id}``.
 *                       Cancels linked AccessPasses and revokes the
 *                       linked manual PathwayEntitlement (safely,
 *                       per the backend rules). Marks the ledger row
 *                       cancelled. Parent may then open Grant Access
 *                       again with the same member preselected — no
 *                       fake atomic "replace Payment Option".
 *
 * The modal is only opened for rows the backend identifies as
 * manual grants (``access_source !== 'purchase'`` AND
 * ``payment_transaction_id`` present) — the "Correct" button is
 * hidden otherwise.
 */

// Only the two on-platform-friendly reasons — matches the create flow.
// Legacy bank_transfer / cash rows still get 'Manual' as a display
// fallback (backend accepts them for correction; UI collapses them
// into Manual).
const SOURCE_OPTIONS = [
  { value: 'complimentary', label: 'Complimentary', helper: 'Access intentionally provided at no charge.' },
  { value: 'manual',        label: 'Manual access', helper: 'Administrative or exceptional access arranged manually.' },
]

/** Map an incoming ``access_source`` value onto one of the two
 *  canonical UI choices. Legacy off-platform sources fold into
 *  "Manual access" so the Creator can re-label without confusion. */
function canonicaliseSource(src: string | null | undefined): string {
  if (src === 'complimentary') return 'complimentary'
  return 'manual'
}

interface Props {
  spaceSlug: string
  pass: AccessPassAdminSummary
  onClose: () => void
  onSaved: () => void
  /** Called after a successful cancellation. Parent can use this to
   *  open Grant Access with the same member preselected so the
   *  Creator can immediately grant replacement access. */
  onCancelled?: () => void
}

export default function CorrectManualGrantModal({
  spaceSlug, pass, onClose, onSaved, onCancelled,
}: Props) {
  const [source, setSource] = useState<string>(canonicaliseSource(pass.access_source))
  const [notes, setNotes] = useState<string>('')
  const [saving, setSaving] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [cancelSummary, setCancelSummary] = useState<{
    revoked_access_passes: number
    revoked_entitlement_id: string | null
    entitlement_left_intact_reason: string | null
  } | null>(null)

  const txnId = pass.payment_transaction_id

  async function saveCorrection() {
    if (!txnId) return
    setError(null)
    setSaving(true)
    try {
      const body: Record<string, unknown> = { source }
      // Empty notes = "leave existing note alone". A single space
      // clears the operator-supplied note (backend trims).
      if (notes !== '') {
        body.notes = notes.trim() || null
      }
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/commerce/manual-grant/${txnId}`),
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify(body),
        },
      )
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : `Save failed (${res.status})`)
      }
      onSaved()
    } catch (err) {
      setError(String((err as Error)?.message ?? err))
    } finally {
      setSaving(false)
    }
  }

  async function cancelGrant() {
    if (!txnId) return
    const ok = confirm(
      'Cancel this manual grant?\n\nThis will:\n' +
      '  \u00b7 mark the transaction cancelled\n' +
      '  \u00b7 cancel any Access pass this grant produced\n' +
      '  \u00b7 revoke the linked Pathway entitlement when it\u2019s safe to do so\n\n' +
      'You can then issue replacement access with the correct Payment Option.'
    )
    if (!ok) return
    setError(null)
    setCancelSummary(null)
    setCancelling(true)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/commerce/manual-grant/${txnId}`),
        { method: 'DELETE', credentials: 'include' },
      )
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : `Cancel failed (${res.status})`)
      }
      const summary = await res.json() as {
        revoked_access_passes: number
        revoked_entitlement_id: string | null
        entitlement_left_intact_reason: string | null
      }
      setCancelSummary(summary)
      // Do not close/onSaved yet — show the confirmation with the
      // replacement CTA so the Creator can act on it directly.
    } catch (err) {
      setError(String((err as Error)?.message ?? err))
    } finally {
      setCancelling(false)
    }
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-2xl bg-white p-6 shadow-xl overflow-y-auto max-h-[90vh]">

        {cancelSummary ? (
          // ── Post-cancellation confirmation with replacement CTA ──
          <div>
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h2 className="text-[17px] font-semibold text-navy-900">Grant cancelled</h2>
                <p className="mt-0.5 text-[12px] text-slate-500">
                  {cancelSummary.revoked_access_passes} access record{cancelSummary.revoked_access_passes === 1 ? '' : 's'} cancelled
                  {cancelSummary.revoked_entitlement_id && ' \u00b7 linked entitlement revoked'}.
                </p>
              </div>
              <button onClick={onClose} className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 hover:bg-slate-100">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M1 1l10 10M11 1L1 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
              </button>
            </div>

            {cancelSummary.entitlement_left_intact_reason && (
              <p className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-800">
                Note: {cancelSummary.entitlement_left_intact_reason}
              </p>
            )}

            <p className="mb-4 text-[13px] text-slate-700">
              If the wrong Payment Option was chosen, you can grant replacement
              access to <strong>{pass.member_name ?? pass.member_email ?? 'this member'}</strong> now.
            </p>

            <div className="flex flex-wrap items-center gap-2">
              {onCancelled && (
                <button
                  onClick={() => { onSaved(); onCancelled() }}
                  className="rounded-xl px-4 py-2.5 text-[13px] font-semibold text-white"
                  style={{ background: '#38A09E' }}
                >
                  Grant replacement access →
                </button>
              )}
              <button
                onClick={() => { onSaved(); onClose() }}
                className="rounded-xl px-4 py-2.5 text-[13px] font-medium text-slate-600 hover:bg-slate-50"
              >
                Done
              </button>
            </div>
          </div>
        ) : (
          // ── Edit form ─────────────────────────────────────────
          <div>
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h2 className="text-[17px] font-semibold text-navy-900">Correct manual grant</h2>
                <p className="mt-0.5 text-[12px] text-slate-500">
                  Editing an access record you created manually. Card
                  purchases are not editable here.
                </p>
              </div>
              <button onClick={onClose} className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 hover:bg-slate-100">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M1 1l10 10M11 1L1 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
              </button>
            </div>

            <div className="mb-4 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5">
              <p className="text-[12px] text-slate-500">Member</p>
              <p className="text-[13px] font-semibold text-navy-900">
                {pass.member_name ?? pass.member_email ?? '—'}
              </p>
              <p className="mt-1.5 text-[12px] text-slate-500">Payment Option</p>
              <p className="text-[13px] font-semibold text-navy-900">
                {pass.option_name ?? '—'}
              </p>
            </div>

            <div className="space-y-4">
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-black">Reason</label>
                <div className="space-y-2">
                  {SOURCE_OPTIONS.map(o => (
                    <label key={o.value}
                      className={`flex cursor-pointer items-start gap-3 rounded-xl border px-3 py-2.5 transition-colors ${
                        source === o.value
                          ? 'border-teal-300 bg-teal-50/40'
                          : 'border-slate-200 hover:border-slate-300'
                      }`}>
                      <input type="radio" name="source" value={o.value}
                        checked={source === o.value}
                        onChange={e => setSource(e.target.value)}
                        className="mt-0.5 h-4 w-4 accent-teal-600" />
                      <span className="min-w-0">
                        <span className="block text-[13px] font-semibold text-navy-900">{o.label}</span>
                        <span className="mt-0.5 block text-[11.5px] text-slate-500">{o.helper}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </div>

              <div>
                <label className="mb-1 block text-[12px] font-semibold text-black">Notes</label>
                <textarea
                  rows={2} value={notes} onChange={(e) => setNotes(e.target.value)}
                  placeholder="Leave blank to keep the existing note"
                  className="w-full resize-none rounded-xl border border-slate-200 px-3 py-2 text-[13px] text-navy-900 focus:outline-none focus:ring-2 focus:ring-teal-400"
                />
              </div>

              {error && <p className="text-[12px] text-red-500">{error}</p>}

              <div className="flex flex-wrap items-center gap-2 pt-1">
                <button
                  onClick={saveCorrection}
                  disabled={saving || cancelling}
                  className="rounded-xl px-4 py-2.5 text-[13px] font-semibold text-white disabled:opacity-50 disabled:cursor-not-allowed"
                  style={{ background: '#38A09E' }}
                >
                  {saving ? 'Saving…' : 'Save correction'}
                </button>
                <button
                  onClick={cancelGrant}
                  disabled={saving || cancelling}
                  className="rounded-xl border border-red-200 bg-white px-4 py-2.5 text-[13px] font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {cancelling ? 'Cancelling…' : 'Cancel this grant'}
                </button>
                <button
                  onClick={onClose}
                  className="ml-auto rounded-xl px-4 py-2.5 text-[13px] font-medium text-slate-600 hover:bg-slate-50"
                >
                  Close
                </button>
              </div>

              <p className="pt-1 text-[11px] text-slate-500">
                <strong>Wrong Payment Option?</strong> Cancel this grant and use
                the confirmation to issue replacement access. Payment-Option
                changes aren't done in place because bundle reversal isn't
                always safe.
              </p>
            </div>
          </div>
        )}
      </div>
    </>
  )
}
