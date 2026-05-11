import Link from 'next/link'
import Container from '@/components/layout/Container'

const LAYERS = [
  {
    eyebrow: 'Foundation',
    eyebrowStyle: { color: '#38A09E' } as React.CSSProperties,
    title: 'Guided pathways',
    body: 'Structured learning you move through at your own pace — with reflection built in at every step. Start with the REAL Journey and go deeper from there.',
    borderStyle: { border: '1px solid rgba(56,160,158,0.20)', background: 'linear-gradient(160deg, #FAFFFE 0%, #EEF9F8 100%)' },
  },
  {
    eyebrow: 'Community',
    eyebrowStyle: { color: '#38A09E' } as React.CSSProperties,
    title: 'Where it becomes real',
    body: 'Live calls, shared reflections, and honest conversation. Real women, real support. The work lands differently when you do it together.',
    borderStyle: { border: '1px solid rgba(0,0,0,0.07)', background: '#ffffff' },
  },
  {
    eyebrow: 'Spaces',
    eyebrowStyle: { color: '#B8922A' } as React.CSSProperties,
    title: 'Rooms to go deeper',
    body: 'As things begin to shift, you move into Spaces — each one focused on a different dimension of your growth. Led by creators who know the work.',
    borderStyle: { border: '1px solid rgba(0,0,0,0.07)', background: '#ffffff' },
  },
]

export default function InsideTheCollective() {
  return (
    <section id="inside-the-collective" className="py-16 sm:py-24" style={{ background: '#FDFCF9' }}>
      <Container>

        <div className="mb-10 max-w-[520px]">
          <div className="mb-3 flex items-center gap-3">
            <div className="h-px w-8 bg-teal-400" />
            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600">
              Inside the Collective
            </span>
          </div>
          <h2
            className="mb-3 text-navy-950"
            style={{ fontSize: 'clamp(1.875rem, 3.5vw, 2.875rem)', letterSpacing: '-0.04em', lineHeight: '1.08' }}
          >
            One system. Three layers.
            <br />
            All working together.
          </h2>
          <p className="text-[15.5px] leading-[1.7] text-navy-400">
            Most programmes give you content. Fresh Collective gives you a structure —
            a beginning, a rhythm, and people beside you through it all.
          </p>
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          {LAYERS.map((layer) => (
            <div
              key={layer.title}
              className="flex flex-col rounded-2xl p-6 transition-all hover:-translate-y-0.5 hover:shadow-lg"
              style={{
                ...layer.borderStyle,
                boxShadow: '0 1px 3px rgba(0,0,0,0.04), 0 8px 20px rgba(0,0,0,0.04)',
              }}
            >
              <p
                className="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em]"
                style={layer.eyebrowStyle}
              >
                {layer.eyebrow}
              </p>
              <h3 className="mb-3 text-[1.125rem] font-semibold leading-snug tracking-tight text-navy-950">
                {layer.title}
              </h3>
              <p className="flex-1 text-[14px] leading-[1.72] text-navy-400">{layer.body}</p>
            </div>
          ))}
        </div>

        <div className="mt-10 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-[14px] text-navy-400">AUD $39/month · Cancel anytime</p>
          <div className="flex flex-wrap gap-3">
            <Link
              href="/membership"
              className="inline-flex items-center rounded-xl px-6 py-3 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
              style={{
                background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                boxShadow: 'var(--fc-shadow-btn)',
              }}
            >
              Step inside the Collective
            </Link>
            <Link
              href="/signup"
              className="inline-flex items-center rounded-xl border px-6 py-3 text-[14px] font-semibold text-navy-700 transition-colors hover:bg-navy-50"
              style={{ borderColor: '#C8D5E3' }}
            >
              Create a free account
            </Link>
          </div>
        </div>

      </Container>
    </section>
  )
}
