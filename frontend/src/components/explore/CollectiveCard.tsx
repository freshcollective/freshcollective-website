'use client'

import Link from 'next/link'
import { getCollectiveCoverStyle } from '@/lib/coverArt'
import { resolveMediaUrl } from '@/lib/api'
import { formatCollectivePricingSummary } from '@/lib/pricing'
import type { SpaceWithMeta } from './spaceMeta'

/**
 * Explore-Collectives-style card for a single Collective.
 *
 * Extracted so both the Explore Collectives listing
 * (``/spaces``) and other pages that surface a filtered set of
 * Collectives — currently the Discover Places location detail page
 * (``/discover-places/[slug]``) — render Collectives with the same
 * visual identity.
 *
 * The card leads with the Collective's OWN artwork (Location artwork
 * first, then Space cover, then a deterministic gradient) so a
 * Collective always keeps its own visual identity regardless of the
 * surrounding page's framing.
 */
export default function CollectiveCard({
  space,
  isJoined,
}: {
  space: SpaceWithMeta
  isJoined: boolean
  /** Retained for API compatibility with the Explore surface — the
   *  card itself does not branch on it today. */
  isLoggedIn: boolean
}) {
  const cs = getCollectiveCoverStyle(space.slug)
  // Atlas v1.2 — prefer the collective's assigned Location artwork.
  // Fallback order: location thumbnail → location hero → space cover_image → placeholder.
  const resolvedImageUrl = resolveMediaUrl(
    space.location_thumbnail_artwork_url
      ?? space.location_hero_artwork_url
      ?? space.cover_image_url,
  )
  const hasImage = Boolean(resolvedImageUrl)
  const href = space.isReal
    ? (isJoined ? `/spaces/${space.slug}` : `/spaces/${space.slug}/about`)
    : '/signup'

  const titleColor = hasImage ? '#FFFFFF' : (cs.isDark ? '#FFFFFF' : '#152236')
  const taglineColor = hasImage
    ? '#FFFFFF'
    : cs.isDark
      ? '#FFFFFF'
      : '#000000'

  const ctaLabel = isJoined ? 'Continue →' : 'Explore →'
  const primaryTheme = space.themes[0] ?? null

  return (
    <div
      className="group flex h-full w-full min-w-0 flex-col overflow-hidden rounded-2xl bg-white transition-all hover:-translate-y-1 hover:shadow-lg"
      style={{
        border: '1px solid rgba(0,0,0,0.07)',
        boxShadow: '0 1px 3px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.05)',
      }}
    >
      {/* Cover area — fixed aspect ratio keeps all covers the same height */}
      <div className="relative w-full shrink-0 overflow-hidden" style={{ paddingBottom: '56.25%' }}>

        {/* CSS art layer */}
        {!hasImage && (
          <div
            className="absolute inset-0"
            style={{
              background: cs.background,
              backgroundSize: cs.backgroundSize ?? 'auto',
            }}
          />
        )}

        {/* Uploaded image */}
        {hasImage && (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={resolvedImageUrl!}
              alt={space.name}
              className="absolute inset-0 h-full w-full object-cover"
            />
            <div
              className="absolute inset-0"
              style={{
                background:
                  'linear-gradient(to top, rgba(7,24,36,0.72) 0%, rgba(7,24,36,0.18) 55%, transparent 80%)',
              }}
            />
          </>
        )}

        {/* Status badges — top-left */}
        <div className="absolute left-3 top-3 flex flex-wrap gap-1.5">
          {isJoined && (
            <span
              className="rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
              style={{ background: 'rgba(56,160,158,0.85)', color: '#FFFFFF' }}
            >
              Joined
            </span>
          )}
          {space.has_upcoming_event && (
            <span
              className="flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium"
              style={{ background: 'rgba(7,24,36,0.45)', color: '#FFFFFF' }}
            >
              <span className="h-1.5 w-1.5 rounded-full bg-teal-400" />
              Live soon
            </span>
          )}
        </div>

        {/* Name + tagline over cover */}
        <div className="absolute inset-x-0 bottom-0 p-4">
          <p className="font-serif text-[17px] leading-snug" style={{ color: titleColor }}>
            {space.name}
          </p>
          {space.tagline && (
            <p
              className="mt-0.5 line-clamp-1 text-[12px] leading-snug"
              style={{ color: taglineColor }}
            >
              {space.tagline}
            </p>
          )}
        </div>
      </div>

      {/* Card body — description preview; flex-1 pins footer to bottom regardless of content */}
      <div className="flex-1">
        {space.description && (
          <div className="px-4 pt-3">
            <p className="line-clamp-2 text-[12.5px] leading-[1.65] text-black">
              {space.description}
            </p>
          </div>
        )}
      </div>

      {/* Footer row */}
      <div
        className="mt-auto border-t px-4 py-3"
        style={{ borderColor: 'rgba(0,0,0,0.06)' }}
      >
        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-[11.5px] text-black">
            {primaryTheme && (
              <span
                className="rounded px-1.5 py-0.5 text-[10px] font-medium"
                style={{ background: `${space.accentColor}18`, color: space.accentColor }}
              >
                {primaryTheme}
              </span>
            )}
            {space.creator_name && (
              <span className="hidden sm:inline">
                by <span className="font-medium text-black">{space.creator_name}</span>
              </span>
            )}
            {space.pathway_count > 0 && (
              <span>{space.pathway_count} {space.pathway_count === 1 ? 'pathway' : 'pathways'}</span>
            )}
            {space.member_count > 0 && (
              <span className="hidden sm:inline">
                · {space.member_count} {space.member_count === 1 ? 'member' : 'members'}
              </span>
            )}
          </div>
          <Link
            href={href}
            className="shrink-0 text-[13px] font-semibold text-teal-700 transition-colors group-hover:text-teal-800"
          >
            {ctaLabel}
          </Link>
        </div>
        {/* Pricing pill */}
        <div className="mt-2">
          <span
            className="inline-flex items-center rounded-full border px-2 py-0.5 text-[10.5px] font-medium"
            style={{
              borderColor: 'rgba(0,0,0,0.08)',
              background: 'rgba(0,0,0,0.03)',
              color: '#475569',
            }}
          >
            {formatCollectivePricingSummary(space)}
          </span>
        </div>
      </div>
    </div>
  )
}
