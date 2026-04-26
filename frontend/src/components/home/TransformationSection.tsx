import Container from '@/components/layout/Container'

const OUTCOMES = [
  {
    headline: 'Energy that doesn\'t depend on perfect conditions',
    body: 'Learn to sustain yourself from the inside — not through willpower or more discipline.',
  },
  {
    headline: 'Clarity without forcing another reinvention',
    body: 'Understand what\'s actually driving the fog, so you can move through it once.',
  },
  {
    headline: 'Boundaries that hold without constant justification',
    body: 'Stop explaining yourself to exhaustion. Lead from values instead.',
  },
  {
    headline: 'Decisions made from values, not fear',
    body: 'Move from reactive coping to grounded, intentional choices.',
  },
  {
    headline: 'A body that stops running on fumes',
    body: 'Reconnect with what you need — and build a life your nervous system can sustain.',
  },
  {
    headline: 'A life you lead instead of manage',
    body: 'Integration over information. Embodied change over another plan that doesn\'t stick.',
  },
]

export default function TransformationSection() {
  return (
    <section
      className="relative overflow-hidden py-24 sm:py-32"
      style={{ background: 'linear-gradient(180deg, #0D1F35 0%, #152236 100%)' }}
    >
      {/* Subtle background glow */}
      <div
        className="pointer-events-none absolute inset-0"
        aria-hidden="true"
        style={{
          background:
            'radial-gradient(ellipse 60% 50% at 50% 100%, rgba(56,160,158,0.10) 0%, transparent 70%)',
        }}
      />

      <Container className="relative">

        {/* Header */}
        <div className="mb-16 max-w-[540px]">
          <p
            className="mb-4 text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-500"
          >
            What shifts
          </p>
          <h2
            className="font-semibold text-white"
            style={{ fontSize: 'clamp(2rem, 4vw, 3.25rem)', lineHeight: '1.07', letterSpacing: '-0.04em' }}
          >
            What changes when
            <br />
            this starts working.
          </h2>
        </div>

        {/* Outcome cards grid */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {OUTCOMES.map(({ headline, body }, i) => (
            <OutcomeCard key={i} index={i} headline={headline} body={body} />
          ))}
        </div>

      </Container>
    </section>
  )
}

function OutcomeCard({ headline, body, index }: { headline: string; body: string; index: number }) {
  const isGold = index === 5
  const accentColor = isGold ? 'rgba(212,176,72,0.5)' : 'rgba(56,160,158,0.5)'
  const accentBg = isGold ? 'rgba(212,176,72,0.08)' : 'rgba(56,160,158,0.06)'
  const accentBorder = isGold ? 'rgba(212,176,72,0.14)' : 'rgba(56,160,158,0.10)'

  return (
    <div
      className="group relative flex flex-col gap-3 rounded-2xl p-6 transition-all duration-300"
      style={{
        background: 'rgba(255,255,255,0.03)',
        border: '1px solid rgba(255,255,255,0.07)',
        boxShadow: 'var(--fc-shadow-card-dark)',
      }}
    >
      {/* Hover reveal: subtle teal/gold tint */}
      <div
        className="pointer-events-none absolute inset-0 rounded-2xl opacity-0 transition-opacity duration-300 group-hover:opacity-100"
        style={{ background: accentBg, border: `1px solid ${accentBorder}` }}
        aria-hidden="true"
      />

      {/* Number dot */}
      <div
        className="relative z-10 flex h-7 w-7 items-center justify-center rounded-full text-[11px] font-bold"
        style={{ background: accentBg, color: accentColor, border: `1px solid ${accentBorder}` }}
      >
        {String(index + 1).padStart(2, '0')}
      </div>

      <h3
        className="relative z-10 font-semibold leading-[1.3] text-white"
        style={{ fontSize: 'clamp(1rem, 1.5vw, 1.1rem)' }}
      >
        {headline}
      </h3>
      <p className="relative z-10 text-[14px] leading-[1.75] text-navy-300">{body}</p>
    </div>
  )
}
