import Link from 'next/link'
import { SERIF_HEADING } from './serif'

/**
 * The navy band before the footer.
 *
 * Borrows ``PageHero``'s surface treatment — the same ``#071824``,
 * the same teal-tinted border and glow — rather than ``PageHero``
 * itself, which hard-codes an ``h1``. An article already has its
 * ``h1`` in the title, and a second one would be an SEO defect on
 * every Guide.
 *
 * Contained and rounded rather than full-bleed, matching the mockup:
 * the page is white and a full-width navy strip would read as the
 * footer arriving early.
 */
export default function GuideClosingBand() {
  return (
    <section
      className="overflow-hidden rounded-2xl px-6 py-12 text-center md:px-12 md:py-16"
      style={{
        background: '#071824',
        border: '1px solid rgba(56,160,158,0.22)',
        boxShadow:
          '0 0 0 1px rgba(56,160,158,0.08), 0 8px 32px rgba(7,24,36,0.18), 0 0 48px rgba(56,160,158,0.06)',
      }}
      aria-labelledby="guide-closing-heading"
    >
      <div
        aria-hidden="true"
        className="mx-auto mb-6 h-[2px] w-10 rounded-full"
        style={{
          background:
            'linear-gradient(90deg, rgba(56,160,158,0.25) 0%, #55B8B6 50%, rgba(56,160,158,0.25) 100%)',
        }}
      />
      {/* Colour set inline, not with ``text-white``. The unlayered
          ``h1…h6`` rule in globals.css outranks the utility class and
          would render this navy on a navy band — invisible. A project
          test pins the rule; see ``headingColour.test.ts``. */}
      <h2
        id="guide-closing-heading"
        className="mx-auto max-w-[20ch] text-[28px] leading-[1.15] tracking-[-0.02em] md:text-[34px]"
        style={{ ...SERIF_HEADING, color: '#FFFFFF' }}
      >
        Ready to give your work a home?
      </h2>
      <p className="mx-auto mt-4 max-w-[52ch] text-[16px] leading-[1.7] text-white/85">
        Set up your Collective in about 15 minutes. Start with who it&apos;s for
        and how it should feel.
      </p>
      <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
        <Link
          href="/for-creators#plans"
          className="inline-flex w-full items-center justify-center rounded-full bg-white px-7 py-3 text-[15px] font-semibold text-navy-950 transition-colors hover:bg-teal-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300 focus-visible:ring-offset-2 focus-visible:ring-offset-[#071824] sm:w-auto"
        >
          Start your Collective
        </Link>
        <Link
          href="/spaces"
          className="inline-flex w-full items-center justify-center rounded-full border border-white/35 px-7 py-3 text-[15px] font-semibold text-white transition-colors hover:border-white/60 hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300 focus-visible:ring-offset-2 focus-visible:ring-offset-[#071824] sm:w-auto"
        >
          Take a look around
        </Link>
      </div>
    </section>
  )
}
