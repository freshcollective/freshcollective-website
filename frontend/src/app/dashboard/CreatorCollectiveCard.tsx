'use client'

import { useRouter } from 'next/navigation'
import { resolveMediaUrl } from '@/lib/api'
import { getCollectiveCoverStyle } from '@/lib/coverArt'
import type { CreatorSpaceDetail, SpaceSummary } from '@/types/platform'
import { ATLAS_CARD_STYLE, AtlasArtwork, AtlasCardBody } from './AtlasCard'

/**
 * Dashboard card for a collective the current user owns.
 *
 * Uses the same artwork/body treatment as membership cards but adds a
 * status pill (Published / Draft) overlaid on the artwork and swaps the
 * CTA to a creator action. Clicks set the `fc_creator_space` cookie so
 * Creator Studio opens straight to this collective — same pattern as
 * CollectiveRow in Creator Studio.
 */

interface Props {
  summary: SpaceSummary
  detail: CreatorSpaceDetail | null
}

export default function CreatorCollectiveCard({ summary, detail }: Props) {
  const router = useRouter()

  const isPublished = summary.status === 'active'
  const cta = isPublished ? 'Open Creator Studio →' : 'Continue building →'
  const name = detail?.name ?? summary.name
  const tagline = detail?.tagline ?? summary.tagline ?? null

  // Location artwork first (identity), then legacy cover, then a slug-based
  // procedural gradient — same fallback chain used for membership cards.
  const loc = detail?.location
  const locationArt = resolveMediaUrl(
    loc?.thumbnail_artwork_url ?? loc?.hero_artwork_url ?? undefined,
  )
  const cover = resolveMediaUrl(detail?.cover_image_url ?? undefined)
  const artUrl = locationArt ?? cover
  const cs = getCollectiveCoverStyle(summary.slug)

  function open() {
    document.cookie = `fc_creator_space=${summary.slug}; path=/; max-age=86400`
    router.push('/creator-studio')
    // Force the /creator-studio layout tree to re-render on the
    // server against the new cookie so the palette provider, sidebar
    // "current collective" chrome, and every other server-derived
    // value pick up the switch. Without this refresh the Client
    // Router Cache serves the previously-rendered tree with the old
    // cookie in play. See CreatorStudioSidebar.switchTo for details.
    router.refresh()
  }

  return (
    <div
      role="link"
      tabIndex={0}
      onClick={open}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && open()}
      className="group block cursor-pointer overflow-hidden rounded-2xl bg-white transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
      style={ATLAS_CARD_STYLE}
    >
      <AtlasArtwork
        url={artUrl}
        fallbackBg={cs.background}
        alt={name}
        overlay={
          <span
            className="absolute right-3 top-3 rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
            style={
              isPublished
                ? {
                    background: 'rgba(56,160,158,0.10)',
                    color: '#38A09E',
                    backdropFilter: 'blur(6px)',
                    border: '1px solid rgba(56,160,158,0.22)',
                  }
                : {
                    background: 'rgba(255,255,255,0.92)',
                    color: '#b08d2a',
                    backdropFilter: 'blur(6px)',
                    border: '1px solid rgba(212,176,72,0.35)',
                  }
            }
          >
            {isPublished ? 'Published' : 'Draft'}
          </span>
        }
      />
      <AtlasCardBody name={name} description={tagline} meta="You created this" cta={cta} />
    </div>
  )
}
