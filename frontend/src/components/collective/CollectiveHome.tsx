import Link from 'next/link'

import { readableOnWhite } from '@/lib/collectivePalette'
import { buildTiles } from '@/lib/collectiveHomeTiles'
import {
  tileFallbackBackground,
  tileImageUrl,
} from '@/lib/collectiveHomeArtwork'
import { ATLAS_CARD_STYLE, AtlasArtwork, AtlasCardBody } from './AtlasCard'
import type { SpaceResponse } from '@/types/platform'

/**
 * The member-facing Collective Home.
 *
 * A public Collective page answers "what is this and why would I
 * join". This answers the question a member has instead: "what can I
 * do in here". It is an orientation hub, not a feed — which is why a
 * real member area keeps its tile whether or not it is busy today.
 *
 * Every colour comes from the Collective's own palette through the
 * theme provider the layout above already mounts. Nothing here
 * introduces theme logic; it reads the ``--fc-accent*`` variables that
 * provider emits, so an un-themed Collective falls back to Fresh
 * Collective teal without a branch.
 *
 * The palette is applied at low intensity and in several places
 * rather than strongly in one — border, hover, focus ring, meta text,
 * the accent rule under the heading, and the fallback artwork. A card
 * washed in a single strong colour would fight the creator's own
 * photography; a card themed only at the CTA, which is what Phase 1
 * shipped, read as platform-default with a coloured word in the
 * corner.
 */

export default function CollectiveHome({
  space,
  platformArtwork,
}: {
  space: SpaceResponse
  /** ``(artworkKey) => url | null`` over the public platform artwork. */
  platformArtwork: (key: string) => string | null
}) {
  const tiles = buildTiles(space)
  const palette = space.colour_palette ?? null

  // Palette primaries are picked to look good as surfaces, and several
  // of them — Sunrise, Snow & Sky — sit under 3:1 on white. Text tinted
  // with the raw hex would be unreadable on those Collectives, so the
  // Home publishes a contrast-guaranteed shade of the same hue and the
  // card reads that in preference to the raw accent. Scoped here rather
  // than added to the provider: every other accent use on this page —
  // the rule, the fallback artwork, the border — wants the vivid
  // colour, and so do the surfaces outside this Home.
  const accentInk = palette?.palette?.primary
    ? readableOnWhite(palette.palette.primary)
    : null

  return (
    <div
      className="mx-auto w-full max-w-6xl px-6 py-10 md:px-10 md:py-14"
      style={accentInk ? ({ ['--fc-accent-ink' as string]: accentInk } as React.CSSProperties) : undefined}
    >
      <header className="mb-8 md:mb-10">
        <h1 className="font-serif text-[28px] leading-tight text-navy-900 md:text-[34px]">
          {space.name}
        </h1>
        {/* A short rule in the Collective's colour — the smallest
            possible signal that this page belongs to this place, set
            before any content. */}
        <div
          aria-hidden="true"
          className="mt-3 h-[3px] w-12 rounded-full"
          style={{ background: 'var(--fc-accent, #38A09E)' }}
        />
        {(space.identity_statement || space.tagline) && (
          <p
            className="mt-4 max-w-[620px] text-[15px] italic leading-relaxed"
            style={{ color: 'rgba(12, 24, 38, 0.65)', fontFamily: 'Georgia, serif' }}
          >
            {space.identity_statement || space.tagline}
          </p>
        )}
      </header>

      <ul className="grid list-none grid-cols-1 gap-6 p-0 sm:grid-cols-2 lg:grid-cols-3">
        {tiles.map((tile, index) => {
          const image = tileImageUrl(tile.key, tile.imageUrl, platformArtwork)
          return (
            <li key={tile.key}>
              <Link
                href={tile.href}
                className="group block h-full overflow-hidden rounded-2xl bg-white transition-all hover:-translate-y-0.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
                style={{
                  ...ATLAS_CARD_STYLE,
                  // Border and hover shadow in the Collective's colour
                  // at low alpha: present on every card, loud on none.
                  border: '1px solid var(--fc-accent-line, rgba(12,24,38,0.06))',
                  boxShadow: '0 6px 20px var(--fc-accent-tint, rgba(12,24,38,0.06))',
                  // Keyboard focus should look like it belongs to this
                  // Collective too, not to the platform.
                  ['--tw-ring-color' as string]: 'var(--fc-accent-ring, rgba(56,160,158,0.32))',
                }}
              >
                <AtlasArtwork
                  url={image}
                  // Each tile's gradient differs from its neighbours'
                  // and from the same tile in another Collective.
                  fallbackBg={tileFallbackBackground(tile.key, palette, space.slug)}
                  // Names the destination and the Collective, so a
                  // screen reader hears "Gatherings at EMBODY" rather
                  // than a filename or a bare repeated word.
                  alt={`${tile.name} at ${space.name}`}
                  // The first row is above the fold on every breakpoint.
                  priority={index < 3}
                />
                <AtlasCardBody
                  name={tile.name}
                  description={tile.description}
                  meta={tile.meta}
                  cta={tile.cta}
                  themeMeta
                />
              </Link>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
