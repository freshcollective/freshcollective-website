import Link from 'next/link'
import { notFound } from 'next/navigation'
import type { Metadata } from 'next'
import { getSpace } from '@/lib/serverApi'
import { resolveMediaUrl } from '@/lib/api'
import type { SpaceResponse } from '@/types/platform'
import {
  atmosphereWords,
  collectiveAboutHref,
  islandHeading,
  islandPalette,
  islandStoryParagraphs,
  islandTagline,
} from '@/lib/islandPage'

/**
 * The island a Collective lives on, for its members.
 *
 * Read-only. Every field comes from where it already lives — the
 * Location row curated in World Management, the Collective's own
 * atmosphere words, the Collective's chosen Colour Palette — so
 * changing the island in Place and Feel changes this page on the next
 * load, with nothing to duplicate or re-author. See
 * ``lib/islandPage``.
 *
 * Access is inherited rather than invented. The page sits inside the
 * ``[slug]`` layout, so the same rules that guard every other
 * Collective page guard this one: a public Collective opens for
 * anybody, a private one sends a signed-out visitor to log in and
 * returns them here, and a Collective that does not resolve is
 * indistinguishable from one that does not exist. There is no new
 * endpoint and no new way to enumerate anything.
 *
 * The one large image is the island's own artwork. The creator's
 * uploaded banner is deliberately not used here — that banner is the
 * Collective's branding, and this page is about the place the
 * Collective chose. No other imagery, no patterns, no illustration:
 * the artwork is the centrepiece.
 */

interface Props {
  params: Promise<{ slug: string }>
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params
  const space = await getSpace(slug) as SpaceResponse | null
  const island = space?.location
  if (!space || !island?.name) {
    // Unreachable, private to this viewer, or islandless — one answer,
    // and it names nothing.
    return { title: 'Island · Fresh Collective', robots: { index: false, follow: false } }
  }
  return {
    title: `${island.name} · ${space.name} · Fresh Collective`,
    description: island.description ?? undefined,
    // Follows the Collective. A private Collective's island is not
    // something to put in an index.
    robots: space.is_public ? undefined : { index: false, follow: false },
  }
}

export default async function CollectiveIslandPage({ params }: Props) {
  const { slug } = await params
  const space = await getSpace(slug) as SpaceResponse | null

  // Deliberately no public-About fallback. That payload is an
  // allowlisted shim for a Collective that is discoverable yet private
  // — it carries a Location name and artwork but no story, atmosphere
  // or palette, so there would be nothing to tell. Rather than show an
  // empty island, those Collectives simply have no island page for an
  // anonymous visitor, and the About card does not offer a link.
  if (!space) notFound()

  const island = space.location ?? null
  // A Collective with no Location assigned has no island to explore.
  // 404 rather than an empty page: the route is about a place, and
  // there isn't one.
  if (!island?.name) notFound()

  const artwork = resolveMediaUrl(
    island.hero_artwork_url ?? island.thumbnail_artwork_url ?? undefined,
  )
  const story = islandStoryParagraphs(island.atlas_entry, island.description)
  const tagline = islandTagline(island.description, island.atlas_entry)
  const heading = islandHeading(space.name, island.name)
  const colours = islandPalette(space.colour_palette ?? null)
  const feelings = atmosphereWords(space.atmosphere_labels)
  const backHref = collectiveAboutHref(slug)

  return (
    <div className="px-5 py-8 sm:px-8 sm:py-10">
      <div className="mx-auto max-w-3xl">

        {/* ── Breadcrumb ── */}
        <nav aria-label="Breadcrumb" className="mb-5">
          <ol className="flex flex-wrap items-center gap-1.5 text-[13px]">
            <li>
              <Link
                href={backHref}
                className="text-black underline-offset-2 transition-colors hover:text-teal-700 hover:underline"
              >
                {space.name}
              </Link>
            </li>
            <li aria-hidden="true" className="text-slate-400">&rsaquo;</li>
            <li aria-current="page" className="text-slate-500">{island.name}</li>
          </ol>
        </nav>

        {/* ── Heading card ──
            The navy plate Explore Collectives uses, built here rather
            than through ``PageHero``: that primitive documents itself
            as deliberately not for ``/spaces/[slug]/*``, and it takes
            no introductory label.

            The label is sentence case and white, not small uppercase
            teal — that treatment is banned platform-wide (see
            CLAUDE.md), and this is the one place the brief's mockup
            asked for it. Flagged in the report. */}
        <header
          className="overflow-hidden rounded-2xl px-7 py-8 sm:px-9 sm:py-10"
          style={{
            background: '#071824',
            border: '1px solid rgba(56,160,158,0.22)',
            boxShadow:
              '0 0 0 1px rgba(56,160,158,0.08), 0 8px 32px rgba(7,24,36,0.18)',
          }}
        >
          <div
            className="mb-5 h-[2px] w-8 rounded-full"
            style={{
              background:
                'linear-gradient(90deg, #38A09E 0%, rgba(56,160,158,0.2) 100%)',
            }}
            aria-hidden="true"
          />
          {/* One sentence, so the page introduces the location as
              *this* Collective's chosen home rather than as a generic
              island. The separate "Your island" label is gone — the
              heading says it.

              The emoji leads the line rather than sitting mid-clause:
              Atlas Locations carry their icon inside ``name`` ("🌿
              Sanctuary Springs"), which is right for a label and
              wrong inside a sentence. Split by ``islandHeading``, and
              hidden from assistive technology — "seedling EMBODY's
              island is…" is worse than the sentence alone.

              Colour set inline, not with ``text-white``: globals.css
              carries an unlayered ``h1…h6 { color: navy-950 }`` rule
              that beats the utility, so the class would have rendered
              this heading navy on a navy card — invisible. There is a
              project-wide test for exactly this, and it caught it.

              ``text-balance`` evens the line lengths rather than
              leaving one word stranded, and ``max-w`` keeps the
              sentence from running the full width of a desktop card. */}
          <h1
            className="max-w-2xl text-balance font-serif text-[28px] leading-tight sm:text-[34px]"
            style={{ color: '#FFFFFF' }}
          >
            {heading.emoji && (
              <span aria-hidden="true">{heading.emoji}{' '}</span>
            )}
            {heading.sentence}
          </h1>
          {tagline && (
            <p
              className="mt-3 max-w-xl font-serif text-[15px] italic leading-relaxed sm:text-[16px]"
              style={{ color: 'rgba(255,255,255,0.82)' }}
            >
              {tagline}
            </p>
          )}
        </header>

        {/* ── The island's own artwork ──
            The one large image on the page. ``object-cover`` at a wide
            ratio so a landscape painting keeps its composition and is
            never stretched. */}
        {artwork && (
          <div
            className="mt-6 overflow-hidden rounded-2xl"
            style={{ border: '1px solid rgba(12,24,38,0.08)' }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={artwork}
              alt={`${island.name}`}
              className="block h-full w-full object-cover"
              style={{ aspectRatio: '16 / 9' }}
              loading="lazy"
              decoding="async"
            />
          </div>
        )}

        {/* ── About this island ── */}
        {story.length > 0 && (
          <section className="mt-10">
            <h2
              className="mb-4 text-[11px] font-semibold uppercase tracking-[0.16em]"
              // The Collective's own primary, deepened until it is
              // legible on this page — see ``islandPalette``. Never a
              // hardcoded teal.
              style={{ color: colours.headingColor }}
            >
              About this island
            </h2>
            {/* ~68ch, so a long atlas entry stays a comfortable read. */}
            <div className="max-w-[68ch] space-y-4">
              {story.map((paragraph, i) => (
                <p
                  key={i}
                  className="text-[15.5px] leading-[1.8] text-navy-900"
                >
                  {paragraph}
                </p>
              ))}
            </div>
          </section>
        )}

        {/* ── The feeling of this place ──
            The whole card wears the Collective's palette, so the same
            island looks like it belongs to whichever Collective you
            reached it through. No illustration, no pattern: the
            artwork above is the centrepiece. */}
        {feelings.length > 0 && (
          <section
            className="mt-10 rounded-2xl px-6 py-7 sm:px-8 sm:py-8"
            style={{ background: colours.cardBackground }}
          >
            <h2
              className="mb-5 text-[11px] font-semibold uppercase tracking-[0.16em]"
              style={{ color: colours.cardText, opacity: 0.82 }}
            >
              The feeling of this place
            </h2>
            <ul className="flex flex-wrap gap-2.5">
              {feelings.map((word) => (
                <li
                  key={word}
                  className="rounded-full border px-3.5 py-1.5 text-[13.5px] font-medium"
                  style={{
                    background: colours.pillBackground,
                    borderColor: colours.pillBorder,
                    color: colours.pillText,
                  }}
                >
                  {word}
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* ── Back to the Collective ── */}
        <div className="mt-10 flex justify-center">
          <Link
            href={backHref}
            className="rounded-full px-5 py-2.5 text-[14px] font-semibold transition-colors"
            style={{
              background: 'var(--fc-accent-soft, rgba(56,160,158,0.10))',
              color: 'var(--fc-accent, #0f766e)',
            }}
          >
            &larr; Back to {space.name}
          </Link>
        </div>

      </div>
    </div>
  )
}
