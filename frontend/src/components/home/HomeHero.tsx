import Link from 'next/link'
import Container from '@/components/layout/Container'

export default function HomeHero() {
  return (
    <section
      className="relative overflow-hidden"
      style={{ background: '#E8EBE7' }}
    >

      {/* ── Video layer ──────────────────────────────────────────────────────── */}
      {/* Sits at the very bottom of the stack. Purely atmospheric — not content. */}
      <video
        autoPlay
        muted
        loop
        playsInline
        preload="none"
        aria-hidden="true"
        className="absolute inset-0 h-full w-full object-cover"
        style={{
          opacity: 0.82,
          filter: 'saturate(0.74) brightness(0.86) contrast(1.10)',
        }}
      >
        <source src="/videos/hero-waves.mp4" type="video/mp4" />
      </video>

      {/* ── Tint overlay — light wash only, lets footage show through ───────── */}
      <div
        className="pointer-events-none absolute inset-0"
        aria-hidden="true"
        style={{ background: 'rgba(232,235,231,0.03)' }}
      />

      {/* ── Left text-protection gradient ───────────────────────────────────── */}
      {/* Darkens the content area enough to keep headlines readable without     */}
      {/* suppressing the video on the right half of the hero.                   */}
      <div
        className="pointer-events-none absolute inset-0"
        aria-hidden="true"
        style={{
          background:
            'linear-gradient(100deg, rgba(232,235,231,0.82) 0%, rgba(232,235,231,0.52) 28%, rgba(232,235,231,0.12) 50%, transparent 68%)',
        }}
      />

      {/* ── Subtle grid ─────────────────────────────────────────────────────── */}
      <div
        className="pointer-events-none absolute inset-0"
        aria-hidden="true"
        style={{
          backgroundImage:
            'linear-gradient(rgba(12,24,38,0.022) 1px, transparent 1px), linear-gradient(90deg, rgba(12,24,38,0.022) 1px, transparent 1px)',
          backgroundSize: '56px 56px',
        }}
      />

      {/* ── Layered gradient atmosphere ──────────────────────────────────────── */}
      <div className="pointer-events-none absolute inset-0" aria-hidden="true">
        <div style={{
          position: 'absolute', top: '-25%', right: '-12%',
          width: '900px', height: '900px', borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(56,160,158,0.11) 0%, transparent 58%)',
          filter: 'blur(72px)',
        }} />
        <div style={{
          position: 'absolute', bottom: '-15%', left: '-14%',
          width: '700px', height: '700px', borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(201,168,60,0.08) 0%, transparent 58%)',
          filter: 'blur(90px)',
        }} />
        <div style={{
          position: 'absolute', top: '30%', right: '18%',
          width: '380px', height: '380px', borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(56,160,158,0.06) 0%, transparent 65%)',
          filter: 'blur(50px)',
        }} />
      </div>

      {/* ── Grain overlay ───────────────────────────────────────────────────── */}
      <div
        className="pointer-events-none absolute inset-0"
        aria-hidden="true"
        style={{
          backgroundImage: `url("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='300' height='300'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='4' stitchTiles='stitch'/><feColorMatrix type='saturate' values='0'/></filter><rect width='300' height='300' filter='url(%23n)' opacity='0.035'/></svg>")`,
          opacity: 0.9,
        }}
      />

      {/* ── Bottom fade — transitions hero into next section cleanly ─────────── */}
      <div
        className="pointer-events-none absolute bottom-0 left-0 right-0 h-48"
        aria-hidden="true"
        style={{
          background: 'linear-gradient(to bottom, transparent, rgba(248,247,244,0.94))',
        }}
      />

      {/* ── Content ─────────────────────────────────────────────────────────── */}
      <Container className="relative py-16 sm:py-24 lg:py-28">
        <div className="max-w-[660px]">

          <div className="mb-6 flex items-center gap-3">
            <div className="h-px w-8 bg-teal-400" />
            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600">
              Learning for what comes next
            </span>
          </div>

          <h1
            className="mb-6 text-navy-950"
            style={{
              fontSize: 'clamp(2.5rem, 5vw, 4.625rem)',
              lineHeight: '1.05',
              letterSpacing: '-0.045em',
              fontWeight: 660,
            }}
          >
            Transformative learning,
            <br />
            <span
              style={{
                background: 'linear-gradient(118deg, #1E7A78 0%, #7ECFCD 45%, #DDD5C4 100%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
              }}
            >
              built for real life.
            </span>
          </h1>

          <div className="mb-9" style={{ maxWidth: '500px' }}>
            <p className="text-navy-600" style={{ fontSize: '1.0625rem', lineHeight: '1.78' }}>
              Fresh Collective is a place for people exploring more intentional ways to live, lead, create, and grow.
            </p>
            <p className="mt-3 text-navy-500" style={{ fontSize: '1rem', lineHeight: '1.78' }}>
              Guided pathways, live gatherings, and thoughtful communities designed to help new ideas become lived experience.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Link
              href="/spaces"
              className="inline-flex items-center rounded-xl px-7 py-3.5 text-[15px] font-semibold text-white transition-all hover:opacity-90 hover:-translate-y-px"
              style={{
                background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                boxShadow: '0 2px 18px rgba(56,160,158,0.38), 0 1px 3px rgba(0,0,0,0.08)',
              }}
            >
              Explore Collectives
            </Link>
            <Link
              href="/signup"
              className="inline-flex items-center rounded-xl border bg-white/75 px-7 py-3.5 text-[15px] font-semibold text-navy-700 backdrop-blur-sm transition-all hover:bg-white hover:-translate-y-px"
              style={{ borderColor: '#D0D8E2' }}
            >
              Build a Collective
            </Link>
          </div>

        </div>
      </Container>
    </section>
  )
}
