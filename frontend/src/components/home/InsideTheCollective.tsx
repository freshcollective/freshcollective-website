import Link from 'next/link'
import Container from '@/components/layout/Container'

const PILLARS = [
  {
    num: '01',
    tag: 'Foundation',
    name: 'The REAL Journey',
    desc: 'A four-phase programme to help you reconnect with yourself, expand your perspective, act from your values, and live with intention. Free to begin.',
    detail: ['Reconnect · Expand · Act · Live', '4 phases · Self-paced · Free to start'],
    color: '#38A09E',
    bgAccent: 'rgba(56,160,158,0.05)',
    borderAccent: 'rgba(56,160,158,0.15)',
    href: '/real-journey',
    cta: 'Start free',
  },
  {
    num: '02',
    tag: 'Deepening',
    name: 'The Rooms',
    desc: 'Focused pathways to go deeper in the areas that matter most — work and money, relationships, body and health, purpose and creative life.',
    detail: ['4 Rooms · Choose your path', 'Included in membership'],
    color: '#C9A83C',
    bgAccent: 'rgba(201,168,60,0.05)',
    borderAccent: 'rgba(201,168,60,0.15)',
    href: '/membership',
    cta: 'Explore membership',
  },
  {
    num: '03',
    tag: 'Community',
    name: 'The Heart',
    desc: 'Monthly live calls and a community of women walking alongside you. Real connection, not just content. The part that holds everything together.',
    detail: ['Monthly live calls · Private community', '42 women and growing'],
    color: '#38A09E',
    bgAccent: 'rgba(56,160,158,0.05)',
    borderAccent: 'rgba(56,160,158,0.15)',
    href: '/membership',
    cta: 'Join the Heart',
  },
]

export default function InsideTheCollective() {
  return (
    <section id="inside-the-collective" className="py-24 sm:py-32" style={{ background: '#FDFCF9' }}>
      <Container>

        {/* Heading */}
        <div className="mb-16 max-w-[520px]">
          <div className="mb-5 flex items-center gap-3">
            <div className="h-px w-8 bg-teal-400" />
            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600">
              Inside the Collective
            </span>
          </div>
          <h2
            className="mb-4 text-navy-950"
            style={{ fontSize: 'clamp(2rem, 3.5vw, 3rem)', letterSpacing: '-0.04em', lineHeight: '1.08' }}
          >
            One system. Three layers.
            <br />
            All working together.
          </h2>
          <p className="text-[16px] leading-[1.75] text-navy-400">
            Most programmes give you content. Fresh Collective gives you a structure —
            a beginning, a rhythm, and women beside you through it all.
          </p>
        </div>

        {/* Cards */}
        <div className="grid gap-5 sm:grid-cols-3">
          {PILLARS.map(({ num, tag, name, desc, detail, color, bgAccent, borderAccent, href, cta }) => (
            <div
              key={num}
              className="group flex flex-col rounded-2xl bg-white p-7 transition-shadow hover:shadow-lg"
              style={{
                border: '1px solid #EBEBEB',
                boxShadow: 'var(--fc-shadow-card)',
              }}
            >
              <div className="mb-6 flex items-center gap-3">
                <div
                  className="flex h-8 w-8 items-center justify-center rounded-lg text-[11px] font-bold"
                  style={{ background: bgAccent, border: `1px solid ${borderAccent}`, color }}
                >
                  {num}
                </div>
                <span
                  className="text-[11px] font-semibold uppercase tracking-[0.1em]"
                  style={{ color }}
                >
                  {tag}
                </span>
              </div>

              <h3 className="mb-3 text-[1.1875rem] font-semibold leading-tight tracking-tight text-navy-950">
                {name}
              </h3>

              <p className="mb-6 flex-1 text-[14.5px] leading-[1.7] text-navy-400">
                {desc}
              </p>

              <div className="mb-6 space-y-1.5">
                {detail.map((d) => (
                  <div key={d} className="flex items-center gap-2">
                    <div className="h-1 w-1 flex-shrink-0 rounded-full" style={{ background: color }} />
                    <span className="text-[12px] text-navy-400">{d}</span>
                  </div>
                ))}
              </div>

              <Link
                href={href}
                className="inline-flex items-center gap-1.5 text-[13px] font-semibold transition-opacity hover:opacity-70"
                style={{ color }}
              >
                {cta}
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
                  <path d="M3 7h8M8 4l3 3-3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </Link>
            </div>
          ))}
        </div>

        {/* Bottom CTA */}
        <div className="mt-14 flex flex-col items-center gap-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-[15px] text-navy-400">
            AUD $39/month · Cancel anytime · REAL Journey free to begin
          </p>
          <Link
            href="/membership"
            className="inline-flex items-center rounded-xl px-7 py-3.5 text-[15px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{
              background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
              boxShadow: 'var(--fc-shadow-btn)',
            }}
          >
            Step inside the Collective
          </Link>
        </div>

      </Container>
    </section>
  )
}
