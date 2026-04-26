import Link from 'next/link'
import Container from '@/components/layout/Container'

export default function HomeHero() {
  return (
    <section className="relative overflow-hidden bg-white">
      {/* Ambient glows */}
      <div className="pointer-events-none absolute inset-0" aria-hidden="true">
        <div
          style={{
            position: 'absolute', top: '-15%', right: '-8%',
            width: '700px', height: '700px', borderRadius: '50%',
            background: 'radial-gradient(circle, rgba(56,160,158,0.07) 0%, transparent 65%)',
            filter: 'blur(80px)',
          }}
        />
        <div
          style={{
            position: 'absolute', bottom: '-5%', left: '-8%',
            width: '550px', height: '550px', borderRadius: '50%',
            background: 'radial-gradient(circle, rgba(212,176,72,0.05) 0%, transparent 60%)',
            filter: 'blur(100px)',
          }}
        />
      </div>

      <Container className="relative pb-24 pt-20 sm:pb-28 sm:pt-24 lg:pb-32 lg:pt-28">
        <div className="max-w-[700px]">

          {/* Eyebrow */}
          <div className="mb-8 flex items-center gap-3">
            <div className="h-px w-8 bg-teal-400" />
            <span
              className="text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600"
            >
              A membership for women
            </span>
          </div>

          {/* Headline */}
          <h1
            className="mb-8 text-navy-950"
            style={{
              fontSize: 'clamp(2.75rem, 5.5vw, 5rem)',
              lineHeight: '1.04',
              letterSpacing: '-0.045em',
              fontWeight: 650,
            }}
          >
            You&apos;re not here to just
            <br />
            survive your life.
            <br />
            <span
              style={{
                background: 'linear-gradient(120deg, #38A09E 0%, #55B8B6 45%, #C9A83C 100%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
              }}
            >
              You&apos;re here to live it.
            </span>
          </h1>

          {/* Sub-copy */}
          <p
            className="mb-12 text-navy-500"
            style={{ fontSize: '1.0625rem', lineHeight: '1.78', maxWidth: '560px' }}
          >
            If you&apos;ve been holding everything together for a long time, you already know
            something needs to change. Fresh Collective gives you a way to move out of
            survival — and into a life that actually works.
          </p>

          {/* CTAs */}
          <div className="flex flex-wrap gap-3">
            <Link
              href="#inside-the-collective"
              className="inline-flex items-center rounded-xl px-7 py-3.5 text-[15px] font-semibold text-white transition-opacity hover:opacity-90"
              style={{
                background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                boxShadow: 'var(--fc-shadow-btn)',
              }}
            >
              See inside the Collective
            </Link>
            {/* /entrance — dedicated onboarding welcome route, not yet built; linking to /real-journey in the meantime */}
            <Link
              href="/real-journey"
              className="inline-flex items-center rounded-xl border px-7 py-3.5 text-[15px] font-semibold text-navy-700 transition-colors hover:bg-navy-50"
              style={{ borderColor: '#D1DCE9' }}
            >
              Start at The Entrance
            </Link>
          </div>

          {/* Social proof */}
          <div className="mt-10 flex items-center gap-3">
            <div className="flex -space-x-1.5">
              {['#55B8B6', '#7FCFCD', '#AAE1E0', '#38A09E'].map((c, i) => (
                <div
                  key={i}
                  className="h-6 w-6 rounded-full border-[2.5px] border-white"
                  style={{ background: c }}
                />
              ))}
            </div>
            <span className="text-[13px] text-navy-400">
              42 women in The Heart · REAL Journey free to begin
            </span>
          </div>

        </div>
      </Container>
    </section>
  )
}
