import Link from 'next/link'
import Container from '@/components/layout/Container'

export default function EntryPoints() {
  return (
    <section className="bg-white py-24 sm:py-32">
      <Container>

        {/* Header */}
        <div className="mb-14 max-w-[560px]">
          <p className="mb-4 text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600">
            Two ways in
          </p>
          <h2
            className="mb-4 font-semibold text-navy-950"
            style={{ fontSize: 'clamp(2rem, 4vw, 3.25rem)', lineHeight: '1.07', letterSpacing: '-0.04em' }}
          >
            Start where you are.
          </h2>
          <p className="text-[16px] leading-[1.8] text-[#666]">
            Choose based on readiness, not hierarchy. There is no wrong entry — and
            you can always expand from wherever you begin.
          </p>
        </div>

        <div className="grid gap-5 md:grid-cols-2">

          {/* ── Free / REAL Journey ── */}
          <div
            className="group relative flex flex-col overflow-hidden rounded-2xl p-8 transition-all duration-300 hover:-translate-y-1"
            style={{
              background: 'linear-gradient(145deg, #F8FDFD 0%, #EAF7F7 100%)',
              border: '1px solid rgba(56,160,158,0.15)',
              boxShadow: 'var(--fc-shadow-card)',
            }}
          >
            {/* Corner glow */}
            <div
              className="pointer-events-none absolute -right-20 -top-20 h-64 w-64 rounded-full opacity-40"
              style={{ background: 'radial-gradient(circle, rgba(56,160,158,0.18) 0%, transparent 70%)' }}
              aria-hidden="true"
            />

            <div className="mb-6 relative z-10">
              <span
                className="inline-block rounded-full px-3.5 py-1.5 text-[11px] font-semibold text-teal-700"
                style={{ background: 'rgba(56,160,158,0.10)', border: '1px solid rgba(56,160,158,0.20)' }}
              >
                Free to begin
              </span>
            </div>

            <div className="relative z-10 flex-1">
              <h3
                className="mb-3 font-semibold text-navy-950"
                style={{ fontSize: 'clamp(1.4rem, 2.5vw, 1.75rem)', letterSpacing: '-0.03em' }}
              >
                REAL Journey
              </h3>
              <p className="mb-7 text-[15px] leading-[1.8] text-[#555]">
                A first step that holds. Work through the four phases — Recognise, Explore,
                Align, Lead — at your own pace. When you are ready, step deeper.
              </p>

              <ul className="mb-8 space-y-3">
                {[
                  'Four-phase transformation framework',
                  'Practices, prompts, and tools',
                  'Self-paced — revisit anytime',
                  'No pressure, no deadline',
                ].map((item) => (
                  <li key={item} className="flex items-start gap-3 text-[14px] text-[#555]">
                    <svg className="mt-[3px] shrink-0 text-teal-500" width="14" height="14" viewBox="0 0 14 14" fill="none">
                      <circle cx="7" cy="7" r="6" stroke="currentColor" strokeWidth="1.2" />
                      <path d="M4.5 7l1.8 1.8 3.2-3.6" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    {item}
                  </li>
                ))}
              </ul>
            </div>

            <Link
              href="/real-journey"
              className="relative z-10 inline-flex h-12 w-full items-center justify-center rounded-xl text-[14px] font-semibold text-white transition-all duration-200"
              style={{
                background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                boxShadow: 'var(--fc-shadow-btn)',
              }}
            >
              Start Free
            </Link>

            <p className="relative z-10 mt-4 text-center text-[12px] text-teal-700/60">
              No account required to explore
            </p>
          </div>

          {/* ── Full membership ── */}
          <div
            className="group relative flex flex-col overflow-hidden rounded-2xl p-8 transition-all duration-300 hover:-translate-y-1"
            style={{
              background: 'linear-gradient(145deg, #0C1826 0%, #0D2030 60%, #071A1A 100%)',
              boxShadow: 'var(--fc-shadow-raised)',
            }}
          >
            {/* Corner glow */}
            <div
              className="pointer-events-none absolute -right-16 -top-16 h-64 w-64 rounded-full"
              style={{ background: 'radial-gradient(circle, rgba(56,160,158,0.20) 0%, transparent 65%)' }}
              aria-hidden="true"
            />
            {/* Bottom-left gold accent */}
            <div
              className="pointer-events-none absolute -bottom-12 -left-12 h-48 w-48 rounded-full"
              style={{ background: 'radial-gradient(circle, rgba(212,176,72,0.10) 0%, transparent 70%)' }}
              aria-hidden="true"
            />

            <div className="mb-6 relative z-10">
              <span
                className="inline-block rounded-full px-3.5 py-1.5 text-[11px] font-semibold text-teal-300"
                style={{ background: 'rgba(56,160,158,0.14)', border: '1px solid rgba(56,160,158,0.25)' }}
              >
                Full membership
              </span>
            </div>

            <div className="relative z-10 flex-1">
              <h3
                className="mb-3 font-semibold text-white"
                style={{ fontSize: 'clamp(1.4rem, 2.5vw, 1.75rem)', letterSpacing: '-0.03em' }}
              >
                Everything included
              </h3>
              <p className="mb-7 text-[15px] leading-[1.8] text-navy-300">
                Join the full membership and be held through the deeper work — REAL Journey,
                monthly live calls, deepening pathways, and a community of women walking
                alongside you.
              </p>

              <ul className="mb-8 space-y-3">
                {[
                  'Complete REAL Journey foundation',
                  'Monthly live calls with the community',
                  'Deepening pathways — The Rooms',
                  'Nervous system, Human Design, Leadership',
                  'Full content and practice library',
                ].map((item) => (
                  <li key={item} className="flex items-start gap-3 text-[14px] text-navy-300">
                    <svg className="mt-[3px] shrink-0 text-teal-400" width="14" height="14" viewBox="0 0 14 14" fill="none">
                      <circle cx="7" cy="7" r="6" stroke="currentColor" strokeWidth="1.2" />
                      <path d="M4.5 7l1.8 1.8 3.2-3.6" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    {item}
                  </li>
                ))}
              </ul>
            </div>

            <Link
              href="/membership"
              className="relative z-10 inline-flex h-12 w-full items-center justify-center rounded-xl text-[14px] font-semibold text-white transition-all duration-200 hover:bg-white/15"
              style={{ border: '1px solid rgba(255,255,255,0.18)', background: 'rgba(255,255,255,0.08)' }}
            >
              Explore Membership
            </Link>

            <p className="relative z-10 mt-4 text-center text-[12px] text-navy-400">
              Ready when you are. No urgency.
            </p>
          </div>

        </div>

        {/* Framing note */}
        <p className="mt-8 text-center text-[14px] text-[#AAA]">
          Start free when you want a first step. Join the membership when you are ready to be held through the deeper work.
        </p>

      </Container>
    </section>
  )
}
