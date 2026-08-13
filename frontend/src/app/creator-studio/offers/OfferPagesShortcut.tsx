import Link from 'next/link'
import type {
  CreatorOfferPageSummary,
  OfferPageStatus,
  OfferPageTargetKind,
} from '@/types/platform'

/** Set to ``false`` to re-enable Offer Page shortcuts across
 *  Pathway, Gathering Series and Gathering editors. Re-enabling
 *  should also update the sidebar's ``paused: true`` flag on the
 *  Offer Pages nav item and the same ``OFFER_PAGES_PAUSED`` guard
 *  in ``SeriesChildOfferHint.tsx``. */
const OFFER_PAGES_PAUSED = true

/**
 * Shared "Offer Pages" shortcut card.
 *
 * Rendered inside the editor for the *thing an Offer Page invites
 * people into* — a Pathway, a Gathering Series, or a single
 * Gathering. Never edits Offer Page content itself; every action
 * routes to the shared Offer Page editor so that editor stays the
 * single source of truth.
 *
 * States:
 *   - No Offer Page yet          → primary "Create Offer Page"
 *   - Exactly one Offer Page     → "Edit Offer Page" + status chip
 *   - Multiple Offer Pages       → compact list, one edit link per row
 *
 * Community-plan Creators see a subtle "not on your plan" note
 * rather than a create button, so the shortcut never dangles an
 * action that would 403.
 *
 * Deep-linking: Create links carry ``?new=1&target_kind=…&target_id=…``
 * so the New Offer Page modal opens with the target preselected and
 * only the title is left for the Creator to type.
 */

interface Props {
  /** Which kind of thing is this shortcut attached to? Drives labels
   *  and the deep-linked create query params. */
  targetKind: OfferPageTargetKind
  /** UUID of the Pathway / Series / Gathering the shortcut is
   *  attached to. Used to filter the space-wide offers list and to
   *  preselect the target in the New Offer Page flow. */
  targetId: string
  /** Optional — surfaces in the empty-state helper text, so the
   *  Creator sees which thing they'd be inviting people into. */
  targetTitle?: string
  /** All Offer Pages for the Collective. The shortcut filters. */
  offers: CreatorOfferPageSummary[]
  /** Server-computed plan gate. False → render an "upgrade" note. */
  paidOffersEnabled: boolean
  /** Slightly quieter visual treatment for shortcuts that shouldn't
   *  compete with the primary editor cards around them (e.g. the
   *  individual Gathering editor). */
  variant?: 'default' | 'compact'
}

const STATUS_LABEL: Record<OfferPageStatus, string> = {
  draft: 'Draft',
  published: 'Published',
  archived: 'Archived',
}

/** UI-facing label — never expose `event_series` to Creators. */
const KIND_LABEL: Record<OfferPageTargetKind, string> = {
  pathway: 'Pathway',
  event_series: 'Gathering Series',
  gathering: 'Gathering',
}

/** Second-person copy fragment used in the empty state. Not shown
 *  as a heading; folded into a sentence so the shortcut reads
 *  naturally in the surrounding editor. */
const KIND_HELPER: Record<OfferPageTargetKind, string> = {
  pathway: 'this Pathway',
  event_series: 'this Gathering Series',
  gathering: 'this Gathering',
}

function statusChipStyle(status: OfferPageStatus): React.CSSProperties {
  if (status === 'published') {
    return { background: 'rgba(56,160,158,0.10)', color: '#0f766e' }
  }
  if (status === 'archived') {
    return { background: 'rgba(12,24,38,0.06)', color: 'rgba(12,24,38,0.55)' }
  }
  return { background: 'rgba(214,177,63,0.14)', color: '#8a6a1f' }
}

/** URL for the New Offer Page flow, pre-configured for this target.
 *  The Offer Pages index reads these query params on mount and opens
 *  the New Offer Page modal with the kind + target locked in. */
function newOfferHref(targetKind: OfferPageTargetKind, targetId: string): string {
  const q = new URLSearchParams({
    new: '1',
    target_kind: targetKind,
    target_id: targetId,
  })
  return `/creator-studio/offers?${q.toString()}`
}

export default function OfferPagesShortcut({
  targetKind, targetId, targetTitle,
  offers, paidOffersEnabled, variant = 'default',
}: Props) {
  // Offer Pages are intentionally on hold — the Creator-facing
  // shortcuts on Pathway, Gathering Series, and Gathering editors
  // are hidden until the feature is re-enabled. Re-enable by
  // deleting this early return. The full implementation below is
  // preserved so re-enabling is a one-line revert; existing
  // Offer Page data, direct URLs, and backend endpoints remain
  // untouched for development / recovery.
  if (OFFER_PAGES_PAUSED) return null

  const own = offers.filter(
    (o) => o.target_kind === targetKind && o.target_id === targetId,
  )
  const label = KIND_LABEL[targetKind]
  const helper = KIND_HELPER[targetKind]

  const cardClass = variant === 'compact'
    ? 'rounded-2xl border border-border bg-white p-4 md:p-5'
    : 'rounded-2xl border border-border bg-white p-5 md:p-6'
  const heading = variant === 'compact'
    ? 'text-[13px] font-semibold text-navy-900'
    : 'text-[14px] font-semibold text-navy-900'

  // ── Community plan — feature not available ──────────────────────────
  if (!paidOffersEnabled) {
    return (
      <div className={cardClass}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className={heading}>Offer Page</h2>
            <p className="mt-1 text-[12.5px] text-black">
              Offer Pages are available on Creator and up.{' '}
              <Link
                href="/creator-studio/billing"
                className="font-medium text-teal-700 hover:underline"
              >
                View plans
              </Link>
            </p>
          </div>
        </div>
      </div>
    )
  }

  // ── 0 offers — encourage creating one ───────────────────────────────
  if (own.length === 0) {
    return (
      <div className={cardClass}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className={heading}>Offer Page</h2>
            <p className="mt-1 max-w-lg text-[12.5px] text-black">
              A beautiful public page you can share to invite people into{' '}
              {helper}
              {targetTitle ? ` — ${targetTitle}.` : '.'}
            </p>
          </div>
          <Link
            href={newOfferHref(targetKind, targetId)}
            className="inline-flex items-center rounded-xl px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Create Offer Page
          </Link>
        </div>
      </div>
    )
  }

  // ── 1 offer — direct edit link ──────────────────────────────────────
  if (own.length === 1) {
    const only = own[0]
    return (
      <div className={cardClass}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className={heading}>Offer Page</h2>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <p className="truncate text-[13.5px] text-black">{only.title}</p>
              <span
                className="rounded-full px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider"
                style={statusChipStyle(only.status)}
              >
                {STATUS_LABEL[only.status]}
              </span>
            </div>
          </div>
          <Link
            href={`/creator-studio/offers/${only.slug}`}
            className="inline-flex items-center rounded-xl border border-slate-200 px-4 py-2 text-[13px] font-medium text-slate-700 transition-colors hover:border-teal-300 hover:text-teal-700"
          >
            Edit Offer Page →
          </Link>
        </div>
        <p className="mt-3 text-[12px] text-slate-500">
          Need a different presentation for the same {label}?{' '}
          <Link
            href={newOfferHref(targetKind, targetId)}
            className="font-medium text-teal-700 hover:underline"
          >
            Create another
          </Link>
          .
        </p>
      </div>
    )
  }

  // ── Multiple offers — compact list ──────────────────────────────────
  return (
    <div className={cardClass}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className={heading}>Offer Pages</h2>
          <p className="mt-0.5 text-[12.5px] text-black">
            {own.length} pages presenting this {label}.
          </p>
        </div>
        <Link
          href={newOfferHref(targetKind, targetId)}
          className="text-[12.5px] font-medium text-teal-700 hover:underline"
        >
          Create another →
        </Link>
      </div>
      <ul className="divide-y divide-slate-100 rounded-xl border border-slate-100">
        {own.map((o) => (
          <li key={o.id}>
            <Link
              href={`/creator-studio/offers/${o.slug}`}
              className="flex items-center gap-3 px-4 py-2.5 text-[13.5px] transition-colors hover:bg-slate-50"
            >
              <span className="min-w-0 flex-1 truncate text-navy-900">{o.title}</span>
              <span
                className="shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider"
                style={statusChipStyle(o.status)}
              >
                {STATUS_LABEL[o.status]}
              </span>
              <span
                aria-hidden="true"
                className="shrink-0 text-[13px]"
                style={{ color: 'rgba(12,24,38,0.35)' }}
              >
                →
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
