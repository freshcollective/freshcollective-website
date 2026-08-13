import Link from 'next/link'
import type { CreatorOfferPageSummary } from '@/types/platform'

/** Kept in sync with the same flag in ``OfferPagesShortcut.tsx``.
 *  See that file's comment for the re-enable checklist. */
const OFFER_PAGES_PAUSED = true

/**
 * Series-child Gathering → Offer Pages hint.
 *
 * Replaces the standalone Gathering's "Create Offer Page" shortcut
 * for Gatherings that belong to a Gathering Series. The primary
 * commercial destination for a Series member is the *Series* Offer
 * Page, not a separate page for a single session — so this card
 * always sends the Creator either to the Series' existing Offer
 * Page or to creating one, rather than encouraging duplication.
 *
 * Backend support for ``target_kind='gathering'`` is preserved for
 * genuinely standalone workshops / retreats / one-offs — this
 * component is a Creator-UI decision only, applied only when the
 * Gathering has a ``series_id``.
 *
 * States:
 *   - Series has an Offer Page  → link to that Offer Page's editor
 *   - Series has none yet       → primary "Create Series Offer Page"
 *     (deep-links to the New Offer Page wizard with
 *     ``target_kind=event_series`` preselected)
 *   - Multiple Series Offer Pages → link to the Series editor, which
 *     hosts the full 0 / 1 / many shortcut card
 *   - Community plan            → subtle "not on your plan" note
 */

interface Props {
  seriesId: string
  seriesTitle: string
  /** Slug of the parent Series — used to route back to the Series
   *  editor when the Series has multiple Offer Pages, or as the
   *  secondary "back to Series" link. */
  seriesSlug: string
  /** All Offer Pages for the Collective. Filtered here. */
  offers: CreatorOfferPageSummary[]
  paidOffersEnabled: boolean
}

export default function SeriesChildOfferHint({
  seriesId, seriesTitle, seriesSlug, offers, paidOffersEnabled,
}: Props) {
  // Offer Pages are intentionally on hold. Delete this early
  // return to re-enable — the implementation below is preserved
  // as-is.
  if (OFFER_PAGES_PAUSED) return null

  const seriesOffers = offers.filter(
    (o) => o.target_kind === 'event_series' && o.target_id === seriesId,
  )

  // ── Community plan — feature not available ──────────────────────────
  if (!paidOffersEnabled) {
    return (
      <div className="rounded-2xl border border-border bg-white p-4 md:p-5">
        <h2 className="text-[13px] font-semibold text-navy-900">Offer Page</h2>
        <p className="mt-1 text-[12.5px] text-black">
          This Gathering is part of {seriesTitle}. Offer Pages are
          available on Creator and up.{' '}
          <Link
            href="/creator-studio/billing"
            className="font-medium text-teal-700 hover:underline"
          >
            View plans
          </Link>
        </p>
      </div>
    )
  }

  // ── 0 Series Offer Pages — direct to create one ────────────────────
  if (seriesOffers.length === 0) {
    const createHref = `/creator-studio/offers?${new URLSearchParams({
      new: '1',
      target_kind: 'event_series',
      target_id: seriesId,
    }).toString()}`
    return (
      <div className="rounded-2xl border border-border bg-white p-4 md:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-[13px] font-semibold text-navy-900">Offer Page</h2>
            <p className="mt-1 max-w-lg text-[12.5px] text-black">
              This Gathering is part of {seriesTitle}. Rather than a
              separate page for a single session, create one Offer
              Page for the whole Series.
            </p>
          </div>
          <Link
            href={createHref}
            className="inline-flex items-center rounded-xl px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Create Series Offer Page
          </Link>
        </div>
      </div>
    )
  }

  // ── 1 Series Offer Page — link directly to its editor ─────────────
  if (seriesOffers.length === 1) {
    const only = seriesOffers[0]
    return (
      <div className="rounded-2xl border border-border bg-white p-4 md:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-[13px] font-semibold text-navy-900">Offer Page</h2>
            <p className="mt-1 max-w-lg text-[12.5px] text-black">
              This Gathering is part of {seriesTitle}. The Series
              Offer Page is the shared public invitation.
            </p>
          </div>
          <Link
            href={`/creator-studio/offers/${only.slug}`}
            className="inline-flex items-center rounded-xl border border-slate-200 px-4 py-2 text-[13px] font-medium text-slate-700 transition-colors hover:border-teal-300 hover:text-teal-700"
          >
            Edit Series Offer Page →
          </Link>
        </div>
      </div>
    )
  }

  // ── Multiple Series Offer Pages — send to the Series editor ────────
  return (
    <div className="rounded-2xl border border-border bg-white p-4 md:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-[13px] font-semibold text-navy-900">Offer Page</h2>
          <p className="mt-1 max-w-lg text-[12.5px] text-black">
            This Gathering is part of {seriesTitle}, which has{' '}
            {seriesOffers.length} Offer Pages. Manage them from the
            Series editor.
          </p>
        </div>
        <Link
          href={`/creator-studio/gathering-series/${seriesSlug}`}
          className="inline-flex items-center rounded-xl border border-slate-200 px-4 py-2 text-[13px] font-medium text-slate-700 transition-colors hover:border-teal-300 hover:text-teal-700"
        >
          Open Series editor →
        </Link>
      </div>
    </div>
  )
}
