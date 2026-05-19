import Link from 'next/link'
import PathwayCover from '@/components/ui/PathwayCover'
import {
  isPathwayLocked,
  accessBadgeLabel,
  formatPathwayPrice,
} from '@/lib/pathwayAccess'
import type { PathwaySummary } from '@/types/platform'

interface PathwayCardProps {
  pathway: PathwaySummary
  spaceSlug: string
}

const LockIcon = () => (
  <svg className="h-3.5 w-3.5 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5} aria-hidden="true">
    <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
  </svg>
)

export default function PathwayCard({ pathway, spaceSlug }: PathwayCardProps) {
  const isComingSoon = pathway.status === 'coming_soon'
  // TODO: Connect pathway purchase/access entitlement once checkout is wired.
  const locked = !isComingSoon && isPathwayLocked(pathway.access_type)
  const overviewHref = `/spaces/${spaceSlug}/pathways/${pathway.slug}`
  const aboutHref = `/spaces/${spaceSlug}/pathways/${pathway.slug}/about`

  const badgeLabel = accessBadgeLabel(pathway.access_type)
  const priceLabel = locked
    ? formatPathwayPrice(pathway.price_cents, pathway.currency, pathway.billing_interval)
    : null

  const baseClass = 'group flex flex-col overflow-hidden rounded-2xl border border-border bg-white'
  const hoverClass = 'shadow-sm transition-all hover:-translate-y-1 hover:shadow-lg hover:border-teal-200/60'
  const cardClass = `${baseClass} ${isComingSoon ? 'opacity-75' : hoverClass}`

  const descriptionEl = pathway.description ? (
    <p className="mb-4 flex-1 text-[13px] leading-relaxed text-slate-500 line-clamp-2">
      {pathway.description}
    </p>
  ) : <div className="flex-1" />

  // ── Coming soon: non-interactive card ──
  if (isComingSoon) {
    return (
      <div className={cardClass}>
        <PathwayCover slug={pathway.slug} title={pathway.title} coverImageUrl={pathway.cover_image_url} isComingSoon />
        <div className="flex flex-1 flex-col p-4">
          {descriptionEl}
          <div className="flex items-center border-t border-border pt-3">
            <span
              className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
              style={{ background: 'rgba(148,163,184,0.12)', color: '#64748B' }}
            >
              Coming soon
            </span>
          </div>
        </div>
      </div>
    )
  }

  // ── Locked: entire card links to About page (mini sales page) ──
  if (locked) {
    return (
      <Link href={aboutHref} className={cardClass}>
        <div className="relative">
          <PathwayCover slug={pathway.slug} title={pathway.title} coverImageUrl={pathway.cover_image_url} isComingSoon={false} />
          <div
            className="absolute right-3 top-3 flex h-7 w-7 items-center justify-center rounded-full shadow-sm"
            style={{ background: 'rgba(255,255,255,0.92)' }}
          >
            <LockIcon />
          </div>
        </div>
        <div className="flex flex-1 flex-col p-4">
          {descriptionEl}
          <div className="flex items-center justify-between border-t border-border pt-3">
            <div className="flex w-full items-center justify-between gap-3">
              {priceLabel && (
                <span
                  className="shrink-0 rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
                  style={{ background: 'rgba(7,24,36,0.07)', color: '#152236' }}
                >
                  {priceLabel}
                </span>
              )}
              <div className="ml-auto text-right">
                <span className="block text-[13px] font-semibold text-teal-700 transition-colors group-hover:text-teal-800">
                  Learn more →
                </span>
                <span className="block text-[10px] text-slate-400 mt-0.5">
                  Unlocking coming soon
                </span>
              </div>
            </div>
          </div>
        </div>
      </Link>
    )
  }

  // ── Accessible: stretched link for click-anywhere + secondary About link ──
  // The absolute <Link> covers the card (z-0); card content sits in z-10 layer.
  // Secondary links (About, Begin) are siblings of the stretched link — valid HTML.
  return (
    <div className={`${cardClass} relative`}>
      <Link
        href={overviewHref}
        className="absolute inset-0 z-0 rounded-2xl"
        tabIndex={-1}
        aria-hidden="true"
      />

      <div className="relative z-10">
        <PathwayCover slug={pathway.slug} title={pathway.title} coverImageUrl={pathway.cover_image_url} isComingSoon={false} />
      </div>

      <div className="relative z-10 flex flex-1 flex-col p-4">
        {descriptionEl}
        <div className="flex items-center justify-between border-t border-border pt-3">
          <div className="flex w-full items-center justify-between gap-3">
            {badgeLabel && (
              <span
                className="shrink-0 rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
                style={
                  badgeLabel === 'Free'
                    ? { background: 'rgba(16,185,129,0.10)', color: '#065F46' }
                    : { background: 'rgba(56,160,158,0.10)', color: '#073B3A' }
                }
              >
                {badgeLabel}
              </span>
            )}
            <div className="ml-auto flex items-center gap-3">
              <Link
                href={aboutHref}
                className="text-[11px] text-slate-400 transition-colors hover:text-teal-600"
              >
                About
              </Link>
              <Link
                href={overviewHref}
                className="text-[13px] font-semibold text-teal-700 transition-colors group-hover:text-teal-800"
              >
                Begin →
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
