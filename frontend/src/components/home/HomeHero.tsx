import Link from 'next/link'
import Container from '@/components/layout/Container'

export default function HomeHero() {
  return (
    <section
      className="relative flex overflow-hidden"
      style={{ background: '#071014', minHeight: 'clamp(560px, 70vh, 700px)' }}
    >

      {/* ── Video layer ──────────────────────────────────────────────────────── */}
      <video
        autoPlay
        muted
        loop
        playsInline
        preload="none"
        aria-hidden="true"
        className="absolute inset-0 h-full w-full object-cover"
        style={{
          opacity: 0.78,
          filter: 'saturate(0.65) brightness(0.72) contrast(1.12)',
        }}
      >
        <source src="/videos/hero-waves.mp4" type="video/mp4" />
      </video>

      {/* ── Cinematic overlay — heavier at bottom for text legibility ────────── */}
      <div
        className="pointer-events-none absolute inset-0"
        aria-hidden="true"
        style={{
          background:
            'linear-gradient(to bottom, rgba(7,16,20,0.55) 0%, rgba(7,16,20,0.30) 40%, rgba(7,16,20,0.55) 80%, rgba(7,16,20,0.75) 100%)',
        }}
      />

      {/* ── Subtle atmospheric teal tint ─────────────────────────────────────── */}
      <div
        className="pointer-events-none absolute inset-0"
        aria-hidden="true"
        style={{
          background:
            'radial-gradient(ellipse 90% 70% at 60% 30%, rgba(38,110,108,0.14) 0%, transparent 65%)',
        }}
      />

      {/* ── Grain overlay ───────────────────────────────────────────────────── */}
      <div
        className="pointer-events-none absolute inset-0"
        aria-hidden="true"
        style={{
          backgroundImage: `url("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='300' height='300'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='4' stitchTiles='stitch'/><feColorMatrix type='saturate' values='0'/></filter><rect width='300' height='300' filter='url(%23n)' opacity='0.028'/></svg>")`,
        }}
      />

      {/* ── Content ─────────────────────────────────────────────────────────── */}
      <div className="relative z-10 w-full" style={{ paddingTop: 'clamp(7rem, 14vw, 10rem)', paddingBottom: 'clamp(4rem, 8vw, 6rem)' }}>
      <Container>
        <div className="max-w-[680px]">

          <div className="mb-5 flex items-center gap-3">
            <div
              className="h-px w-6 shrink-0"
              style={{ background: 'rgba(212,176,72,0.45)' }}
            />
            <span
              className="text-[10.5px] font-semibold uppercase tracking-[0.20em]"
              style={{ color: 'rgba(255,255,255,0.32)' }}
            >
              Fresh Collective
            </span>
          </div>

          <h1
            className="mb-7"
            style={{
              fontSize: 'clamp(2.75rem, 6vw, 5.5rem)',
              lineHeight: '1.03',
              letterSpacing: '-0.04em',
              fontWeight: 660,
              color: '#ffffff',
            }}
          >
            <span className="block">Exploring better ways to</span>
            <span
              className="block"
              style={{
                backgroundImage: 'linear-gradient(100deg, #42C7C6 0%, #7FDAD9 28%, #D8F5F2 55%, #FFFFFF 78%, #FFFFFF 100%)',
                WebkitBackgroundClip: 'text',
                backgroundClip: 'text',
                color: 'transparent',
              }}
            >
              <span className="block">live, learn, create,</span>
              <span className="block">and lead.</span>
            </span>
          </h1>

          <p
            className="mb-9"
            style={{
              fontSize: 'clamp(1rem, 1.4vw, 1.0625rem)',
              lineHeight: '1.80',
              color: 'rgba(255,255,255,0.46)',
              maxWidth: '420px',
              letterSpacing: '-0.01em',
            }}
          >
            A membership for people exploring more intentional ways to grow —
            with structure, community, and depth that lasts.
          </p>

          <div className="flex flex-wrap items-center gap-3">
            <Link
              href="/spaces"
              className="inline-flex items-center rounded-xl px-7 py-3.5 text-[15px] font-semibold text-white transition-all hover:-translate-y-px hover:opacity-90"
              style={{
                background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                boxShadow: '0 2px 20px rgba(56,160,158,0.40)',
              }}
            >
              Explore Collectives
            </Link>
            <Link
              href="/signup"
              className="inline-flex items-center rounded-xl px-7 py-3.5 text-[15px] font-semibold transition-all hover:-translate-y-px bg-white hover:bg-[#F6F6F6]"
              style={{
                border: '1px solid rgba(255,255,255,0.12)',
                color: '#0F172A',
                boxShadow: '0 4px 24px rgba(0,0,0,0.30)',
              }}
            >
              Build a Collective
            </Link>
          </div>

        </div>
      </Container>
      </div>

    </section>
  )
}
