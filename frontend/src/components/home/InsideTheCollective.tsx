import Link from 'next/link'
import Container from '@/components/layout/Container'

export default function InsideTheCollective() {
  return (
    <section id="inside-the-collective" className="py-16 sm:py-24" style={{ background: '#FDFCF9' }}>
      <Container>

        {/* Heading */}
        <div className="mb-10 max-w-[500px]">
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
            a beginning, a rhythm, and women beside you through it all.
          </p>
        </div>

        {/* Cards — centre card featured */}
        <div className="grid gap-4 sm:grid-cols-3">

          {/* Card 1: Start Here */}
          <div
            className="flex flex-col rounded-2xl bg-white p-6 transition-all hover:-translate-y-0.5 hover:shadow-lg"
            style={{
              border: '1px solid rgba(0,0,0,0.07)',
              boxShadow: '0 1px 3px rgba(0,0,0,0.04), 0 8px 20px rgba(0,0,0,0.04)',
            }}
          >
            <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600">
              Start Here
            </p>
            <h3 className="mb-3 text-[1.125rem] font-semibold leading-snug tracking-tight text-navy-950">
              A place to begin
            </h3>
            <p className="flex-1 text-[14px] leading-[1.72] text-navy-400">
              When everything feels unclear, this is where you start.
              Something steady. Something you can actually return to.
            </p>
          </div>

          {/* Card 2: The Heart — featured */}
          <div
            className="flex flex-col rounded-2xl p-6 transition-all hover:-translate-y-0.5 hover:shadow-xl"
            style={{
              background: 'linear-gradient(160deg, #FAFFFE 0%, #EEF9F8 100%)',
              border: '1px solid rgba(56,160,158,0.20)',
              boxShadow: '0 1px 3px rgba(56,160,158,0.06), 0 8px 24px rgba(56,160,158,0.08), 0 20px 48px rgba(56,160,158,0.05)',
            }}
          >
            <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600">
              The Heart
            </p>
            <h3 className="mb-3 text-[1.125rem] font-semibold leading-snug tracking-tight text-navy-950">
              Where it becomes real
            </h3>
            <p className="flex-1 text-[14px] leading-[1.72] text-navy-500">
              Live calls, shared reflections, and honest conversation.
              This is where the work starts to land.
            </p>
          </div>

          {/* Card 3: The Rooms */}
          <div
            className="flex flex-col rounded-2xl bg-white p-6 transition-all hover:-translate-y-0.5 hover:shadow-lg"
            style={{
              border: '1px solid rgba(0,0,0,0.07)',
              boxShadow: '0 1px 3px rgba(0,0,0,0.04), 0 8px 20px rgba(0,0,0,0.04)',
            }}
          >
            <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em]" style={{ color: '#B8922A' }}>
              The Rooms
            </p>
            <h3 className="mb-3 text-[1.125rem] font-semibold leading-snug tracking-tight text-navy-950">
              Spaces to go deeper
            </h3>
            <p className="flex-1 text-[14px] leading-[1.72] text-navy-400">
              As things begin to shift, you can move into the Rooms —
              each one holding a different part of your growth.
            </p>
          </div>

        </div>

        {/* Bottom CTA */}
        <div className="mt-10 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-[14px] text-navy-400">
            AUD $39/month · Cancel anytime
          </p>
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
            {/* /entrance — dedicated onboarding welcome route, not yet built; linking to /real-journey in the meantime */}
            <Link
              href="/real-journey"
              className="inline-flex items-center rounded-xl border px-6 py-3 text-[14px] font-semibold text-navy-700 transition-colors hover:bg-navy-50"
              style={{ borderColor: '#C8D5E3' }}
            >
              Start at The Entrance
            </Link>
          </div>
        </div>

      </Container>
    </section>
  )
}
