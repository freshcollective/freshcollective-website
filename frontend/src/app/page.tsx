import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import AnimatedTypeRibbon from '@/components/ui/AnimatedTypeRibbon'
import HomeHero from '@/components/home/HomeHero'
import TransformationSection from '@/components/home/TransformationSection'
import EntryPoints from '@/components/home/EntryPoints'
import RealJourneySection from '@/components/home/RealJourneySection'
import PlatformLayers from '@/components/home/PlatformLayers'
import CommunityLayer from '@/components/home/CommunityLayer'
import Link from 'next/link'

/* ─── Design principles strip ───────────────────────────────────────────── */

const PRINCIPLES = [
  {
    label: 'Bite-sized by design',
    desc: '5–15 minute sessions. Built for real life, not aspirational schedules.',
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
        <rect x="1.5" y="1.5" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.3" />
        <rect x="10.5" y="1.5" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.3" />
        <rect x="1.5" y="10.5" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.3" />
        <rect x="10.5" y="10.5" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.3" />
      </svg>
    ),
  },
  {
    label: 'Live every month',
    desc: 'One structured live call per month. Real connection, not just content.',
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
        <circle cx="9" cy="9" r="7.5" stroke="currentColor" strokeWidth="1.3" />
        <circle cx="9" cy="9" r="3" fill="currentColor" />
      </svg>
    ),
  },
  {
    label: 'No deadline pressure',
    desc: 'Move at your own pace. Return to any phase whenever you need to.',
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
        <path d="M9 3v6l3.5 3.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="9" cy="9" r="7.5" stroke="currentColor" strokeWidth="1.3" />
      </svg>
    ),
  },
]

/* ─── Page ──────────────────────────────────────────────────────────────── */

export default function Home() {
  return (
    <SiteShell>

      {/* 1. Hero — dark, alive, transformation-first */}
      <HomeHero />

      {/* 2. Kinetic system band — dark theme */}
      <AnimatedTypeRibbon />

      {/* 3. Transformation outcomes — what changes */}
      <TransformationSection />

      {/* 4. Entry points — Start Free / Explore Membership */}
      <EntryPoints />

      {/* 5. Platform layers — how Fresh Collective works */}
      <PlatformLayers />

      {/* 6. REAL Journey — framework section */}
      <RealJourneySection />

      {/* 7. Community layer — belonging, live support */}
      <CommunityLayer />

      {/* 8. Design principles strip */}
      <section className="bg-white py-20">
        <Container>
          <div className="grid grid-cols-1 gap-px sm:grid-cols-3">
            {PRINCIPLES.map(({ label, desc, icon }, i) => (
              <div
                key={label}
                className="group flex flex-col gap-4 px-8 py-7 transition-colors first:pl-0 last:pr-0"
                style={i > 0 ? { borderLeft: '1px solid rgba(0,0,0,0.06)' } : {}}
              >
                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-teal-50 text-teal-600"
                  style={{ border: '1px solid rgba(56,160,158,0.15)' }}>
                  {icon}
                </div>
                <div>
                  <p className="mb-1.5 text-[14px] font-semibold text-navy-900">{label}</p>
                  <p className="text-[14px] leading-[1.75] text-[#777]">{desc}</p>
                </div>
              </div>
            ))}
          </div>
        </Container>
      </section>

      {/* 9. Final CTA */}
      <section
        className="relative overflow-hidden py-32 sm:py-40"
        style={{ background: 'linear-gradient(160deg, #060C17 0%, #080F1E 50%, #071A1A 100%)' }}
      >
        {/* Atmosphere */}
        <div className="pointer-events-none absolute inset-0" aria-hidden="true">
          <div
            style={{
              position: 'absolute', top: '-20%', left: '50%', transform: 'translateX(-50%)',
              width: '700px', height: '500px', borderRadius: '50%',
              background: 'radial-gradient(ellipse, rgba(56,160,158,0.16) 0%, rgba(56,160,158,0.04) 50%, transparent 72%)',
              filter: 'blur(60px)',
            }}
          />
          <div
            style={{
              position: 'absolute', bottom: '-15%', right: '-10%',
              width: '500px', height: '500px', borderRadius: '50%',
              background: 'radial-gradient(circle, rgba(212,176,72,0.07) 0%, transparent 65%)',
              filter: 'blur(80px)',
            }}
          />
          {/* Dot grid */}
          <div
            style={{
              position: 'absolute', inset: 0,
              backgroundImage: 'radial-gradient(circle, rgba(255,255,255,0.15) 1px, transparent 1px)',
              backgroundSize: '44px 44px',
              opacity: 0.18,
            }}
          />
        </div>

        <Container className="relative">
          <div className="mx-auto max-w-[620px] text-center">

            <p
              className="mb-5 text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-500"
            >
              Ready when you are
            </p>

            <h2
              className="mb-6 font-semibold text-white"
              style={{
                fontSize: 'clamp(2.25rem, 4.5vw, 3.75rem)',
                lineHeight: '1.06',
                letterSpacing: '-0.04em',
              }}
            >
              A softer way forward.
              <br />
              <span
                style={{
                  background: 'linear-gradient(120deg, #7FCFCD 0%, #55B8B6 40%, #D4B048 100%)',
                  WebkitBackgroundClip: 'text',
                  WebkitTextFillColor: 'transparent',
                  backgroundClip: 'text',
                }}
              >
                With enough structure to actually move.
              </span>
            </h2>

            <p className="mb-12 text-[16px] leading-[1.8] text-navy-300">
              Start free when you want a first step.
              Join the membership when you are ready to be held through the deeper work.
            </p>

            <div className="flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
              <Link
                href="/real-journey"
                className="group relative inline-flex items-center overflow-hidden rounded-xl px-8 py-[15px] text-[15px] font-semibold text-white transition-all duration-200"
                style={{
                  background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                  boxShadow: 'var(--fc-shadow-btn)',
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
                className="inline-flex items-center rounded-xl px-8 py-[15px] text-[15px] font-semibold transition-all duration-200 hover:border-white/30 hover:text-white"
                style={{
                  border: '1px solid rgba(255,255,255,0.14)',
                  background: 'rgba(255,255,255,0.05)',
                  color: 'rgba(255,255,255,0.70)',
                }}
              >
                Explore Membership
              </Link>
            </div>

          </div>
        </Container>
      </section>

    </SiteShell>
  )
}
