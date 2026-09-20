import Link from 'next/link'

import { resolveMediaUrl } from '@/lib/api'
import { getCollectiveCoverStyle } from '@/lib/coverArt'
import { buildTiles } from '@/lib/collectiveHomeTiles'
import { ATLAS_CARD_STYLE, AtlasArtwork, AtlasCardBody } from './AtlasCard'
import type { SpaceResponse } from '@/types/platform'

/**
 * The member-facing Collective Home.
 *
 * A public Collective page answers "what is this and why would I
 * join". This answers the question a member has instead: "what can I
 * do in here". It is an orientation hub, not a feed — which is why a
 * real member area keeps its tile whether or not it is busy today. A
 * Collective whose Gatherings tile vanished between terms would read
 * as broken rather than quiet, and the member would have no route to
 * the archive. Only two things remove a tile: the platform already
 * treating that area as unavailable (the member directory can be
 * switched off), or the area not existing at all.
 *
 * Every colour comes from the Collective's own palette through
 * ``CollectiveThemeProvider``, already mounted by the layout above
 * this component. Nothing here introduces theme logic; it reads the
 * ``--fc-accent*`` variables that provider emits, so an un-themed
 * Collective falls back to Fresh Collective teal without a branch.
 */

/**
 * Artwork for a tile: the Collective's cover, then a gradient.
 *
 * No upload namespace is introduced in Phase 1, and a Collective that
 * has never touched its imagery still gets a Home that looks
 * deliberate — the gradient is derived from the slug, so it is stable
 * for that Collective forever rather than random per render.
 *
 * ``island_artwork_url`` is deliberately absent from this chain even
 * though it would fit. It is not on the member space payload today;
 * it is admin-only, and ``GET /api/spaces/{slug}`` answers anonymous
 * callers for public Collectives, so adding it would widen a public
 * response. That is a decision to take on its own merits, not a
 * side-effect of building a Home — and Phase 2's per-tile images
 * supersede the question anyway.
 */
function tileArtwork(space: SpaceResponse): string | null {
  return resolveMediaUrl(space.cover_image_url ?? undefined) ?? null
}

export default function CollectiveHome({ space }: { space: SpaceResponse }) {
  const tiles = buildTiles(space)
  const artwork = tileArtwork(space)
  const fallbackBg = getCollectiveCoverStyle(space.slug).background

  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-10 md:px-10 md:py-14">
      <header className="mb-8 md:mb-10">
        <h1 className="font-serif text-[28px] leading-tight text-navy-900 md:text-[34px]">
          {space.name}
        </h1>
        {(space.identity_statement || space.tagline) && (
          <p
            className="mt-3 max-w-[620px] text-[15px] italic leading-relaxed"
            style={{ color: 'rgba(12, 24, 38, 0.65)', fontFamily: 'Georgia, serif' }}
          >
            {space.identity_statement || space.tagline}
          </p>
        )}
      </header>

      <ul className="grid list-none grid-cols-1 gap-6 p-0 sm:grid-cols-2 lg:grid-cols-3">
        {tiles.map((tile, index) => (
          <li key={tile.key}>
            <Link
              href={tile.href}
              className="group block h-full overflow-hidden rounded-2xl bg-white transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
              style={{
                ...ATLAS_CARD_STYLE,
                // Focus ring in the Collective's own colour rather than
                // the platform teal, so keyboard navigation looks like
                // it belongs to this place too.
                ['--tw-ring-color' as string]: 'var(--fc-accent-ring, rgba(56,160,158,0.32))',
              }}
            >
              <AtlasArtwork
                url={artwork}
                fallbackBg={fallbackBg}
                // Names the destination and the Collective, so a screen
                // reader hears "Gatherings at EMBODY" rather than a
                // filename or a bare repeated word.
                alt={`${tile.name} at ${space.name}`}
                // The first row is above the fold on every breakpoint.
                priority={index < 3}
              />
              <AtlasCardBody
                name={tile.name}
                description={tile.description}
                meta={tile.meta}
                cta={tile.cta}
              />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
