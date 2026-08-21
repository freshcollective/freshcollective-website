import Image from 'next/image'
import Container from '@/components/layout/Container'
import { HeroPrimaryCta, HeroSecondaryCta } from '@/components/marketing/heroCtaButtons'

export default function HomeHero() {
  return (
    <section
      className="relative flex overflow-hidden"
      style={{ background: '#0F1B18', minHeight: 'clamp(480px, 70vh, 700px)' }}
    >

      {/* ── Illustration layer ──────────────────────────────────────────────
          Warm golden-hour outdoor gathering. Next Image serves the WebP
          with automatic responsive sizing; `priority` because this is
          above-the-fold on every visit. object-position keeps the
          foreground groups + hand-lettered sign visible when the frame
          crops for portrait viewports. */}
      <Image
        src="/home/hero-community.webp"
        alt=""
        aria-hidden="true"
        fill
        priority
        sizes="100vw"
        style={{
          objectFit: 'cover',
          objectPosition: '50% 40%',
        }}
      />

      {/* ── Readability treatment ───────────────────────────────────────────
          Two purposes:
            1. Give the headline (left half of the hero) a clear dark
               ground without darkening the whole illustration.
            2. Keep the golden-hour warmth on the right side of the
               frame — where the landscape and painting figures sit —
               so the image stays rich rather than muddy.
          Horizontal gradient (heavier left) does the primary
          readability work; a light bottom gradient tucks the CTA row
          under a soft floor. Deliberately no saturate() / contrast()
          filters — the illustration was authored with the intended
          look and we don't second-guess it. */}
      <div
        className="pointer-events-none absolute inset-0"
        aria-hidden="true"
        style={{
          background:
            'linear-gradient(100deg, rgba(7,20,24,0.72) 0%, rgba(7,20,24,0.55) 28%, rgba(7,20,24,0.22) 55%, rgba(7,20,24,0.08) 78%, rgba(7,20,24,0.04) 100%)',
        }}
      />
      <div
        className="pointer-events-none absolute inset-0"
        aria-hidden="true"
        style={{
          background:
            'linear-gradient(to bottom, transparent 60%, rgba(7,20,24,0.28) 100%)',
        }}
      />

      {/* ── Content ─────────────────────────────────────────────────────── */}
      <div className="relative z-10 w-full" style={{ paddingTop: 'clamp(5rem, 14vw, 10rem)', paddingBottom: 'clamp(3.5rem, 8vw, 6rem)' }}>
      <Container>
        <div className="max-w-[640px]">

          {/* Lead-in — deliberately small (~45% of the main line's
              size at the desktop max) and faded, so the visitor's eye
              reads it as a set-up rather than as competing claim. Not
              an eyebrow: still sentence case, still the display sans,
              just quiet. */}
          <p
            className="mb-4"
            style={{
              fontSize: 'clamp(1.0625rem, 2.6vw, 2.375rem)',
              lineHeight: '1.15',
              letterSpacing: '-0.015em',
              fontWeight: 500,
              color: '#FFFFFF',
              opacity: 0.55,
            }}
          >
            Most platforms optimise for engagement...
          </p>

          {/* Main claim — unmistakably the largest thing on the page.
              "belonging." carries the sanctioned warm gold; everything
              else stays full-strength white in the same display sans. */}
          <h1
            className="mb-8"
            style={{
              fontSize: 'clamp(2.75rem, 7.4vw, 6.25rem)',
              lineHeight: '1.02',
              letterSpacing: '-0.04em',
              fontWeight: 660,
              color: '#FFFFFF',
            }}
          >
            <span className="inline sm:block">We optimise for</span>{' '}
            <span
              className="inline sm:block"
              style={{ color: '#EDBE5D' }}
            >
              belonging.
            </span>
          </h1>

          <p
            className="mb-8"
            style={{
              fontSize: 'clamp(0.9375rem, 1.4vw, 1.0625rem)',
              lineHeight: '1.80',
              color: '#FFFFFF',
              maxWidth: '560px',
              letterSpacing: '-0.01em',
            }}
          >
            Fresh Collective gives creators a beautiful place to bring
            people together — through pathways, gatherings, conversation
            and shared experiences. Build a Collective that feels like
            yours.
          </p>

          <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
            <HeroPrimaryCta href="/for-creators">Create a Collective</HeroPrimaryCta>
            <HeroSecondaryCta href="/spaces">Explore Collectives</HeroSecondaryCta>
          </div>

        </div>
      </Container>
      </div>

    </section>
  )
}
