import Link from 'next/link'
import Container from '@/components/layout/Container'

export default function HomeHero() {
  return (
    <section
      className="relative flex overflow-hidden"
      style={{ background: '#071014', minHeight: 'clamp(480px, 70vh, 700px)' }}
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
          opacity: 0.88,
          filter: 'saturate(0.72) brightness(0.82) contrast(1.08)',
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
            'linear-gradient(to bottom, rgba(7,16,20,0.42) 0%, rgba(7,16,20,0.18) 40%, rgba(7,16,20,0.44) 80%, rgba(7,16,20,0.68) 100%)',
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
      <div className="relative z-10 w-full" style={{ paddingTop: 'clamp(5rem, 14vw, 10rem)', paddingBottom: 'clamp(3.5rem, 8vw, 6rem)' }}>
      <Container>
        <div className="max-w-[680px]">

          <h1
            className="mb-6"
            style={{
              fontSize: 'clamp(2.375rem, 6vw, 5.5rem)',
              lineHeight: '1.05',
              letterSpacing: '-0.04em',
              fontWeight: 660,
              color: '#ffffff',
            }}
          >
            <span className="block">Human connection</span>
            <span
              className="block"
              style={{
                backgroundImage: 'linear-gradient(100deg, #42C7C6 0%, #7FDAD9 28%, #D8F5F2 55%, #FFFFFF 78%, #FFFFFF 100%)',
                WebkitBackgroundClip: 'text',
                backgroundClip: 'text',
                color: 'transparent',
              }}
            >
              <span className="block">is our greatest</span>
              <span className="block">advantage.</span>
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
            Fresh Collective is a home for many Collectives, where
            people can learn, lead, connect and grow together. There
            are Collectives you can join, or you can build your own.
          </p>

          <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
            <Link
              href="/spaces"
              className="inline-flex w-full items-center justify-center rounded-xl px-7 py-3.5 text-[15px] font-semibold text-white transition-all hover:-translate-y-px hover:opacity-90 sm:w-auto"
              style={{
                background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                boxShadow: '0 2px 20px rgba(56,160,158,0.40)',
              }}
            >
              Explore Collectives
            </Link>
            <Link
              href="/for-creators"
              className="inline-flex w-full items-center justify-center rounded-xl px-7 py-3.5 text-[15px] font-semibold transition-all hover:-translate-y-px bg-white hover:bg-[#F6F6F6] sm:w-auto"
              style={{
                border: '1px solid rgba(255,255,255,0.12)',
                color: '#0F172A',
                boxShadow: '0 4px 24px rgba(0,0,0,0.30)',
              }}
            >
              Create a Collective
            </Link>
          </div>

        </div>
      </Container>
      </div>

    </section>
  )
}
