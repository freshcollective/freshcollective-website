import Link from 'next/link'
import Container from '@/components/layout/Container'

const PILLARS = [
  {
    number: '01',
    heading: 'A clear path through the work',
    body: 'Pathways break learning into steps you can actually follow — with reflection built in at every stage. Progress is visible. The pace is real. You always know where you are and what comes next.',
  },
  {
    number: '02',
    heading: 'Learning with other people',
    body: 'Every collective includes live gatherings, community prompts, and a shared feed. The gap between understanding something and actually living it is almost always other people.',
  },
  {
    number: '03',
    heading: 'Led by someone who knows',
    body: 'Collectives are built and run by creators who have done this work themselves. Not content libraries. Not algorithms. Real expertise shaped into a guided experience — start to finish.',
  },
]

export default function HowItWorks() {
  return (
    <section id="how-it-works" className="bg-white py-20 sm:py-28">
      <Container>

        <div className="mb-16 max-w-[560px]">
          <div className="mb-4 flex items-center gap-3">
            <div className="h-px w-8 bg-teal-400" />
            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600">
              Why it works
            </span>
          </div>
          <h2
            className="mb-5 text-navy-950"
            style={{ fontSize: 'clamp(2rem, 3.75vw, 3.25rem)', letterSpacing: '-0.04em', lineHeight: '1.07', fontWeight: 650 }}
          >
            Learning that
            <br />actually sticks.
          </h2>
          <p className="text-[15.5px] leading-[1.75] text-navy-400" style={{ maxWidth: '460px' }}>
            Most learning environments separate content from community.
            Here, structure, participation, and real expertise work together — by design.
          </p>
        </div>

        <div className="space-y-0 divide-y" style={{ borderTop: '1px solid #EEEDE9', borderBottom: '1px solid #EEEDE9' }}>
          {PILLARS.map((pillar, i) => (
            <div
              key={pillar.number}
              className="group grid gap-6 py-10 sm:grid-cols-[80px_1fr_1.5fr] sm:gap-10 sm:py-12"
            >
              <div
                className="text-[13px] font-semibold tabular-nums text-navy-200 transition-colors group-hover:text-teal-400"
                style={{ letterSpacing: '0.04em', lineHeight: '1' }}
              >
                {pillar.number}
              </div>
              <h3
                className="font-semibold leading-snug text-navy-950"
                style={{ fontSize: 'clamp(1.0625rem, 1.5vw, 1.25rem)', letterSpacing: '-0.02em' }}
              >
                {pillar.heading}
              </h3>
              <p className="text-[15px] leading-[1.78] text-navy-400">
                {pillar.body}
              </p>
            </div>
          ))}
        </div>

        <div className="mt-10 flex flex-wrap gap-3">
          <Link
            href="/spaces"
            className="inline-flex items-center rounded-xl px-6 py-3 text-[14px] font-semibold text-white transition-all hover:opacity-90 hover:-translate-y-px"
            style={{
              background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
              boxShadow: 'var(--fc-shadow-btn)',
            }}
          >
            Explore Collectives
          </Link>
          <Link
            href="/about"
            className="inline-flex items-center rounded-xl border px-6 py-3 text-[14px] font-semibold text-black transition-colors hover:bg-navy-50"
            style={{ borderColor: '#D0D8E2' }}
          >
            About the platform
          </Link>
        </div>

      </Container>
    </section>
  )
}
