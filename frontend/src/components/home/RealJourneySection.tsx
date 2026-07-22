import Link from 'next/link'
import Container from '@/components/layout/Container'

const PHASES = [
  {
    letter: 'R',
    name: 'Recognise',
    body: 'See clearly what is actually true — what you are carrying, and what has quietly been running your life.',
    chips: ['Self-inventory', 'Pattern awareness', 'Inner truth'],
    color: '#38A09E',
    glow: 'rgba(56,160,158,0.35)',
  },
  {
    letter: 'E',
    name: 'Explore',
    body: 'Move into the patterns underneath. Why do you respond the way you do? What is driving the coping?',
    chips: ['Root causes', 'Nervous system', 'Human Design'],
    color: '#55B8B6',
    glow: 'rgba(85,184,182,0.3)',
  },
  {
    letter: 'A',
    name: 'Align',
    body: 'Make choices from a grounded place — aligning your life with what you actually want.',
    chips: ['Values clarity', 'Real boundaries', 'Real choices'],
    color: '#7FCFCD',
    glow: 'rgba(127,207,205,0.25)',
  },
  {
    letter: 'L',
    name: 'Lead',
    body: 'You are no longer managing your life. You are leading it — from the inside out.',
    chips: ['Integration', 'Embodiment', 'Self-leadership'],
    color: '#D4B048',
    glow: 'rgba(212,176,72,0.30)',
  },
]

export default function RealJourneySection() {
  return (
    <section
      className="relative overflow-hidden py-24 sm:py-32"
      style={{ background: '#F5F7FA' }}
    >
      {/* Subtle gradient accent */}
      <div
        className="pointer-events-none absolute inset-0"
        aria-hidden="true"
        style={{
          background:
            'radial-gradient(ellipse 50% 60% at 0% 50%, rgba(56,160,158,0.05) 0%, transparent 65%)',
        }}
      />

      <Container className="relative">

        <div className="mb-16 grid gap-8 lg:grid-cols-[1fr_1fr] lg:items-end">
          <div>
            <p className="mb-4 text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600">
              The foundation
            </p>
            <h2
              className="font-semibold text-navy-950"
              style={{ fontSize: 'clamp(2rem, 4vw, 3.25rem)', lineHeight: '1.07', letterSpacing: '-0.04em' }}
            >
              Four phases.
              <br />One transformation.
            </h2>
          </div>
          <div>
            <p className="max-w-[420px] text-[16px] leading-[1.8] text-[#666]">
              The REAL Journey is where every member begins. Each phase builds on the last —
              designed to be revisited, not rushed through.
            </p>
          </div>
        </div>

        {/* Phase cards */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {PHASES.map(({ letter, name, body, chips, color, glow }, i) => (
            <div
              key={letter}
              className="group relative flex flex-col rounded-2xl p-6 transition-all duration-300 hover:-translate-y-1"
              style={{
                background: '#FFFFFF',
                border: '1px solid rgba(0,0,0,0.06)',
                boxShadow: 'var(--fc-shadow-card)',
              }}
            >
              {/* Hover glow overlay */}
              <div
                className="pointer-events-none absolute inset-0 rounded-2xl opacity-0 transition-opacity duration-300 group-hover:opacity-100"
                style={{ background: `radial-gradient(circle at 30% 20%, ${glow.replace('0.3', '0.06')} 0%, transparent 70%)` }}
                aria-hidden="true"
              />

              {/* Phase number orb */}
              <div
                className="relative z-10 mb-5 flex h-11 w-11 items-center justify-center rounded-full text-[15px] font-bold text-white transition-shadow duration-300"
                style={{
                  background: `linear-gradient(135deg, ${color}, ${color}CC)`,
                  boxShadow: `0 0 20px ${glow}`,
                }}
              >
                {letter}
              </div>

              {/* Phase label */}
              <p
                className="relative z-10 mb-1 text-[10px] font-semibold uppercase tracking-[0.10em] text-[#BBB]"
              >
                Phase {i + 1}
              </p>
              <h3
                className="relative z-10 mb-3 text-[1.1rem] font-semibold text-navy-950"
                style={{ letterSpacing: '-0.02em' }}
              >
                {name}
              </h3>
              <p className="relative z-10 mb-4 flex-1 text-[13px] leading-[1.8] text-[#666]">
                {body}
              </p>

              {/* Chips */}
              <div className="relative z-10 flex flex-wrap gap-1.5">
                {chips.map((chip) => (
                  <span
                    key={chip}
                    className="rounded-full px-2.5 py-0.5 text-[10px] font-medium"
                    style={{
                      background: `${color}14`,
                      color: color,
                      border: `1px solid ${color}25`,
                    }}
                  >
                    {chip}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Bottom CTA */}
        <div className="mt-10 flex flex-col items-start gap-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-[14px] text-[#999]">
            Begin at Recognise. Move at your own pace. Return whenever you need to.
          </p>
          <Link
            href="/real-journey"
            className="inline-flex shrink-0 items-center gap-2 rounded-xl border border-black/10 bg-white px-5 py-2.5 text-[13px] font-semibold text-black transition-all hover:border-black/18 hover:bg-[#F8F8F8]"
            style={{ boxShadow: 'var(--fc-shadow-xs)' }}
          >
            Learn about the journey
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M3 7h8M8 4l3 3-3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </Link>
        </div>

      </Container>
    </section>
  )
}
