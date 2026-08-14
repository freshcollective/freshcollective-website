'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import type { AccessPassAdminSummary, CreatorMemberDetail } from '@/types/platform'
import { apiUrl } from '@/lib/api'
import CollectiveArtworkHeader from '@/components/creator/CollectiveArtworkHeader'
import { Button } from '@/components/platform/Button'
import { PlusIcon } from '@/components/creator/PrimaryActionLink'
import CorrectManualGrantModal from './CorrectManualGrantModal'

interface Props {
  passes: AccessPassAdminSummary[]
  spaceName: string
  spaceSlug: string
  headerLocation: { name?: string; hero_artwork_url?: string | null; thumbnail_artwork_url?: string | null } | null
  headerCoverImageUrl: string | null
}

const STATUS_LABELS: Record<string, string> = {
  active: 'Active',
  pending: 'Pending',
  expired: 'Expired',
  cancelled: 'Cancelled',
  used: 'Used',
  suspended: 'Suspended',
}

const STATUS_COLOURS: Record<string, string> = {
  active: 'bg-teal-50 text-teal-700 border-teal-200',
  pending: 'bg-amber-50 text-amber-700 border-amber-200',
  expired: 'bg-slate-100 text-slate-500 border-slate-200',
  cancelled: 'bg-red-50 text-red-600 border-red-200',
  used: 'bg-slate-100 text-slate-500 border-slate-200',
  suspended: 'bg-orange-50 text-orange-600 border-orange-200',
}

const PASS_TYPE_LABELS: Record<string, string> = {
  term_pass: 'Term Pass',
  class_pass: 'Class Pass',
  pathway_access: 'Pathway Access',
  event_ticket: 'Event Ticket',
  retreat_booking: 'Retreat Booking',
  membership: 'Membership',
  bundle: 'Bundle',
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })
}

/** True when the pass row was produced by a manual grant and can
 *  therefore be corrected in place. Rows without a linked
 *  transaction (very old data) and Stripe purchases are read-only. */
function isCorrectable(pass: AccessPassAdminSummary): boolean {
  if (!pass.payment_transaction_id) return false
  const src = pass.access_source
  return src === 'complimentary'
    || src === 'bank_transfer'
    || src === 'cash'
    || src === 'admin_grant'
    || src === 'manual'
}

/** Human-friendly label for the ``access_source`` field returned
 *  by the backend.
 *
 *  U1 final: only three canonical source labels are shown to the
 *  Creator — Purchase / Complimentary / Manual. Legacy off-platform
 *  labels (bank_transfer / cash / admin_grant) fold into "Manual"
 *  so we don't advertise them as first-class Grant Access choices;
 *  the underlying row is preserved.
 */
function formatSource(src: string | null | undefined): string {
  switch (src) {
    case 'purchase':          return 'Purchase'
    case 'one_time_purchase': return 'Purchase'
    case 'subscription':      return 'Subscription'
    case 'complimentary':     return 'Complimentary'
    case 'free':              return 'Free'
    // Legacy off-platform + generic manual → "Manual" for display.
    case 'bank_transfer':     return 'Manual'
    case 'cash':              return 'Manual'
    case 'admin_grant':       return 'Manual'
    case 'manual':            return 'Manual'
    default:                  return src ?? '—'
  }
}

function CreditBar({ used, total }: { used: number; total: number | null }) {
  if (total === null) {
    return <span className="text-[13px] text-black">Unlimited</span>
  }
  const remaining = Math.max(0, total - used)
  const pct = total > 0 ? Math.round((remaining / total) * 100) : 0
  const barColour = pct > 40 ? '#38A09E' : pct > 15 ? '#F59E0B' : '#EF4444'
  return (
    <div>
      <span className="text-[13px] font-semibold text-navy-900">{remaining}</span>
      <span className="text-[12px] text-black"> / {total}</span>
      <div className="mt-1 h-1.5 w-24 overflow-hidden rounded-full bg-slate-100">
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: barColour }} />
      </div>
    </div>
  )
}

// (Legacy PaymentOptionItem removed — the manual-grant modal now
//  binds to the Collective-scoped ``CentralPaymentOptionSummary``
//  returned by ``/commerce/payment-options``.)

// Grant Access is an access operation, not a payments workflow.
// Creator Studio deliberately does NOT offer bank-transfer / cash
// choices here — we don't want to normalise taking payments outside
// Fresh Collective. Two reasons only:
//
//   Complimentary — access intentionally provided at no charge.
//   Manual access — administrative or exceptional access arranged
//                   manually.
//
// Both use the same PaymentOption → resolve → validate → atomic
// apply pipeline, so the full grant bundle is created correctly.
// Any resulting PaymentTransaction row is a $0 audit anchor and
// is filtered out of Payments received.
const SOURCE_OPTIONS = [
  {
    value: 'complimentary',
    label: 'Complimentary',
    helper: 'Access intentionally provided at no charge.',
  },
  {
    value: 'manual',
    label: 'Manual access',
    helper: 'Use for access arranged outside Fresh Collective or for an administrative exception. No payment will be recorded.',
  },
]

interface CentralPaymentOptionSummary {
  id: string
  name: string
  status: 'draft' | 'published' | 'archived'
  purchasability: string
  grants: {
    grant_kind: 'pathway' | 'event_series' | 'gathering'
    target: { title: string } | null
    sessions_per_week: number | null
    total_sessions: number | null
  }[]
  schedules: {
    id: string
    name: string
    schedule_type: 'pay_in_full' | 'recurring_installments' | 'manual'
    status: 'draft' | 'published' | 'archived'
    total_amount_cents: number | null
    currency: string
  }[]
}

function GrantPassModal({ spaceSlug, onClose, onGranted, initialMember }: {
  spaceSlug: string
  onClose: () => void
  onGranted: () => void
  /** Optional preselected member — used by the post-cancellation
   *  "Grant replacement access →" flow so the Creator doesn't have
   *  to search for the same person again. */
  initialMember?: CreatorMemberDetail | null
}) {
  const [members, setMembers] = useState<CreatorMemberDetail[]>([])
  const [memberSearch, setMemberSearch] = useState('')
  const [selectedMember, setSelectedMember] = useState<CreatorMemberDetail | null>(
    initialMember ?? null,
  )
  const [options, setOptions] = useState<CentralPaymentOptionSummary[]>([])
  const [selectedOptionId, setSelectedOptionId] = useState('')
  const [source, setSource] = useState('complimentary')
  const [notes, setNotes] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  useEffect(() => {
    Promise.all([
      fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/members`), { credentials: 'include' })
        .then(r => r.ok ? r.json() : []),
      fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/commerce/payment-options`), { credentials: 'include' })
        .then(r => r.ok ? r.json() : []),
    ]).then(([membersData, optsData]: [CreatorMemberDetail[], CentralPaymentOptionSummary[]]) => {
      setMembers(membersData)
      // Manual-grant only offers currently-usable Payment Options —
      // drafts / archives / needs-attention are hidden so the
      // Creator can't grant access to a broken bundle.
      setOptions(optsData.filter(o => o.status !== 'archived'))
    }).catch(() => {})
  }, [spaceSlug])

  const selectedOption = options.find(o => o.id === selectedOptionId) ?? null

  const filteredMembers = memberSearch.trim()
    ? members.filter(m =>
        m.display_name.toLowerCase().includes(memberSearch.toLowerCase()) ||
        m.email.toLowerCase().includes(memberSearch.toLowerCase())
      ).slice(0, 6)
    : []

  async function handleSubmit() {
    if (!selectedMember) { setError('Select a member.'); return }
    if (!selectedOptionId) { setError('Select a Payment Option.'); return }
    setError(null)
    setLoading(true)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/commerce/manual-grant`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            user_id: selectedMember.id,
            payment_option_id: selectedOptionId,
            source,
            notes: notes.trim() || null,
          }),
        },
      )
      if (res.ok) { setSuccess(true); onGranted() }
      else {
        const body = await res.json().catch(() => ({}))
        setError(typeof body.detail === 'string' ? body.detail : 'Could not grant access.')
      }
    } catch { setError('Something went wrong. Please try again.') }
    finally { setLoading(false) }
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-2xl bg-white p-6 shadow-xl overflow-y-auto max-h-[90vh]">
        {success ? (
          <div className="py-4 text-center">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full text-xl"
              style={{ background: 'rgba(56,160,158,0.12)', color: '#38A09E' }}>✓</div>
            <p className="text-[16px] font-semibold text-navy-900">Access granted</p>
            <p className="mt-1 text-[13px] text-black">
              {selectedMember?.display_name} now has active access.
            </p>
            <button onClick={onClose} className="mt-4 rounded-xl px-5 py-2.5 text-[13px] font-semibold text-white" style={{ background: '#38A09E' }}>Done</button>
          </div>
        ) : (
          <>
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-[17px] font-semibold text-navy-900">Grant access</h2>
              <button onClick={onClose} className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 hover:bg-slate-100">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M1 1l10 10M11 1L1 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
              </button>
            </div>

            <div className="space-y-4">
              {/* Member search */}
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-black">Member</label>
                {selectedMember ? (
                  <div className="flex items-center justify-between rounded-xl border border-teal-200 bg-teal-50/40 px-3 py-2">
                    <div>
                      <p className="text-[13px] font-semibold text-navy-900">{selectedMember.display_name}</p>
                      <p className="text-[11px] text-black">{selectedMember.email}</p>
                    </div>
                    <button onClick={() => { setSelectedMember(null); setMemberSearch('') }}
                      className="text-[11px] text-black hover:text-slate-600">Change</button>
                  </div>
                ) : (
                  <div className="relative">
                    <input
                      type="text"
                      value={memberSearch}
                      onChange={e => setMemberSearch(e.target.value)}
                      placeholder="Search by name or email…"
                      className="w-full rounded-xl border border-slate-200 px-3 py-2 text-[13px] text-navy-900 placeholder-slate-300 focus:outline-none focus:ring-2 focus:ring-teal-400"
                    />
                    {filteredMembers.length > 0 && (
                      <ul className="absolute z-10 mt-1 w-full rounded-xl border border-slate-200 bg-white shadow-lg">
                        {filteredMembers.map(m => (
                          <li key={m.id}>
                            <button
                              type="button"
                              onClick={() => { setSelectedMember(m); setMemberSearch('') }}
                              className="w-full px-3 py-2.5 text-left hover:bg-teal-50/60 first:rounded-t-xl last:rounded-b-xl"
                            >
                              <p className="text-[13px] font-medium text-navy-900">{m.display_name}</p>
                              <p className="text-[11px] text-black">{m.email}</p>
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                    {memberSearch.trim() && filteredMembers.length === 0 && (
                      <p className="mt-1 text-[12px] text-black">No members found.</p>
                    )}
                  </div>
                )}
              </div>

              {/* Payment Option — Collective-scoped list; grants describe what's included */}
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-black">
                  Payment Option <span className="text-red-400">*</span>
                </label>
                {options.length > 0 ? (
                  <select value={selectedOptionId}
                    onChange={e => setSelectedOptionId(e.target.value)}
                    className="w-full rounded-xl border border-slate-200 px-3 py-2 text-[13px] text-navy-900 focus:outline-none focus:ring-2 focus:ring-teal-400">
                    <option value="">Choose a Payment Option…</option>
                    {options.map(o => (
                      <option key={o.id} value={o.id}>
                        {o.name}{o.status === 'draft' ? ' (Draft)' : ''}
                      </option>
                    ))}
                  </select>
                ) : (
                  <p className="text-[12px] text-amber-600">
                    No Payment Options yet. Create one in <strong>Commerce → Payment Options</strong>.
                  </p>
                )}

                {selectedOption && (
                  <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Includes</p>
                    <ul className="mt-1 space-y-0.5 text-[12.5px] text-navy-900">
                      {selectedOption.grants.length === 0 && (
                        <li className="italic text-slate-400">This Payment Option has no experiences configured yet.</li>
                      )}
                      {selectedOption.grants.map((g, i) => (
                        <li key={i}>
                          {g.target?.title ?? <em className="text-red-500">Missing target</em>}
                          {g.grant_kind === 'event_series' && (g.sessions_per_week || g.total_sessions) && (
                            <span className="ml-1 text-[11.5px] text-slate-500">
                              · {[
                                g.sessions_per_week != null ? `${g.sessions_per_week}/week` : null,
                                g.total_sessions != null ? `${g.total_sessions} total` : null,
                              ].filter(Boolean).join(' · ')}
                            </span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>

              {/* Reason — the only "how" the Creator picks. No amount,
                  no payment method, no schedule reference — Grant Access
                  is an access operation, not a payments workflow. */}
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

              {/* Notes */}
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-black">Notes (optional)</label>
                <textarea rows={2} value={notes} onChange={e => setNotes(e.target.value)}
                  placeholder="Scholarship, referral, special arrangement…"
                  className="w-full resize-none rounded-xl border border-slate-200 px-3 py-2 text-[13px] text-navy-900 placeholder-slate-300 focus:outline-none focus:ring-2 focus:ring-teal-400" />
              </div>

              {error && <p className="text-[12px] text-red-500">{error}</p>}

              <div className="flex gap-2 pt-1">
                <button onClick={handleSubmit} disabled={loading || !selectedMember || !selectedOptionId}
                  className="flex-1 rounded-xl py-2.5 text-[13px] font-semibold text-white disabled:opacity-50 disabled:cursor-not-allowed"
                  style={{ background: '#38A09E' }}>
                  {loading ? 'Granting…' : 'Grant access'}
                </button>
                <button onClick={onClose} className="rounded-xl px-4 py-2.5 text-[13px] font-medium text-black hover:bg-slate-50">Cancel</button>
              </div>
            </div>
          </>
        )}
      </div>
    </>
  )
}

export default function AccessClient({ passes, spaceName, spaceSlug, headerLocation, headerCoverImageUrl }: Props) {
  const router = useRouter()
  const [statusFilter, setStatusFilter] = useState<string>('active')
  const [showGrantModal, setShowGrantModal] = useState(false)
  const [grantKey, setGrantKey] = useState(0)
  const [correcting, setCorrecting] = useState<AccessPassAdminSummary | null>(null)
  // Optional preselected member for the Grant Access modal — used
  // by the post-cancellation "Grant replacement access" flow so the
  // Creator doesn't have to search for the same person twice.
  const [grantPreselectMember, setGrantPreselectMember] = useState<CreatorMemberDetail | null>(null)

  const filtered = statusFilter === 'all'
    ? passes
    : passes.filter(p => p.status === statusFilter)

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
      <CollectiveArtworkHeader
        collectiveName={spaceName}
        sectionTitle="Access"
        meta="See who has access, what they can use, and remaining Gathering allowances."
        location={headerLocation}
        coverImageUrl={headerCoverImageUrl}
        action={
          <Button
            variant="primary"
            size="md"
            iconStart={<PlusIcon />}
            onClick={() => setShowGrantModal(true)}
          >
            Grant access
          </Button>
        }
      />

      {/* Filters */}
      <div className="mb-5 flex flex-wrap gap-2">
        {(['active', 'expired', 'cancelled', 'all'] as const).map(f => (
          <button
            key={f}
            onClick={() => setStatusFilter(f)}
            className={`rounded-full border px-3 py-1 text-[12px] font-medium transition-colors ${
              statusFilter === f
                ? 'border-teal-500 bg-teal-50 text-teal-700'
                : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300'
            }`}
          >
            {f === 'all' ? 'All statuses' : STATUS_LABELS[f] ?? f}
          </button>
        ))}
        <span className="ml-auto text-[12px] text-black self-center">
          {filtered.length} access record{filtered.length === 1 ? '' : 's'}
        </span>
      </div>

      {/* Table */}
      {filtered.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-10 text-center">
          <p className="text-[15px] font-semibold text-navy-900">No access records found.</p>
          <p className="mt-1 text-[13px] text-black">
            Access is created when a member purchases a Payment Option — or when you grant one manually.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50">
                <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wide text-black">Member</th>
                <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wide text-black">Access</th>
                <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wide text-black">Source</th>
                <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wide text-black">Status</th>
                <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wide text-black">Valid</th>
                <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wide text-black">Gathering allowance</th>
                <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wide text-black">Bookings (30d)</th>
                <th className="px-3 py-3" aria-label="Actions" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {filtered.map(pass => {
                // "Access" cell — prefer the Payment Option's included
                // items list (from grants) when we have it; falls back
                // to the legacy option_name / pathway_title for
                // pre-U1 rows.
                const includedItems = (pass.option_included_items && pass.option_included_items.length > 0)
                  ? pass.option_included_items
                  : (pass.pathway_title ? [pass.pathway_title] : [])
                // Series-bound pass with allowance? Only show
                // credit metrics when they're meaningful — a
                // pathway-only pass never has session credits, so
                // we render "—" rather than a confusing zero bar.
                const hasSeriesAllowance = pass.eligible_series_id != null && pass.total_credits != null
                const perWeek = pass.credits_per_week
                return (
                  <tr key={pass.id} className="hover:bg-slate-50/50 transition-colors align-top">
                    <td className="px-4 py-3.5">
                      <p className="text-[13px] font-semibold text-navy-900">{pass.member_name ?? '—'}</p>
                      <p className="text-[12px] text-black">{pass.member_email ?? ''}</p>
                    </td>
                    <td className="px-4 py-3.5">
                      <p className="text-[13px] font-semibold text-navy-900">
                        {pass.option_name ?? PASS_TYPE_LABELS[pass.pass_type] ?? pass.pass_type}
                      </p>
                      {includedItems.length > 0 && (
                        <ul className="mt-0.5 space-y-0.5">
                          {includedItems.map((title, i) => (
                            <li key={i} className="text-[11.5px] text-slate-600">· {title}</li>
                          ))}
                        </ul>
                      )}
                    </td>
                    <td className="px-4 py-3.5">
                      <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider text-slate-600">
                        {formatSource(pass.access_source)}
                      </span>
                    </td>
                    <td className="px-4 py-3.5">
                      <span
                        className={`inline-block rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${STATUS_COLOURS[pass.status] ?? 'bg-slate-100 text-slate-500'}`}
                      >
                        {STATUS_LABELS[pass.status] ?? pass.status}
                      </span>
                    </td>
                    <td className="px-4 py-3.5">
                      <p className="text-[12px] text-navy-900">{formatDate(pass.valid_from)}</p>
                      {pass.valid_until && (
                        <p className="text-[11px] text-black">→ {formatDate(pass.valid_until)}</p>
                      )}
                    </td>
                    <td className="px-4 py-3.5">
                      {hasSeriesAllowance ? (
                        <div>
                          {perWeek != null && (
                            <p className="text-[12px] text-navy-900">{perWeek}/week</p>
                          )}
                          <div className="mt-0.5">
                            <CreditBar used={pass.used_credits} total={pass.total_credits} />
                          </div>
                        </div>
                      ) : perWeek != null ? (
                        <p className="text-[12px] text-navy-900">{perWeek}/week</p>
                      ) : (
                        <span className="text-[12px] text-slate-400">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3.5">
                      {hasSeriesAllowance ? (
                        <>
                          <span className="text-[13px] font-semibold text-navy-900">{pass.recent_bookings}</span>
                          <span className="text-[12px] text-black"> / {pass.total_bookings} total</span>
                        </>
                      ) : (
                        <span className="text-[12px] text-slate-400">—</span>
                      )}
                    </td>
                    <td className="px-3 py-3.5 text-right">
                      {isCorrectable(pass) && (
                        <button
                          type="button"
                          onClick={() => setCorrecting(pass)}
                          className="rounded-full border border-slate-200 px-2.5 py-1 text-[11px] font-medium text-slate-600 transition-colors hover:border-teal-200 hover:text-teal-700"
                          title="Correct this manual grant"
                        >
                          Correct
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {correcting && (
        <CorrectManualGrantModal
          spaceSlug={spaceSlug}
          pass={correcting}
          onClose={() => setCorrecting(null)}
          onSaved={() => {
            setCorrecting(null)
            // Re-fetch server-rendered ledger — this pass came from
            // the server component, so refresh() is the honest path
            // rather than mutating client state.
            router.refresh()
          }}
          onCancelled={() => {
            // Preselect this member so the Creator can immediately
            // grant replacement access without searching again. The
            // ledger row carries the real ``user_id`` since the U1
            // enrichment pass, so this is a genuine preselection —
            // not a search-string prefill.
            const member: CreatorMemberDetail | null = correcting.user_id
              ? ({
                  id: correcting.user_id,
                  display_name: correcting.member_name ?? correcting.member_email ?? 'Member',
                  email: correcting.member_email ?? '',
                } as CreatorMemberDetail)
              : null
            setCorrecting(null)
            setGrantPreselectMember(member)
            setShowGrantModal(true)
          }}
        />
      )}

      {showGrantModal && (
        <GrantPassModal
          key={grantKey}
          spaceSlug={spaceSlug}
          initialMember={grantPreselectMember}
          onClose={() => {
            setShowGrantModal(false)
            setGrantPreselectMember(null)
          }}
          onGranted={() => {
            setShowGrantModal(false)
            setGrantPreselectMember(null)
            setGrantKey(k => k + 1)
            router.refresh()
          }}
        />
      )}
    </div>
  )
}
