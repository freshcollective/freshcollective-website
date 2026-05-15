import Link from 'next/link'
import PathwayCover from '@/components/ui/PathwayCover'
import {
  isPathwayLocked,
  accessBadgeLabel,
  unlockCtaLabel,
  formatPathwayPrice,
} from '@/lib/pathwayAccess'
import type { PathwaySummary } from '@/types/platform'

interface PathwayCardProps {
  pathway: PathwaySummary
  spaceSlug: string
}

export default function PathwayCard({ pathway, spaceSlug }: PathwayCardProps) {
  const isComingSoon = pathway.status === 'coming_soon'
  const locked = !isComingSoon && isPathwayLocked(pathway.access_type)
  const href = `/spaces/${spaceSlug}/pathways/${pathway.slug}`

  const badgeLabel = accessBadgeLabel(pathway.access_type)
  const priceLabel = locked
    ? formatPathwayPrice(pathway.price_cents, pathway.currency, pathway.billing_interval)
    : null
  const ctaUnlock = locked
    ? unlockCtaLabel(pathway.access_type, pathway.price_cents, pathway.currency, pathway.billing_interval)
    : null

  return (
    <div
      className={[
        'group flex flex-col overflow-hidden rounded-2xl border border-border bg-white',
        isComingSoon
          ? 'opacity-70'
          : locked
            ? 'shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md hover:border-slate-200'
            : 'shadow-sm transition-all hover:-translate-y-1 hover:shadow-lg hover:border-teal-200/60',
      ].join(' ')}
    >
      {/* Visual cover — with lock icon overlay when locked */}
      <div className="relative">
        <PathwayCover
          slug={pathway.slug}
          title={pathway.title}
          coverImageUrl={pathway.cover_image_url}
          isComingSoon={isComingSoon}
        />
        {locked && (
          <div className="absolute right-3 top-3 flex h-7 w-7 items-center justify-center rounded-full bg-white/90 shadow-sm">
            <svg
              className="h-3.5 w-3.5 text-slate-500"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2.5}
              aria-hidden="true"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
            </svg>
          </div>
        )}
      </div>

      {/* Card body */}
      <div className="flex flex-1 flex-col p-4">
        {pathway.description ? (
          <p className="mb-4 flex-1 text-[13px] leading-relaxed text-slate-500 line-clamp-2">
            {pathway.description}
          </p>
        ) : (
          <div className="flex-1" />
        )}

        <div className="flex items-center justify-between border-t border-border pt-3">
          {isComingSoon ? (
            <span className="text-[11px] text-slate-400">Coming soon</span>
          ) : locked ? (
            /* Locked state */
            <div className="flex w-full items-center justify-between gap-3">
              {priceLabel && (
                <span
                  className="shrink-0 rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
                  style={{ background: 'rgba(7,24,36,0.07)', color: '#152236' }}
                >
                  {priceLabel}
                </span>
              )}
              <div className="flex flex-col items-end gap-0.5 text-right">
                {/* TODO: Connect pathway purchase/access entitlement once checkout is wired. */}
                <button
                  disabled
                  className="text-[12px] font-semibold text-slate-400 cursor-not-allowed"
                  title="Payment access coming soon"
                >
                  {ctaUnlock}
                </button>
                <span className="text-[10px] text-slate-300">Coming soon</span>
              </div>
            </div>
          ) : (
            /* Accessible state */
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
              <Link
                href={href}
                className={[
                  'ml-auto text-[13px] font-semibold text-teal-700 transition-colors group-hover:text-teal-800',
                  !badgeLabel ? 'w-full' : '',
                ].join(' ')}
              >
                Begin →
              </Link>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
