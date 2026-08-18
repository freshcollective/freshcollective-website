import { notFound } from 'next/navigation'
import Link from 'next/link'
import {
  getSpace,
  getSpaceGatheringSeriesDetail,
  getSpaceGatheringSeriesAboutBlocks,
  getSpaceGatheringSeriesPaymentOptions,
} from '@/lib/serverApi'
import { resolveMediaUrl } from '@/lib/api'
import type { CollectivePaletteMeta } from '@/lib/collectivePalette'
import { AboutBlockRenderer } from '@/components/spaces/AboutBlockRenderer'
import SeriesSchedule from './SeriesSchedule'
import { SidebarWaysToJoin, SidebarYourAccess } from './SeriesSidebar'
import { PlanRecoveryBanner } from '@/components/commerce/PlanRecoveryBanner'
import type { PathwayAboutBlock } from '@/types/platform'

/**
 * Member Gathering Series page (M1).
 *
 * Composes:
 *   * Hero — cover image + title + date range.
 *   * About — rich block content (falls back to the short
 *     description when no blocks are authored yet).
 *   * Your access / Ways to join — one branch based on whether
 *     the current viewer holds an active Series pass.
 *   * Gatherings in this Series — upcoming first, past
 *     collapsed at the bottom.
 *
 * Every data shape comes from the member-scoped endpoints in
 * ``backend/app/spaces/_series_member_routes.py``.
 */

interface Props {
  params: Promise<{ slug: string; 'series-slug': string }>
}

interface AccessSummary {
  has_access: boolean
  option_name: string | null
  valid_from: string | null
  valid_until: string | null
  gatherings_per_week: number | null
  gatherings_total: number | null
  gatherings_used: number | null
  gatherings_remaining: number | null
  used_this_week: number | null
}

interface SeriesGatheringSummary {
  id: string
  title: string
  starts_at: string
  ends_at: string | null
  location_type: string
  venue_name: string | null
  venue_locality: string | null
  attendance_format: string | null
  thumbnail_url: string | null
  booking_access_type: string
  capacity: number | null
  booked_count: number
  spots_remaining: number | null
  my_booking_status: string | null
  is_past: boolean
}

interface SeriesDetail {
  id: string
  slug: string
  title: string
  description: string | null
  cover_image_url: string | null
  starts_at: string
  ends_at: string | null
  total_gathering_count: number
  upcoming_gathering_count: number
  has_purchasable_options: boolean
  access: AccessSummary
  upcoming_gatherings: SeriesGatheringSummary[]
  past_gatherings: SeriesGatheringSummary[]
  member_plan_state?: import('@/types/platform').MemberPlanState | null
}

interface PaymentOptionScheduleOut {
  id: string
  name: string
  schedule_type: string
  total_amount_cents: number
  installment_amount_cents: number | null
  installment_count: number | null
  interval: string | null
  currency: string
  is_member_checkoutable: boolean
}

interface PaymentOptionOut {
  id: string
  name: string
  description: string | null
  allowance_per_week: number | null
  allowance_total: number | null
  included_titles: string[]
  schedules: PaymentOptionScheduleOut[]
  viewer_holds_this_option: boolean
}

function formatDateRange(startsAt: string, endsAt: string | null): string {
  const start = new Date(startsAt).toLocaleDateString('en-AU', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
  if (!endsAt) return `Starts ${start} · Ongoing`
  const end = new Date(endsAt).toLocaleDateString('en-AU', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
  return `${start} – ${end}`
}

export default async function MemberGatheringSeriesPage({ params }: Props) {
  const { slug, 'series-slug': seriesSlug } = await params

  const [detail, aboutBlocks, options, space]: [
    SeriesDetail | null,
    PathwayAboutBlock[],
    PaymentOptionOut[],
    { colour_palette?: CollectivePaletteMeta | null; timezone?: string | null } | null,
  ] = await Promise.all([
    getSpaceGatheringSeriesDetail(slug, seriesSlug),
    getSpaceGatheringSeriesAboutBlocks(slug, seriesSlug),
    getSpaceGatheringSeriesPaymentOptions(slug, seriesSlug),
    getSpace(slug),
  ])

  if (!detail) notFound()

  const collectivePalette: CollectivePaletteMeta | null = space?.colour_palette ?? null
  const coverUrl = resolveMediaUrl(detail.cover_image_url ?? undefined)
  const dateRange = formatDateRange(detail.starts_at, detail.ends_at)
  const hasAccess = detail.access.has_access

  return (
    <div className="mx-auto w-full max-w-[1100px] px-5 py-6 md:px-8 md:py-10">
      {/* Back to Gatherings */}
      <div className="mb-4">
        <Link
          href={`/spaces/${slug}/events`}
          className="inline-flex items-center gap-1.5 text-[12px] font-medium text-slate-500 transition-colors hover:text-slate-700"
        >
          <span aria-hidden="true">←</span>
          <span>Back to Gatherings</span>
        </Link>
      </div>

      {/* Hero — full-width above the two-column split.
          Over-image text is *always* white with a heavy layered
          overlay so a pale-logo cover (EMBODY), a scenic photo, or a
          dark stock image all read the same. Hero typography is
          deliberately not palette-tinted — the image supplies the
          colour, the overlay + white typography supply readability. */}
      <header className="mb-6 overflow-hidden rounded-2xl border border-border bg-white">
        {coverUrl ? (
          <div className="relative h-48 w-full md:h-64">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={coverUrl} alt="" className="h-full w-full object-cover" />
            <div
              aria-hidden="true"
              className="absolute inset-0"
              style={{
                // 5-stop gradient: near-opaque black under the text
                // block, thick coverage across the middle to tame busy
                // artwork, still lets the top ~10% of the image
                // breathe. Tested visually on light logo art (EMBODY),
                // scenic art, warm rust art (The Grove), and dark art.
                background:
                  'linear-gradient(to top, rgba(0,0,0,0.86) 0%, rgba(0,0,0,0.70) 22%, rgba(0,0,0,0.50) 46%, rgba(0,0,0,0.32) 72%, rgba(0,0,0,0.20) 100%)',
              }}
            />
            <div
              className="absolute inset-x-0 bottom-0 p-5 md:p-6"
              // Belt-and-braces text shadow — protects the title on
              // extreme edge cases (very high-frequency imagery right
              // under the words).
              style={{ textShadow: '0 1px 14px rgba(0,0,0,0.65)' }}
            >
              <p className="text-[11px] font-semibold uppercase tracking-wider text-white/90">
                {dateRange}
              </p>
              <h1 className="mt-1 font-serif text-2xl leading-tight text-white md:text-3xl">
                {detail.title}
              </h1>
            </div>
          </div>
        ) : (
          // No cover — plain card with neutral navy text. No palette
          // tint here either: the shell is Fresh Collective's, and
          // the palette rightly lives on the CTAs + sidebar below.
          <div className="p-6 md:p-8">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
              {dateRange}
            </p>
            <h1 className="mt-1 font-serif text-2xl leading-tight text-navy-900 md:text-3xl">
              {detail.title}
            </h1>
          </div>
        )}
      </header>

      {/*
        Two-column split (MF4).

        Source order — About · Sidebar · Schedule — is also the
        mobile order, so a member on a phone sees "how to join"
        before scrolling through the calendar. Grid placement
        promotes the sidebar to a sticky right rail on ≥lg while
        About + Schedule stack in the main column.
      */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_320px] lg:gap-8">
        {/* About — main column, row 1 */}
        <section className="lg:col-start-1 lg:row-start-1">
          {aboutBlocks.length > 0 ? (
            <div className="space-y-4">
              {aboutBlocks.map((b) => (
                <AboutBlockRenderer key={b.id} block={b} collectivePalette={collectivePalette} />
              ))}
            </div>
          ) : detail.description ? (
            <div className="rounded-2xl border border-border bg-white px-6 py-5">
              <p className="text-[15px] leading-relaxed text-black">{detail.description}</p>
            </div>
          ) : (
            <div className="rounded-2xl border border-dashed border-slate-200 bg-white px-6 py-8 text-center text-[13px] italic text-slate-500">
              More about this Series is coming soon.
            </div>
          )}
        </section>

        {/* Sidebar — sits between About and Schedule on mobile;
            sticky right-rail on desktop spanning both rows.

            FIP4B1 — the plan-recovery banner takes precedence over
            the standard ways-to-join CTA when the viewer already
            has a payment_problem/suspended plan for this Series
            (Rule D would refuse a duplicate purchase). For
            payment_problem, access is still live during grace so
            the access summary renders alongside the banner. */}
        <aside className="lg:col-start-2 lg:row-start-1 lg:row-end-3 lg:sticky lg:top-6 lg:self-start">
          {detail.member_plan_state && (
            <div className="mb-4">
              <PlanRecoveryBanner
                state={detail.member_plan_state}
                timezone={space?.timezone ?? null}
              />
            </div>
          )}
          {hasAccess ? (
            <SidebarYourAccess access={detail.access} palette={collectivePalette} />
          ) : detail.member_plan_state ? (
            /* Suspended member — banner already tells them what to
               do; do not add a fresh ways-to-join CTA. */
            null
          ) : (
            <SidebarWaysToJoin
              spaceSlug={slug}
              seriesSlug={seriesSlug}
              options={options}
              hasPurchasable={detail.has_purchasable_options}
              palette={collectivePalette}
            />
          )}
        </aside>

        {/* Schedule — main column, row 2 */}
        <div className="lg:col-start-1 lg:row-start-2">
          <SeriesSchedule
            spaceSlug={slug}
            upcoming={detail.upcoming_gatherings}
            past={detail.past_gatherings}
            memberHasSeriesAccess={hasAccess}
            palette={collectivePalette}
          />
        </div>
      </div>
    </div>
  )
}

