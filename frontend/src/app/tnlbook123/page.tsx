/**
 * /tnlbook123 — preserved legacy URL (The Natural Leader Book Companion).
 *
 * This exact path may be printed in the book, so it must keep resolving
 * after freshcollective.au stops pointing at Wix. The URL is preserved;
 * the old Wix layout deliberately is not — this is built from the
 * current public shell and design primitives.
 *
 * Public and signed-out by design. A reader with the book in their hand
 * has no account and should not need one.
 *
 * The five companion files are ordinary static assets under
 * ``public/book-companion/``, served by Next. No API route, no database
 * row and no auth gate stands between a book owner and a PDF.
 *
 * Two sections of the old page are deliberately absent:
 *
 *   * the invitation to join The Natural Leader Hub — that programme is
 *     retired, and this page is not a sales surface;
 *   * the "resources are being gathered" placeholder this page carried
 *     at launch — the resources are here now.
 *
 * Visual language: the cover is deep indigo (#2D325A) with warm gold
 * line art, so the page borrows that pairing using Fresh Collective's
 * OWN navy and gold scales rather than importing the book's exact hues
 * as new tokens. The hero is a navy band carrying the cover; the
 * resource grid is warm off-white; the reading list sits on a warmer
 * band again. Three sections, three grounds, so scrolling has rhythm
 * without a second design system.
 *
 * Resource types are distinguished by GLYPH, not by colour — every
 * icon chip is the same gold-on-cream. Colour-coding six cards would
 * be the "busy" failure mode, and would also carry meaning that
 * colour alone cannot convey accessibly.
 */

import type { Metadata } from 'next'
import Image from 'next/image'
import Link from 'next/link'

import Card from '@/components/ui/Card'
import Container from '@/components/layout/Container'
import SectionHeading from '@/components/ui/SectionHeading'
import SiteShell from '@/components/layout/SiteShell'

export const metadata: Metadata = {
  title: 'The Natural Leader Book Companion · Fresh Collective',
  description:
    'Free companion resources for The Natural Leader by Lindsey Hilliard, '
    + 'including Human Design, journal prompts, embodiment practices and '
    + 'supporting resources.',
}

/** Static asset paths, served straight from ``public/``. */
const ASSETS = {
  cover: '/book-companion/natural-leader-front-cover.jpg',
  gates: '/book-companion/gates-summaries.pdf',
  healingVortex: '/book-companion/healing-vortex.mp3',
  feminineArchetypes: '/book-companion/feminine-archetypes.pdf',
  promptsAndPractices: '/book-companion/journal-prompts-and-somatic-practices.pdf',
} as const

const SPOTIFY_SHOW =
  'https://open.spotify.com/show/4K7nabojVkR6jhQpqqzSEq?si=2de56df555044123'

/** Shared CTA styling. A styled anchor rather than the Button
 *  component, because every one of these navigates or downloads —
 *  nesting a <button> inside an <a> would be invalid markup. */
// teal-700 rather than teal-600: white on teal-600 measures 4.37:1,
// which is just under AA for normal text. One step down the same scale
// clears it at 6.20:1 and looks no different in context.
const CTA =
  'inline-flex items-center justify-center gap-2 rounded-lg bg-teal-700 px-4 py-2.5 '
  + 'text-[14px] font-semibold text-white transition hover:bg-teal-800 '
  + 'focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 '
  + 'focus-visible:ring-offset-2'

/**
 * Resource glyphs. Inline SVG on the house convention (24-box,
 * ``currentColor``, 1.6 stroke) — this codebase has no icon package and
 * draws its handful of glyphs inline, so adding one would be a
 * dependency for four shapes.
 *
 * Four marks for four kinds of thing: a chart, a document, sound, a
 * broadcast. The chart glyph echoes the cover's radiating mandala.
 */
type Glyph = 'chart' | 'document' | 'audio' | 'podcast'

const GLYPH_PATHS: Record<Glyph, React.ReactNode> = {
  // Radiating spokes — a nod to the cover's lotus mandala.
  chart: (
    <>
      <circle cx="12" cy="12" r="2.6" />
      <path d="M12 2.4v5M12 16.6v5M2.4 12h5M16.6 12h5M5.2 5.2l3.5 3.5M15.3 15.3l3.5 3.5M18.8 5.2l-3.5 3.5M8.7 15.3l-3.5 3.5" />
    </>
  ),
  document: (
    <>
      <path d="M14 2.8H7.4A1.6 1.6 0 0 0 5.8 4.4v15.2a1.6 1.6 0 0 0 1.6 1.6h9.2a1.6 1.6 0 0 0 1.6-1.6V7.2z" />
      <path d="M14 2.8v4.4h4.2" />
      <path d="M12 11.4v5.4M9.6 14.4 12 16.8l2.4-2.4" />
    </>
  ),
  audio: (
    <>
      <path d="M4 10v4M8 7.2v9.6M12 4.6v14.8M16 7.8v8.4M20 10.4v3.2" />
    </>
  ),
  podcast: (
    <>
      <rect x="9.4" y="2.8" width="5.2" height="10" rx="2.6" />
      <path d="M5.8 11.2a6.2 6.2 0 0 0 12.4 0M12 17.4v3.8" />
    </>
  ),
}

function ResourceGlyph({ name }: { name: Glyph }) {
  return (
    <span
      aria-hidden="true"
      className="mb-5 inline-flex h-11 w-11 items-center justify-center rounded-full"
      style={{
        background: 'rgba(166,126,30,0.09)',
        border: '1px solid rgba(166,126,30,0.22)',
      }}
    >
      <svg
        width="20"
        height="20"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="text-gold-600"
      >
        {GLYPH_PATHS[name]}
      </svg>
    </span>
  )
}

/** Books named in The Natural Leader. Titles and authors only —
 *  no purchase or affiliate links. */
const READING_LIST: readonly { title: string; author: string }[] = [
  { title: 'Women Who Run With the Wolves', author: 'Clarissa Pinkola Estés' },
  {
    title: 'Burnout: The Secret to Unlocking the Stress Cycle',
    author: 'Emily Nagoski & Amelia Nagoski',
  },
  { title: 'The Patriarchy Stress Disorder', author: 'Dr Valerie Rein' },
  { title: 'Do Less', author: 'Kate Northrup' },
  { title: 'The Body Is Not an Apology', author: 'Sonya Renee Taylor' },
  { title: 'Untamed', author: 'Glennon Doyle' },
  {
    title: "Power: A Woman's Guide to Living and Leading Without Apology",
    author: 'Kemi Nekvapil',
  },
  { title: 'The Chalice and the Blade', author: 'Riane Eisler' },
  { title: 'Dare to Lead', author: 'Brené Brown' },
  { title: "My Grandmother's Hands", author: 'Resmaa Menakem' },
  { title: 'You Can Heal Your Life', author: 'Louise Hay' },
  { title: 'The Secret Language of Your Body', author: 'Inna Segal' },
]

/** One resource card — for the four things you take away with you.
 *  Warm ground and a gold hairline rather than a white box, so a page
 *  of six resources reads as a considered set rather than a file list. */
function ResourceCard({
  glyph,
  title,
  description,
  children,
}: {
  glyph: Glyph
  title: string
  description: string
  children: React.ReactNode
}) {
  return (
    <Card className="flex h-full flex-col border-[#E9E2D3] bg-[#FDFBF6]">
      <ResourceGlyph name={glyph} />
      <h3 className="mb-2 font-serif text-xl text-navy-900">{title}</h3>
      <p className="mb-6 text-[15px] leading-relaxed text-[#4A5568]">
        {description}
      </p>
      <div className="mt-auto">{children}</div>
    </Card>
  )
}

/** The two listening resources get a wide navy panel instead of a card.
 *
 *  Not decoration: it separates "things you take away" from "things you
 *  press play on", gives the audio element room to be usable rather
 *  than squeezed into a column, and sets up a pair / wide / pair / wide
 *  rhythm down the grid. The navy is the cover's, so the listening
 *  moments are where the page looks most like the book. */
function MediaPanel({
  glyph,
  title,
  description,
  children,
}: {
  glyph: Glyph
  title: string
  description: string
  children: React.ReactNode
}) {
  return (
    <div
      className="relative overflow-hidden rounded-xl px-6 py-7 md:col-span-2 md:px-9 md:py-9"
      style={{ background: 'linear-gradient(140deg, #0C1826 0%, #152236 60%, #1E3354 100%)' }}
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'radial-gradient(52% 80% at 88% 20%, rgba(212,176,72,0.16) 0%, rgba(212,176,72,0) 72%)',
        }}
      />
      <div className="relative md:flex md:items-center md:gap-10">
        <div className="md:max-w-[340px]">
          <span
            aria-hidden="true"
            className="mb-4 inline-flex h-11 w-11 items-center justify-center rounded-full"
            style={{
              background: 'rgba(212,176,72,0.12)',
              border: '1px solid rgba(212,176,72,0.32)',
            }}
          >
            <svg
              width="20" height="20" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="1.6"
              strokeLinecap="round" strokeLinejoin="round"
              className="text-gold-300"
            >
              {GLYPH_PATHS[glyph]}
            </svg>
          </span>
          <h3 className="mb-2 font-serif text-2xl text-white">{title}</h3>
          <p className="text-[15px] leading-relaxed text-navy-200">
            {description}
          </p>
        </div>
        <div className="mt-6 min-w-0 flex-1 md:mt-0">{children}</div>
      </div>
    </div>
  )
}

export default function NaturalLeaderBookCompanionPage() {
  return (
    <SiteShell>
      {/* ── Hero ───────────────────────────────────────────────────────
          A navy band rather than the pale expanse this page opened with.
          The cover is deep indigo and gold, so on white it sat in a lot
          of nothing; on navy it belongs to the page. Stacks on mobile
          with the cover first, so a reader who followed a printed URL
          sees the book they are holding before any text. */}
      <section
        className="relative overflow-hidden"
        style={{ background: 'linear-gradient(165deg, #0C1826 0%, #152236 58%, #1E3354 100%)' }}
      >
        {/* One soft gold bloom behind the cover, echoing the mandala.
            Decorative and aria-hidden; carries no meaning. */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              'radial-gradient(46% 60% at 24% 46%, rgba(212,176,72,0.20) 0%, rgba(212,176,72,0) 68%)',
          }}
        />
        <Container className="relative">
          <div className="grid gap-10 py-14 md:grid-cols-[minmax(0,268px)_minmax(0,1fr)] md:items-center md:gap-16 md:py-20">
            <div className="mx-auto w-[196px] md:mx-0 md:w-full">
              {/* Gold hairline frame — the cover's own line weight,
                  borrowed so the image is finished rather than floating. */}
              <div
                className="rounded-xl p-[3px]"
                style={{
                  background:
                    'linear-gradient(150deg, rgba(212,176,72,0.80) 0%, rgba(212,176,72,0.16) 58%, rgba(212,176,72,0.42) 100%)',
                  boxShadow: '0 18px 44px rgba(0,0,0,0.38)',
                }}
              >
                <Image
                  src={ASSETS.cover}
                  alt="The Natural Leader by Lindsey Hilliard — front cover"
                  width={1310}
                  height={2048}
                  priority
                  sizes="(min-width: 768px) 268px, 196px"
                  className="block h-auto w-full rounded-[10px]"
                />
              </div>
            </div>
            <div>
              <span
                aria-hidden="true"
                className="mb-5 block h-px w-10 bg-gold-300"
              />
              <h1 className="mb-5 font-serif text-4xl leading-tight text-white md:text-[3.25rem] md:leading-[1.1]">
                The Natural Leader Book Companion
              </h1>
              <p className="mb-5 font-serif text-xl leading-relaxed text-gold-300 md:text-2xl">
                Everything you need to integrate your leadership design.
              </p>
              <p className="mb-6 max-w-[54ch] text-lg leading-relaxed text-navy-200">
                These free tools are designed to help you go deeper with what
                you&apos;re reading — so you don&apos;t just understand your
                design, you live it.
              </p>
              <p className="text-[15px] leading-relaxed text-navy-300">
                Worth bookmarking — this page stays here, and you can come
                back to it as you read.
              </p>
            </div>
          </div>
        </Container>
      </section>

      {/* ── Resources ───────────────────────────────────────────────
          Warm off-white ground so the cards read as warm paper rather
          than white-on-white. Cards and panels alternate: take-away,
          take-away, listen, take-away, take-away, listen. */}
      <section className="bg-[#FBF8F2] py-14 md:py-20">
        <Container>
          <SectionHeading
            title="The Natural Leader Book Resources"
            className="mb-10 md:mb-12"
          />
          <div className="grid gap-6 md:grid-cols-2">
            <ResourceCard
              glyph="chart"
              title="Human Design Chart"
              description="Get a copy of your chart from here."
            >
              <Link href="/leadershipbodychart" className={CTA}>
                Get Chart
              </Link>
            </ResourceCard>

            <ResourceCard
              glyph="document"
              title="Gate / Gifts Summary"
              description="Download your PDF here."
            >
              <a href={ASSETS.gates} download className={CTA}>
                Download
              </a>
            </ResourceCard>

            <MediaPanel
              glyph="audio"
              title="The Healing Vortex"
              description="Listen to the audio meditation here."
            >
              {/* ``preload="none"`` deliberately: the file is ~48MB, and
                  browsers that preload metadata would pull a slice of it
                  on every visit to this page for every visitor, most of
                  whom came for a PDF. It loads when someone presses
                  play. */}
              <div
                className="rounded-lg p-3"
                style={{
                  background: 'rgba(255,255,255,0.07)',
                  border: '1px solid rgba(212,176,72,0.22)',
                }}
              >
                <audio
                  controls
                  preload="none"
                  src={ASSETS.healingVortex}
                  className="block w-full"
                >
                  Your browser cannot play audio inline.
                </audio>
              </div>
              <a
                href={ASSETS.healingVortex}
                download
                className="mt-3 inline-block text-[14px] font-semibold text-gold-300 underline underline-offset-4 transition hover:text-white"
              >
                Download the audio
              </a>
            </MediaPanel>

            <ResourceCard
              glyph="document"
              title="Feminine Archetypes"
              description="Download your PDF summary here."
            >
              <a href={ASSETS.feminineArchetypes} download className={CTA}>
                Download
              </a>
            </ResourceCard>

            <ResourceCard
              glyph="document"
              title="Prompts &amp; Practices"
              description="Download your journal prompts and embodiment practices here."
            >
              <a href={ASSETS.promptsAndPractices} download className={CTA}>
                Download
              </a>
            </ResourceCard>

            <MediaPanel
              glyph="podcast"
              title="The Natural Leader Podcast"
              description="Listen to the podcast here."
            >
              <a
                href={SPOTIFY_SHOW}
                target="_blank"
                rel="noopener noreferrer"
                className={CTA}
              >
                Listen on Spotify
              </a>
            </MediaPanel>
          </div>
        </Container>
      </section>

      {/* ── Reading list ────────────────────────────────────────────
          A curated shelf, not a paragraph of titles. Each entry sits on
          its own ruled line with a gold serif numeral, so the eye can
          run down the column the way it would down a contents page. */}
      <section className="border-t border-[#EDE6D8] bg-white py-14 md:py-20">
        <Container>
          <SectionHeading
            title="Other resources mentioned in the book"
            className="mb-10 md:mb-12"
          />
          <div
            className="rounded-2xl border border-[#EDE6D8] bg-[#FDFBF6] px-6 py-8 md:px-10 md:py-10"
          >
            <h3 className="mb-6 flex items-center gap-3 text-[12px] font-semibold uppercase tracking-[0.18em] text-gold-600">
              <span aria-hidden="true" className="h-px w-6 bg-gold-300" />
              Books
            </h3>
            <ol className="grid gap-x-12 md:grid-cols-2">
              {READING_LIST.map(({ title, author }, i) => (
                <li
                  key={title}
                  className="flex gap-4 border-b border-[#EDE6D8] py-3.5 last:border-b-0 md:[&:nth-last-child(2)]:border-b-0"
                >
                  <span
                    aria-hidden="true"
                    className="shrink-0 pt-0.5 font-serif text-[15px] tabular-nums text-gold-500"
                  >
                    {String(i + 1).padStart(2, '0')}
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[16px] leading-snug text-navy-900">
                      {title}
                    </span>
                    <span className="mt-0.5 block text-[14px] leading-snug text-[#5F6E7E]">
                      {author}
                    </span>
                  </span>
                </li>
              ))}
            </ol>
          </div>
        </Container>
      </section>
    </SiteShell>
  )
}
