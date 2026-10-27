import { Fragment } from 'react'
import type { Metadata } from 'next'
import Image from 'next/image'
import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import {
  HeroPrimaryCta,
  HeroSecondaryCta,
} from '@/components/marketing/heroCtaButtons'
import type { AboutSection } from '@/lib/aboutStory'
import {
  ABOUT_IMAGES,
  ABOUT_INTRO,
  ABOUT_INVITATION,
  ABOUT_PHOTOGRAPHER,
  ABOUT_PHOTOGRAPHER_URL,
  ABOUT_PHOTO_CREDIT_PREFIX,
  ABOUT_SECTIONS,
  ABOUT_SIGNATURE,
  ABOUT_TITLE_LINES,
  ABOUT_VIDEO_LABEL,
  ABOUT_VIDEO_URL,
  ABOUT_VISION,
} from '@/lib/aboutStory'

/**
 * /about — "Why Fresh Collective exists".
 *
 * A reading page, not a marketing page. Four movements: the fig-tree
 * photograph and the title, the story, the vision, and the invitation
 * beside the willow portrait.
 *
 * Everything here is borrowed. The chrome is ``SiteShell``, the width
 * is ``Container``, the two buttons are the shared hero CTA pair, the
 * heading scale and ink colours are the ones ``/for-creators`` already
 * uses, and the hero photograph is handled the way ``HomeHero`` handles
 * its own — ``next/image`` with ``fill``, ``priority`` and a reserved
 * aspect ratio. No new component library, font or design system, and
 * deliberately very few boxes: the story is the page, so it is set as
 * running text at a comfortable measure rather than one card per
 * paragraph.
 */

// The same tokens ``/for-creators`` declares, so the two pages read as
// one site. Copied rather than imported because that page keeps them
// private; a shared module for five colours would be a refactor of
// someone else's file, which is not what this change is for.
const TEAL_DEEP = '#246B6A'
const NAVY = '#0C1826'
const INK_SOFT = 'rgba(12, 24, 38, 0.66)'

/**
 * The reading column, and the body style inside it.
 *
 * Both are the homepage's, measured off the rendered page rather than
 * chosen: its widest editorial paragraph is **Georgia 17px / 1.8 /
 * -0.01em / rgba(12,24,38,0.82), 24px between paragraphs, 760px
 * wide**, and that is exactly what is set here. 816px at 19px was
 * close but not the same thing, and ran about five characters a line
 * longer than anything on the homepage.
 *
 * 760px keeps the wide column — it is still 40% wider than the 544px
 * this page started at — while putting the measure at the homepage's
 * own 79 characters instead of 84.
 */
const READING_COLUMN = 'mx-auto max-w-[760px]'

/**
 * Homepage editorial body, one step up in size.
 *
 * The homepage sets 17px/1.8; this runs 19px/1.75 because the story
 * is a long read rather than a paragraph between artwork, and at 17px
 * the 40px section headings were dominating the prose they introduce.
 * Family, tracking, colour and the 24px paragraph gap are the
 * homepage's unchanged — only the step, and the line height eased a
 * touch to keep the same visual rhythm at the larger size.
 */
const BODY_CLASS = 'font-serif text-[19px] leading-[1.75] tracking-[-0.01em]'
const BODY_INK = 'rgba(12, 24, 38, 0.82)'

/**
 * Homepage section heading: 600 weight sans, -0.03em, 1.06 line
 * height, full navy — all four straight off the rendered homepage.
 *
 * Only the size differs, and deliberately. The homepage sets 44px and
 * 40px for headings that introduce a whole region of the page; these
 * five run in sequence down one story, above body copy, and at 40px
 * they read as five announcements rather than five signposts. 35px
 * keeps the heading-to-body ratio close to the homepage's own.
 */
const HEADING_CLASS = 'font-sans font-semibold'
const HEADING_STYLE = {
  fontSize: 'clamp(1.7rem, 3.4vw, 2.2rem)',
  lineHeight: 1.06,
  letterSpacing: '-0.03em',
  color: NAVY,
} as const

const CANONICAL = '/about'

export const metadata: Metadata = {
  title: 'Why Fresh Collective Exists | Our Story',
  description:
    'Discover why Fresh Collective was created — a personal story about '
    + 'connection, collaboration, belonging and building a world where '
    + 'people can discover more through each other.',
  // Relative, resolved against ``metadataBase`` in the root layout —
  // the same arrangement every other canonical on the site uses.
  alternates: { canonical: CANONICAL },
  openGraph: {
    title: 'Why Fresh Collective Exists | Our Story',
    description:
      'A personal story about connection, collaboration and belonging — '
      + 'and why Fresh Collective was built.',
    url: CANONICAL,
    type: 'website',
    // The hero photograph. One image, already on the page, already
    // optimised by the same pipeline; nothing is generated for sharing.
    images: [{ url: ABOUT_IMAGES.hero.src, alt: ABOUT_IMAGES.hero.alt }],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Why Fresh Collective Exists | Our Story',
    description:
      'A personal story about connection, collaboration and belonging — '
      + 'and why Fresh Collective was built.',
    images: [ABOUT_IMAGES.hero.src],
  },
}

/**
 * How the fig tree is framed, width by width.
 *
 * The photograph is 2048 × 1536 — a 4:3 landscape with Linds and the
 * roots down the left and open lawn to the right, which is what lets
 * the title sit beside her rather than across her.
 *
 * Every frame here trims the top and bottom only; nothing is ever cut
 * off either side, so the open ground the title needs is always
 * there. The anchors were measured against the real file rather than
 * guessed. She stands low in the frame, so a centred crop takes her
 * feet off: at 16:9 the band has to sit near the bottom of the image
 * to keep her feet and the roots she is standing on in shot.
 *
 * Phones get 4:3 — the photograph entire, no crop at all, which is
 * the point at the width where it matters most.
 *
 * 21:9 was tried and abandoned. It is the proportion a hero usually
 * wants, but from a 4:3 original it leaves 57% of the height, and no
 * anchor fits both her head and her feet inside that band: one or the
 * other always goes. 16:9 keeps the whole figure with room to spare.
 *
 * Responsive, so set as a custom property rather than an inline
 * value — inline styles cannot carry a media query.
 */
const HERO_FRAME = 'aspect-[4/3] sm:aspect-[3/2] md:aspect-[16/9]'
const HERO_FOCUS =
  '[--about-hero-pos:50%_50%] '
  + 'sm:[--about-hero-pos:50%_62%] '
  + 'md:[--about-hero-pos:50%_76%]'

function Hero() {
  return (
    <Container className="pt-8 md:pt-12">
      {/*
        One heading block, two positions. Below ``md`` it is an
        ordinary block under the photograph; from ``md`` up it is
        absolutely positioned into the open right-hand side of the
        frame. The brief was explicit that on a phone the photograph
        matters more than getting the title on top of it, and single
        nodes mean the two can never disagree about the words.
      */}
      <div className="relative">
        <div
          data-about-frame="hero"
          className={`relative w-full overflow-hidden rounded-2xl ${HERO_FRAME}`}
          // A ground colour behind the photograph, so the reserved
          // space is a considered panel for the moment before it
          // decodes rather than a white hole. No layout shift either
          // way: the aspect ratio holds the height from first paint.
          style={{ background: '#13211C' }}
        >
          <Image
            src={ABOUT_IMAGES.hero.src}
            alt={ABOUT_IMAGES.hero.alt}
            fill
            priority
            sizes="(min-width: 1024px) 1152px, 100vw"
            className={HERO_FOCUS}
            // Deliberately no filters, no saturate(), no contrast() —
            // the photograph is the point and it is shown as taken.
            style={{ objectFit: 'cover', objectPosition: 'var(--about-hero-pos)' }}
          />
          {/*
            A directional wash: full strength down the right, where
            the headline is, and nothing at all on the left, where
            Linds, the trunk and the roots are. The photograph was
            chosen because it is warm and full of natural light, and
            an even overlay across the whole frame — which this was
            for one revision — spent that light to solve a problem
            that only exists on one side.

            Shaped as a **smoothstep**, sampled into ten stops. The
            first attempt at a directional wash fell from strength to
            nothing over four percent of the frame and put a visible
            edge straight down the middle of the picture. This one
            holds to 46% across and eases out by 62%, so the fall is
            four times longer, and the curve has no sudden change of
            slope at either end — a straight ramp does, and that kink
            is what the eye reads as a band.

            Measured against the actual pixels behind each line, and
            better than the even wash it replaces on every count:

                              gold    white    photo   on Linds
              even 0.54       2.32     4.01    0.091      0.54
              this            3.04     5.26    0.152      0.10

            The gold now clears 3:1 outright — past the homepage's
            own gold word at 2.64 — the white lines are well past the
            homepage's 3.60, the photograph is two-thirds brighter
            than it was, and the most that lands on Linds is 0.10 at
            her fingertips, falling to nothing before her hand.
          */}
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 hidden md:block"
            style={{
              background:
                'linear-gradient(to left, '
                + 'rgba(7,20,24,0.62) 0%, rgba(7,20,24,0.62) 46%, '
                + 'rgba(7,20,24,0.60) 48%, rgba(7,20,24,0.56) 49%, '
                + 'rgba(7,20,24,0.49) 51%, rgba(7,20,24,0.40) 52%, '
                + 'rgba(7,20,24,0.31) 54%, rgba(7,20,24,0.22) 56%, '
                + 'rgba(7,20,24,0.13) 57%, rgba(7,20,24,0.06) 59%, '
                + 'rgba(7,20,24,0.02) 60%, rgba(7,20,24,0.00) 62%)',
            }}
          />
        </div>

        <div className="mt-7 md:absolute md:inset-y-0 md:right-0 md:mt-0 md:flex md:w-[46%] md:items-center md:pr-6 lg:pr-8">
          <div>
            <h1
              className="font-sans text-[2.75rem] [--about-title-ink:#0C1826] md:text-[3.4rem] md:[--about-title-ink:#FFFFFF] md:[text-shadow:0_2px_30px_rgba(7,20,24,0.45)] lg:text-[4.8rem] xl:text-[5.5rem]"
              style={{
                fontWeight: 660,
                lineHeight: 1.02,
                letterSpacing: '-0.04em',
                color: 'var(--about-title-ink)',
              }}
            >
              {ABOUT_TITLE_LINES.map((line) => (
                <span
                  key={line.text}
                  /*
                    Two colours, because the word changes ground at
                    the breakpoint: it sits on the photograph from
                    ``md`` up and on the page below it.

                    On the photograph it is ``#EDBE5D``, the gold the
                    homepage uses on dark grounds ("belonging." on the
                    hero, "vision" on the navy section).

                    On the page it is ``TEAL_DEEP``, not gold. Gold on
                    white is barely there — the bright one measures
                    1.7:1 and even the homepage's duller light-ground
                    gold only reaches about 2:1 — whereas this teal is
                    already the page's accent, in the vision statement
                    below, and clears 5.3:1 on the page ground.

                    Written out rather than interpolated. Tailwind
                    generates CSS by scanning source text, so a class
                    name assembled from a template literal produces no
                    rule at all — which is exactly what happened on
                    the first attempt, leaving the custom property
                    undefined and the word not gold at any width.
                  */
                  className={
                    line.gold
                      ? 'block [--about-gold:#246B6A] md:[--about-gold:#EDBE5D]'
                      : 'block'
                  }
                  style={line.gold ? { color: 'var(--about-gold)' } : undefined}
                >
                  {line.text}
                </span>
              ))}
            </h1>
          </div>
        </div>
      </div>
    </Container>
  )
}

function Story() {
  return (
    <Container className="pt-12 md:pt-16">
      <div className={READING_COLUMN}>
        {/*
          The homepage opens its hero the same way — a larger, lighter
          line before the body settles down. Same family and colour as
          the prose below, one step up in size.
        */}
        <p
          className="font-serif text-[20px] leading-[1.7] tracking-[-0.01em] md:text-[21px]"
          style={{ color: BODY_INK }}
        >
          {ABOUT_INTRO}
        </p>
      </div>
    </Container>
  )
}

/** One story section, set at the reading width. */
function StorySection({ section }: { section: AboutSection }) {
  return (
    <Container>
      <section id={section.id} className={`${READING_COLUMN} pt-16 md:pt-24`}>
        <h2 className={HEADING_CLASS} style={HEADING_STYLE}>
          {section.heading}
        </h2>

        {/*
          The turning-point line is deliberately absent from this
          flow. It is lifted out into the navy feature below, which is
          the whole point of that section — leaving it here as well
          would say the same sentence twice.
        */}
        {section.paragraphs
          .filter((paragraph) => paragraph.emphasis !== 'turning-point')
          .map((paragraph, index) => (
            <p
              key={index}
              className={`mt-6 ${BODY_CLASS}`}
              style={{ color: BODY_INK }}
            >
              {paragraph.text}
            </p>
          ))}
      </section>
    </Container>
  )
}

/**
 * A pull-quote, white ground, teal serif.
 *
 * This was a deep-navy card borrowed from ``ClosingInvitation`` —
 * gold rule, teal glow, the lot. It worked on its own terms and was
 * the wrong thing on this page: a second feature treatment competing
 * with the vision statement below it, in a story that is otherwise
 * one continuous editorial column.
 *
 * Both statements now share one language: same colour, same width,
 * same family, same centring. The only difference is the slope —
 * this one is italic because it is a line Linds says, and the vision
 * statement is upright because it is a statement of intent.
 */
function PullQuote({
  text, italic = false,
}: { text: string; italic?: boolean }) {
  return (
    <Container className="pt-14 md:pt-20">
      <div
        data-about-quote={italic ? 'turning-point' : 'vision'}
        className="mx-auto max-w-[44rem] text-center"
      >
        <p
          className={`text-balance font-serif leading-[1.26] ${italic ? 'italic' : ''}`}
          style={{
            fontSize: 'clamp(1.6rem, 4.2vw, 2.6rem)',
            letterSpacing: '-0.02em',
            color: TEAL_DEEP,
          }}
        >
          {text}
        </p>
      </div>
    </Container>
  )
}

function Closing() {
  return (
    <Container className="pt-20 md:pt-28">
      {/*
        Invitation, signature and buttons beside the portrait on
        desktop; portrait first, then the words, on a phone. ``gap-y``
        is generous because this is the last thing on the page and it
        should not feel crowded against the footer.
      */}
      <div className="mx-auto grid max-w-4xl items-center gap-x-12 gap-y-8 lg:grid-cols-[1fr_minmax(0,22rem)]">
        <div>
          {/*
            The invitation is this section's heading, so it is set as
            one — the same ``HEADING_CLASS`` and ``HEADING_STYLE`` the
            five story headings use, at the same size.

            It used to carry its own font size, its own letter spacing
            and a serif face none of the headings above it use, which
            is why the ending read as though it came from a different
            page. Those were overrides for their own sake; removing
            them is the whole change.
          */}
          <h2 className={HEADING_CLASS} style={HEADING_STYLE}>
            {ABOUT_INVITATION}
          </h2>
          {/*
            The signature is the story's own body face, italic, one
            step up — the same step the opening line takes. Nothing
            here is special-cased any more.
          */}
          <p
            className={`mt-6 italic ${BODY_CLASS} text-[21px]`}
            style={{ color: BODY_INK }}
          >
            {ABOUT_SIGNATURE}
          </p>

          <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center">
            {/*
              Two existing destinations. "Create a Collective" goes
              where the For Creators page's own "Choose your plan"
              button goes — the plans on that page — rather than to
              any new signup route. "Explore Collectives" is the
              public listing the header and footer already link to.
            */}
            <HeroPrimaryCta href="/for-creators#plans" className="whitespace-nowrap">
              Create a Collective
            </HeroPrimaryCta>
            <HeroSecondaryCta href="/spaces" className="whitespace-nowrap">
              Explore Collectives
            </HeroSecondaryCta>
          </div>

          {/*
            Below the two buttons rather than beside them. Three
            things on one row would have read as three equal choices,
            and this is deliberately the quiet third option — a text
            link in the page's teal, not a button.

            Same new-tab handling as the photographer credit:
            ``noopener`` because without it YouTube gets a handle on
            this window through ``window.opener``.
          */}
          <p className="mt-5">
            <a
              href={ABOUT_VIDEO_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-sm text-[14.5px] underline decoration-1 underline-offset-4 transition-colors hover:opacity-80 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#246B6A]"
              style={{ color: TEAL_DEEP, textDecorationColor: 'rgba(36,107,106,0.35)' }}
            >
              {ABOUT_VIDEO_LABEL}
            </a>
          </p>
        </div>

        {/*
          No ``order-first`` any more. The portrait used to come
          before the invitation on a phone, which pushed the words,
          the buttons and the video link a long way down the screen.
          Ordinary flow now reads invitation, signature, buttons,
          video link, portrait, credit — and the desktop grid still
          puts the photograph beside the text.
        */}
        {/*
          The split is ``lg``, not ``md``. At 768px a 22rem photograph
          beside the text left about 290px for a display-size serif
          line and two buttons, and both button labels wrapped onto
          two lines — cramped, and the opposite of the unhurried
          ending this page wants. A tablet stacks instead: portrait,
          then the invitation at full width with the buttons side by
          side.
        */}
        <div>
          {/*
            5:4, because the photograph is 1135 × 909 and that is 5:4.
            The frame was a tall 4:5 while the file was still to come,
            which would have cropped a third of the width away and
            turned an environmental portrait into a tight head shot.
            Matching the frame to the file instead means the willow,
            the shoulders and the whole original composition survive,
            and ``objectFit: cover`` has nothing left to trim.
          */}
          <div
            data-about-frame="portrait"
            className="relative mx-auto aspect-[5/4] w-full max-w-[22rem] overflow-hidden rounded-2xl"
            style={{ background: '#1B2A22' }}
          >
            <Image
              src={ABOUT_IMAGES.portrait.src}
              alt={ABOUT_IMAGES.portrait.alt}
              fill
              sizes="(min-width: 1024px) 352px, (min-width: 640px) 352px, 100vw"
              // Shown as taken: no filter, no grade, no vignette.
              style={{ objectFit: 'cover', objectPosition: '50% 50%' }}
            />
          </div>
        </div>
      </div>
    </Container>
  )
}

/**
 * Photo credit, at the foot of the page.
 *
 * Both photographs are Narelle's, so this is one quiet line rather
 * than a caption under each — a caption beside the portrait would
 * have read as a label on Linds, which is not what it is. Small,
 * muted and last, the way a credit sits at the end of an article.
 */
function PhotoCredit() {
  return (
    <Container className="pb-20 pt-12 md:pb-28 md:pt-14">
      <p
        className="text-center text-[13px]"
        style={{ color: INK_SOFT }}
      >
        {ABOUT_PHOTO_CREDIT_PREFIX}
        {/*
          Only the name is the link — "Photographs by" is not part of
          what you would click. ``noopener noreferrer`` because it
          opens in a new tab: without ``noopener`` the destination
          gets a handle on this window through ``window.opener``.

          Hover and focus use ``TEAL_DEEP``, the page's existing
          accent, rather than a new colour. The focus ring is drawn
          with ``focus-visible`` so it appears for keyboard use and
          not on a mouse click, and it is an outline rather than a
          background so the credit stays understated either way.
        */}
        <a
          href={ABOUT_PHOTOGRAPHER_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="rounded-sm underline decoration-1 underline-offset-2 transition-colors hover:text-[#246B6A] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#246B6A]"
          style={{ textDecorationColor: 'rgba(12, 24, 38, 0.30)' }}
        >
          {ABOUT_PHOTOGRAPHER}
        </a>
      </p>
    </Container>
  )
}

export default function AboutPage() {
  return (
    <SiteShell>
      <main>
        <Hero />
        <Story />
        {ABOUT_SECTIONS.map((section) => (
          <Fragment key={section.id}>
            <StorySection section={section} />
            {/*
              The feature lands where the story turns — straight after
              "The idea I kept coming back to", which is the section
              whose closing line it carries. Driven off the content
              rather than off a hard-coded position, so reordering the
              story cannot leave the feature stranded in the wrong place.
            */}
            {section.paragraphs
              .filter((p) => p.emphasis === 'turning-point')
              .map((p) => <PullQuote key={p.text} text={p.text} italic />)}
          </Fragment>
        ))}
        <PullQuote text={ABOUT_VISION} />
        <Closing />
        <PhotoCredit />
      </main>
    </SiteShell>
  )
}
