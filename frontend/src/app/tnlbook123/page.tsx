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
 *  nesting a <button> inside an <a> would be invalid markup.
 *
 *  teal-700 rather than teal-600: white on teal-600 measures 4.37:1,
 *  a hair under AA for normal text. One step down the same scale
 *  clears it at 6.20:1 and reads no differently in context. */
const CTA =
  'inline-flex items-center justify-center gap-2 rounded-lg bg-teal-700 px-4 py-2.5 '
  + 'text-[14px] font-semibold text-white transition hover:bg-teal-800 '
  + 'focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 '
  + 'focus-visible:ring-offset-2'

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

/** One resource card. Children carry the control, because the audio
 *  card needs a player where the others need a link. */
function ResourceCard({
  title,
  description,
  children,
}: {
  title: string
  description: string
  children: React.ReactNode
}) {
  return (
    <Card className="flex h-full flex-col">
      <h3 className="mb-2 font-serif text-xl text-navy-900">{title}</h3>
      <p className="mb-5 text-[15px] leading-relaxed text-[#4A5568]">
        {description}
      </p>
      <div className="mt-auto">{children}</div>
    </Card>
  )
}

export default function NaturalLeaderBookCompanionPage() {
  return (
    <SiteShell>
      {/* ── Hero ───────────────────────────────────────────────────────
          The cover carries the visual character; the copy does the
          explaining. Stacks on mobile with the cover first, so a reader
          who followed a printed URL sees the book they are holding
          before any text. */}
      <section className="border-b border-border py-14 md:py-20">
        <Container>
          <div className="grid gap-10 md:grid-cols-[minmax(0,280px)_minmax(0,1fr)] md:items-center md:gap-14">
            <div className="mx-auto w-[200px] md:mx-0 md:w-full">
              <Image
                src={ASSETS.cover}
                alt="The Natural Leader by Lindsey Hilliard — front cover"
                width={1310}
                height={2048}
                priority
                sizes="(min-width: 768px) 280px, 200px"
                className="h-auto w-full rounded-xl"
                style={{ boxShadow: 'var(--fc-shadow-md, 0 8px 30px rgba(12,24,38,0.16))' }}
              />
            </div>
            <div>
              <h1 className="mb-5 font-serif text-4xl leading-tight text-navy-900 md:text-5xl">
                The Natural Leader Book Companion
              </h1>
              <p className="mb-5 text-lg leading-relaxed text-[#4A5568]">
                Everything you need to integrate your leadership design.
              </p>
              <p className="mb-5 text-lg leading-relaxed text-[#4A5568]">
                These free tools are designed to help you go deeper with what
                you&apos;re reading — so you don&apos;t just understand your
                design, you live it.
              </p>
              <p className="text-[15px] leading-relaxed text-[#5F6E7E]">
                Worth bookmarking — this page stays here, and you can come
                back to it as you read.
              </p>
            </div>
          </div>
        </Container>
      </section>

      {/* ── Resources ──────────────────────────────────────────────── */}
      <section className="py-14 md:py-20">
        <Container>
          <SectionHeading
            title="The Natural Leader Book Resources"
            className="mb-10"
          />
          <div className="grid gap-6 md:grid-cols-2">
            <ResourceCard
              title="Human Design Chart"
              description="Get a copy of your chart from here."
            >
              <Link href="/leadershipbodychart" className={CTA}>
                Get Chart
              </Link>
            </ResourceCard>

            <ResourceCard
              title="Gate / Gifts Summary"
              description="Download your PDF here."
            >
              <a href={ASSETS.gates} download className={CTA}>
                Download
              </a>
            </ResourceCard>

            <ResourceCard
              title="The Healing Vortex"
              description="Listen to the audio meditation here."
            >
              {/* ``preload="none"`` deliberately: the file is ~48MB, and
                  browsers that preload metadata would pull a slice of it
                  on every visit to this page for every visitor, most of
                  whom came for a PDF. It loads when someone presses
                  play. */}
              <audio
                controls
                preload="none"
                src={ASSETS.healingVortex}
                className="w-full"
              >
                Your browser cannot play audio inline.
              </audio>
              <a
                href={ASSETS.healingVortex}
                download
                className="mt-3 inline-block text-[14px] font-semibold text-teal-700 underline underline-offset-2 hover:text-teal-800"
              >
                Download the audio
              </a>
            </ResourceCard>

            <ResourceCard
              title="Feminine Archetypes"
              description="Download your PDF summary here."
            >
              <a href={ASSETS.feminineArchetypes} download className={CTA}>
                Download
              </a>
            </ResourceCard>

            <ResourceCard
              title="Prompts &amp; Practices"
              description="Download your journal prompts and embodiment practices here."
            >
              <a href={ASSETS.promptsAndPractices} download className={CTA}>
                Download
              </a>
            </ResourceCard>

            <ResourceCard
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
            </ResourceCard>
          </div>
        </Container>
      </section>

      {/* ── Reading list ───────────────────────────────────────────── */}
      <section className="border-t border-border py-14 md:py-20">
        <Container>
          <SectionHeading
            title="Other resources mentioned in the book"
            className="mb-10"
          />
          <h3 className="mb-5 text-[13px] font-semibold uppercase tracking-[0.14em] text-[#5F6E7E]">
            Books
          </h3>
          <ol className="grid gap-x-10 gap-y-4 md:grid-cols-2">
            {READING_LIST.map(({ title, author }, i) => (
              <li key={title} className="flex gap-3">
                <span
                  className="shrink-0 pt-0.5 text-[13px] font-semibold tabular-nums text-[#9AA7B6]"
                  aria-hidden="true"
                >
                  {i + 1}.
                </span>
                <span>
                  <span className="block text-[16px] leading-snug text-navy-900">
                    {title}
                  </span>
                  <span className="block text-[14px] leading-snug text-[#5F6E7E]">
                    {author}
                  </span>
                </span>
              </li>
            ))}
          </ol>
        </Container>
      </section>
    </SiteShell>
  )
}
