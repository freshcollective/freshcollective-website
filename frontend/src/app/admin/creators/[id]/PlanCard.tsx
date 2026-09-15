'use client'

/**
 * World Management — Creator Detail → Plan card.
 *
 * Shows the creator's current Fresh Collective plan (name + fee) and
 * exposes the Change Plan modal. The backend endpoint
 * ``POST /api/admin/creators/{user_id}/plan/change`` performs the
 * revoke-then-grant atomically; this modal is a thin form on top.
 *
 * When the creator has no active plan, the card renders the
 * "not configured" state — the primary CTA is the same Change Plan
 * modal, framed as the initial assignment.
 */

import { useState } from 'react'
import { apiUrl } from '@/lib/api'

const INK        = '#0C1826'
const INK_MUTED  = 'rgba(12, 24, 38, 0.60)'
const INK_SOFTER = 'rgba(12, 24, 38, 0.42)'
const CARD_BG    = '#FFFFFF'
const CARD_BORDER = '1px solid #E7EEF0'
const CARD_SHADOW = '0 2px 10px rgba(16, 24, 40, 0.04), 0 1px 2px rgba(16, 24, 40, 0.03)'

// Backend accepts a fixed set of reasons — see PLAN_GRANT_REASONS in
// backend/app/admin/schemas.py. Frontend labels are UI copy only.
const REASON_OPTIONS: Array<[string, string]> = [
  ['correction', 'Administrative correction'],
  ['comp', 'Complimentary / founder terms'],
  ['replacement', 'Replacement / plan change'],
  ['migration', 'Migration from legacy plan'],
  ['temporary', 'Temporary access'],
  ['internal', 'Internal use'],
  ['beta', 'Beta programme'],
  ['other', 'Other (note required)'],
]

const DURATION_OPTIONS: Array<[string, string]> = [
  ['indefinite', 'Indefinite'],
  ['1_month', '1 month'],
  ['3_months', '3 months'],
  ['6_months', '6 months'],
  ['12_months', '12 months'],
]

interface AvailablePlan {
  id: string
  slug: string
  name: string
  transaction_fee_basis_points: number
  monthly_price_cents: number
  is_active: boolean
}

export default function PlanCard({
  userId,
  planName,
  planSlug,
  feeBasisPoints,
  hasActivePlan,
  availablePlans,
}: {
  userId: string
  planName: string
  planSlug: string | null
  feeBasisPoints: number | null
  hasActivePlan: boolean
  availablePlans: AvailablePlan[]
}) {
  const [modalOpen, setModalOpen] = useState(false)
  const [selectedSlug, setSelectedSlug] = useState<string>('')
  const [reason, setReason] = useState<string>('correction')
  const [note, setNote] = useState<string>('')
  const [duration, setDuration] = useState<string>('indefinite')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    if (!selectedSlug) { setError('Select a plan.'); return }
    if (reason === 'other' && !note.trim()) { setError('Reason "Other" requires a note.'); return }
    setSaving(true)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/admin/creators/${userId}/plan/change`),
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            plan_slug: selectedSlug,
            reason,
            note: note.trim() || null,
            duration,
          }),
        },
      )
      if (!res.ok) {
        let detail = `${res.status} ${res.statusText}`
        try {
          const body = (await res.json()) as { detail?: string }
          if (body?.detail) detail = body.detail
        } catch { /* ignore */ }
        throw new Error(detail)
      }
      // The page is server-rendered from getAdminCreators(); a full
      // reload is the simplest way to reflect the new plan.
      window.location.reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed.')
      setSaving(false)
    }
  }

  const feePct = feeBasisPoints == null ? null : (feeBasisPoints / 100).toFixed(feeBasisPoints % 100 === 0 ? 0 : 2)

  return (
    <section
      className="rounded-2xl px-6 py-5 md:px-7 md:py-6"
      style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
    >
      <h2 className="mb-4 font-serif text-[20px] leading-tight" style={{ color: INK }}>
        Fresh Collective plan
      </h2>
      {hasActivePlan ? (
        <>
          <p className="text-[15px]" style={{ color: INK }}>
            <span className="font-medium">{planName}</span>
          </p>
          <p className="mt-1 text-[12.5px]" style={{ color: INK_MUTED }}>
            Transaction fee: <span style={{ color: INK }}>{feePct}% on member sales</span>
          </p>
        </>
      ) : (
        <div
          className="rounded-lg px-3 py-2.5 text-[13px]"
          style={{ background: '#FFF7ED', border: '1px solid #FBD38D', color: '#7C2D12' }}
        >
          No active plan. Paid checkout is unavailable on this
          creator's Collectives until commercial terms are configured.
        </div>
      )}
      <div className="mt-4">
        <button
          type="button"
          onClick={() => { setModalOpen(true); setSelectedSlug(planSlug ?? ''); setError(null) }}
          className="rounded-full border px-4 py-1.5 text-[12.5px] font-semibold transition-colors"
          style={{ borderColor: '#E7EEF0', color: INK, background: '#FFFFFF' }}
        >
          {hasActivePlan ? 'Change plan' : 'Assign plan'}
        </button>
      </div>

      {modalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
          role="dialog"
          aria-modal="true"
        >
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl">
            <h3 className="font-serif text-[22px] leading-tight" style={{ color: INK }}>
              {hasActivePlan ? 'Change Fresh Collective plan' : 'Assign Fresh Collective plan'}
            </h3>
            <p className="mt-1 text-[13px]" style={{ color: INK_MUTED }}>
              {hasActivePlan
                ? 'Atomically revokes the current active plan and grants the new one. Existing PaymentTransactions retain their original transaction fee.'
                : 'Grants an active plan to this creator. Their Collectives will become eligible for paid checkout as soon as the new plan takes effect.'}
            </p>
            <div className="mt-4 space-y-3">
              <label className="block">
                <span className="text-[11.5px] font-semibold uppercase tracking-wider" style={{ color: INK_SOFTER }}>Plan</span>
                <select
                  value={selectedSlug}
                  onChange={(e) => setSelectedSlug(e.target.value)}
                  className="mt-1 w-full rounded-lg border px-3 py-2 text-[13px]"
                  style={{ borderColor: '#E7EEF0', color: INK }}
                >
                  <option value="">Choose a plan…</option>
                  {availablePlans
                    .filter((p) => p.is_active)
                    .map((p) => (
                      <option key={p.slug} value={p.slug}>
                        {p.name} — {(p.transaction_fee_basis_points / 100).toFixed(2)}% fee, ${p.monthly_price_cents / 100}/mo
                      </option>
                    ))}
                </select>
              </label>
              <label className="block">
                <span className="text-[11.5px] font-semibold uppercase tracking-wider" style={{ color: INK_SOFTER }}>Reason</span>
                <select
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  className="mt-1 w-full rounded-lg border px-3 py-2 text-[13px]"
                  style={{ borderColor: '#E7EEF0', color: INK }}
                >
                  {REASON_OPTIONS.map(([v, label]) => (
                    <option key={v} value={v}>{label}</option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="text-[11.5px] font-semibold uppercase tracking-wider" style={{ color: INK_SOFTER }}>Duration</span>
                <select
                  value={duration}
                  onChange={(e) => setDuration(e.target.value)}
                  className="mt-1 w-full rounded-lg border px-3 py-2 text-[13px]"
                  style={{ borderColor: '#E7EEF0', color: INK }}
                >
                  {DURATION_OPTIONS.map(([v, label]) => (
                    <option key={v} value={v}>{label}</option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="text-[11.5px] font-semibold uppercase tracking-wider" style={{ color: INK_SOFTER }}>
                  Note {reason === 'other' && <span style={{ color: '#B45309' }}>*</span>}
                </span>
                <textarea
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  rows={2}
                  className="mt-1 w-full rounded-lg border px-3 py-2 text-[13px]"
                  style={{ borderColor: '#E7EEF0', color: INK }}
                  disabled={saving}
                />
              </label>
            </div>
            {error && (
              <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700">
                {error}
              </div>
            )}
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setModalOpen(false)}
                disabled={saving}
                className="rounded-full border px-4 py-2 text-[12.5px] font-medium transition-colors disabled:opacity-50"
                style={{ borderColor: '#E7EEF0', color: INK }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={submit}
                disabled={saving}
                className="rounded-full px-4 py-2 text-[12.5px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
                style={{ background: '#0F766E' }}
              >
                {saving ? 'Saving…' : (hasActivePlan ? 'Change plan' : 'Assign plan')}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
