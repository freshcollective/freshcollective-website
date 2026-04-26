import type { CSSProperties } from 'react'
import Link from 'next/link'
import Container from '@/components/layout/Container'

export default function HomeHero() {
  return (
    <section
      className="relative overflow-hidden"
      style={{
        background: 'linear-gradient(160deg, #080F1E 0%, #0C1826 55%, #071A1A 100%)',
        minHeight: '90vh',
      }}
    >
      {/* Background atmosphere */}
      <div className="pointer-events-none absolute inset-0" aria-hidden="true">
        {/* Primary teal orb — top right */}
        <div
          style={{
            position: 'absolute', top: '-18%', right: '-10%',
            width: '750px', height: '750px', borderRadius: '50%',
            background: 'radial-gradient(circle, rgba(56,160,158,0.24) 0%, rgba(56,160,158,0.06) 45%, transparent 70%)',
            filter: 'blur(70px)',
            animation: 'float-slow 14s ease-in-out infinite',
          }}
        />
        {/* Warm gold centre — subtle depth */}
        <div
          style={{
            position: 'absolute', top: '20%', left: '35%',
            width: '600px', height: '600px', borderRadius: '50%',
            background: 'radial-gradient(circle, rgba(212,176,72,0.07) 0%, transparent 65%)',
            filter: 'blur(90px)',
            animation: 'float-slow 18s ease-in-out 4s infinite',
          }}
        />
        {/* Bottom-left teal */}
        <div
          style={{
            position: 'absolute', bottom: '-12%', left: '-8%',
            width: '640px', height: '640px', borderRadius: '50%',
            background: 'radial-gradient(circle, rgba(56,160,158,0.10) 0%, transparent 60%)',
            filter: 'blur(80px)',
          }}
        />
        {/* Dot grid overlay */}
        <div
          style={{
            position: 'absolute', inset: 0,
            backgroundImage: 'radial-gradient(circle, rgba(255,255,255,0.20) 1px, transparent 1px)',
            backgroundSize: '44px 44px',
            opacity: 0.22,
          }}
        />
        {/* Bottom fade */}
        <div
          style={{
            position: 'absolute', bottom: 0, left: 0, right: 0, height: '220px',
            background: 'linear-gradient(to bottom, transparent, rgba(7,26,26,0.35))',
          }}
        />
      </div>

      <Container className="relative py-24 sm:py-32 lg:py-36 xl:py-44">
        <div className="grid items-center gap-12 lg:grid-cols-[1fr_460px] xl:grid-cols-[1fr_520px]">

          {/* ── Copy ── */}
          <div className="max-w-[600px]">

            {/* Badge */}
            <div
              className="mb-8 inline-flex items-center gap-2.5 rounded-full px-4 py-2"
              style={{
                background: 'rgba(56,160,158,0.10)',
                border: '1px solid rgba(56,160,158,0.22)',
              }}
            >
              <span
                className="h-1.5 w-1.5 rounded-full bg-teal-400"
                style={{ animation: 'glow-pulse 2.5s ease-in-out infinite' }}
              />
              <span
                className="text-[11px] font-semibold text-teal-300"
                style={{ letterSpacing: '0.1em', textTransform: 'uppercase' }}
              >
                A membership for women
              </span>
            </div>

            {/* Headline */}
            <h1
              className="mb-7 font-semibold text-white"
              style={{
                fontSize: 'clamp(2.8rem, 5.5vw, 5.2rem)',
                lineHeight: '1.03',
                letterSpacing: '-0.04em',
              }}
            >
              Move from survival
              <br />
              into expansion
              <br />
              <span
                style={{
                  background: 'linear-gradient(120deg, #7FCFCD 0%, #55B8B6 38%, #D4B048 100%)',
                  WebkitBackgroundClip: 'text',
                  WebkitTextFillColor: 'transparent',
                  backgroundClip: 'text',
                }}
              >
                that actually lasts.
              </span>
            </h1>

            {/* Sub-copy */}
            <p
              className="mb-3 text-navy-200"
              style={{ fontSize: 'clamp(1.05rem, 1.7vw, 1.15rem)', lineHeight: '1.75' }}
            >
              Stop coping your way through life. Fresh Collective is a structured
              transformation for women who are ready to stop surviving — and start leading
              from the inside out.
            </p>
            <p className="mb-10 text-[15px] leading-[1.8] text-navy-400">
              One foundation. A live community. Deepening pathways. Built for real life,
              not aspirational schedules.
            </p>

            {/* CTAs */}
            <div className="flex flex-wrap gap-3">
              <Link
                href="/real-journey"
                className="group relative inline-flex items-center overflow-hidden rounded-xl px-7 py-[14px] text-[15px] font-semibold text-white transition-all duration-200"
                style={{
                  background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                  boxShadow: 'var(--fc-shadow-btn)',
                  animation: 'glow-pulse 3s ease-in-out infinite',
                }}
              >
                <span className="relative z-10">Start Free</span>
                <div
                  className="absolute inset-0 opacity-0 transition-opacity duration-200 group-hover:opacity-100"
                  style={{ background: 'linear-gradient(135deg, #55B8B6 0%, #7FCFCD 100%)' }}
                />
              </Link>

              <Link
                href="/membership"
                className="inline-flex items-center rounded-xl px-7 py-[14px] text-[15px] font-semibold transition-all duration-200 hover:border-white/30 hover:text-white"
                style={{
                  border: '1px solid rgba(255,255,255,0.14)',
                  background: 'rgba(255,255,255,0.05)',
                  color: 'rgba(255,255,255,0.72)',
                }}
              >
                Explore Membership
              </Link>
            </div>

            {/* Social proof */}
            <div className="mt-10 flex flex-wrap items-center gap-5">
              <div className="flex items-center gap-2.5">
                <div className="flex -space-x-2">
                  {['#55B8B6', '#7FCFCD', '#AAE1E0', '#38A09E'].map((c, i) => (
                    <div
                      key={i}
                      className="h-7 w-7 rounded-full border-[2.5px]"
                      style={{ background: c, borderColor: '#080F1E' }}
                    />
                  ))}
                </div>
                <span className="text-[13px] text-navy-400">42 women in The Heart</span>
              </div>
              <div className="hidden items-center gap-2 sm:flex">
                <span className="h-1.5 w-1.5 rounded-full bg-teal-500" />
                <span className="text-[13px] text-navy-400">REAL Journey · Free to begin</span>
              </div>
            </div>
          </div>

          {/* ── Transformation visual (desktop) ── */}
          <div className="hidden lg:flex lg:items-center lg:justify-center">
            <HeroTransformationVisual />
          </div>

        </div>
      </Container>
    </section>
  )
}

/* ─── Transformation visual ─────────────────────────────────────────────── */

function HeroTransformationVisual() {
  return (
    <div
      className="relative select-none"
      style={{ width: '480px', height: '500px' }}
      aria-hidden="true"
    >
      {/* Orbital rings */}
      {([320, 400, 470] as const).map((size, i) => (
        <div
          key={size}
          className="absolute inset-0 flex items-center justify-center"
          style={{ transform: 'translateX(-16px)' }}
        >
          <div
            style={{
              width: `${size}px`,
              height: `${size}px`,
              borderRadius: '50%',
              border: `1px solid rgba(56,160,158,${0.09 - i * 0.025})`,
            }}
          />
        </div>
      ))}

      {/* Central core glow */}
      <div
        className="absolute inset-0 flex items-center justify-center"
        style={{ transform: 'translateX(-16px)' }}
      >
        <div
          style={{
            width: '160px', height: '160px', borderRadius: '50%',
            background: 'radial-gradient(circle, rgba(56,160,158,0.20) 0%, rgba(56,160,158,0.05) 60%, transparent 80%)',
          }}
        />
      </div>

      {/* Logo orb */}
      <div
        className="absolute inset-0 flex flex-col items-center justify-center gap-3"
        style={{ transform: 'translateX(-16px)' }}
      >
        <div
          style={{
            width: '60px', height: '60px', borderRadius: '50%',
            background: 'linear-gradient(135deg, #38A09E, #55B8B6)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: '0 0 50px rgba(56,160,158,0.55)',
          }}
        >
          <div className="h-[18px] w-[18px] rounded-sm bg-white" style={{ opacity: 0.9 }} />
        </div>
        <p
          className="text-[10px] font-semibold text-teal-500"
          style={{ letterSpacing: '0.14em', textTransform: 'uppercase' }}
        >
          R · E · A · L
        </p>
      </div>

      {/* Before: muted/dissolving cards */}
      <FloatingCard
        pos={{ top: '4%', left: '-2%' }}
        delay="0s"
        label="Always exhausted"
        labelColor="rgba(255,255,255,0.18)"
        sub="Running on empty"
        subColor="rgba(255,255,255,0.10)"
        bg="rgba(255,255,255,0.03)"
        border="rgba(255,255,255,0.06)"
      />
      <FloatingCard
        pos={{ top: '56%', left: '-4%' }}
        delay="1.8s"
        label="Overwhelmed"
        labelColor="rgba(255,255,255,0.18)"
        sub="Too many things"
        subColor="rgba(255,255,255,0.10)"
        bg="rgba(255,255,255,0.03)"
        border="rgba(255,255,255,0.06)"
      />
      <FloatingCard
        pos={{ bottom: '8%', left: '14%' }}
        delay="0.9s"
        label="Self-abandoning"
        labelColor="rgba(255,255,255,0.18)"
        sub="Coping by managing"
        subColor="rgba(255,255,255,0.10)"
        bg="rgba(255,255,255,0.03)"
        border="rgba(255,255,255,0.06)"
      />

      {/* After: glowing expansion cards */}
      <FloatingCard
        pos={{ top: '2%', right: '-2%' }}
        delay="0.5s"
        label="Clear"
        labelColor="#7FCFCD"
        sub="Values over fear"
        subColor="#6B8EB2"
        bg="rgba(56,160,158,0.08)"
        border="rgba(56,160,158,0.22)"
        glow="var(--fc-shadow-float-teal)"
      />
      <FloatingCard
        pos={{ top: '44%', right: '-6%' }}
        delay="1.4s"
        label="Leading"
        labelColor="#D4B048"
        sub="From the inside out"
        subColor="#6B8EB2"
        bg="rgba(212,176,72,0.07)"
        border="rgba(212,176,72,0.22)"
        glow="var(--fc-shadow-float-gold)"
      />
      <FloatingCard
        pos={{ bottom: '4%', right: '2%' }}
        delay="2.2s"
        label="Energised"
        labelColor="#7FCFCD"
        sub="Sustainable expansion"
        subColor="#6B8EB2"
        bg="rgba(56,160,158,0.08)"
        border="rgba(56,160,158,0.22)"
        glow="var(--fc-shadow-float-teal)"
      />
    </div>
  )
}

function FloatingCard({
  pos, delay, label, labelColor, sub, subColor, bg, border, glow,
}: {
  pos: CSSProperties
  delay: string
  label: string
  labelColor: string
  sub: string
  subColor: string
  bg: string
  border: string
  glow?: string
}) {
  return (
    <div
      className="absolute"
      style={{ ...pos, animation: `float 6s ease-in-out ${delay} infinite` }}
    >
      <div
        className="rounded-xl px-4 py-3"
        style={{
          background: bg,
          border: `1px solid ${border}`,
          boxShadow: glow,
          backdropFilter: 'blur(10px)',
        }}
      >
        <p className="text-[12px] font-semibold" style={{ color: labelColor }}>{label}</p>
        <p className="mt-0.5 text-[10px]" style={{ color: subColor }}>{sub}</p>
      </div>
    </div>
  )
}
