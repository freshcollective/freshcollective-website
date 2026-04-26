import Link from 'next/link'
import Container from '@/components/layout/Container'

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

        {/* Cards — centre card is featured */}
        <div className="grid gap-5 sm:grid-cols-3">

          {/* Card 1: Start Here */}
          <div
            className="flex flex-col rounded-2xl bg-white p-7 transition-shadow hover:shadow-lg"
            style={{ border: '1px solid #EBEBEB', boxShadow: 'var(--fc-shadow-card)' }}
          >
            <p
              className="mb-5 text-[11px] font-semibold uppercase tracking-[0.12em]"
              style={{ color: '#38A09E' }}
            >
              Start Here
            </p>
            <h3 className="mb-4 text-[1.1875rem] font-semibold leading-snug tracking-tight text-navy-950">
              A place to begin
            </h3>
            <p className="flex-1 text-[14.5px] leading-[1.75] text-navy-400">
              When everything feels unclear, this is where you start.
              Something steady. Something you can actually return to.
            </p>
          </div>

          {/* Card 2: The Heart — featured centre */}
          <div
            className="flex flex-col rounded-2xl p-7 transition-shadow hover:shadow-xl"
            style={{
              background: 'linear-gradient(160deg, #FAFFFE 0%, #F0FAFA 100%)',
              border: '1px solid rgba(56,160,158,0.22)',
              boxShadow: '0 0 0 1px rgba(56,160,158,0.10), var(--fc-shadow-raised)',
            }}
          >
            <p
              className="mb-5 text-[11px] font-semibold uppercase tracking-[0.12em]"
              style={{ color: '#38A09E' }}
            >
              The Heart
            </p>
            <h3 className="mb-4 text-[1.1875rem] font-semibold leading-snug tracking-tight text-navy-950">
              Where it becomes real
            </h3>
            <p className="flex-1 text-[14.5px] leading-[1.75] text-navy-500">
              Live calls, shared reflections, and honest conversation.
              This is where the work starts to land.
            </p>
          </div>

          {/* Card 3: The Rooms */}
          <div
            className="flex flex-col rounded-2xl bg-white p-7 transition-shadow hover:shadow-lg"
            style={{ border: '1px solid #EBEBEB', boxShadow: 'var(--fc-shadow-card)' }}
          >
            <p
              className="mb-5 text-[11px] font-semibold uppercase tracking-[0.12em]"
              style={{ color: '#C9A83C' }}
            >
              The Rooms
            </p>
            <h3 className="mb-4 text-[1.1875rem] font-semibold leading-snug tracking-tight text-navy-950">
              Spaces to go deeper
            </h3>
            <p className="flex-1 text-[14.5px] leading-[1.75] text-navy-400">
              As things begin to shift, you can move into the Rooms —
              each one holding a different part of your growth.
            </p>
          </div>

        </div>

        {/* Bottom CTA */}
        <div className="mt-14 flex flex-col items-center gap-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-[15px] text-navy-400">
            AUD $39/month · Cancel anytime
          </p>
          <div className="flex flex-wrap gap-3">
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
            {/* /entrance — dedicated onboarding welcome route, not yet built; linking to /real-journey in the meantime */}
            <Link
              href="/real-journey"
              className="inline-flex items-center rounded-xl border px-7 py-3.5 text-[15px] font-semibold text-navy-700 transition-colors hover:bg-navy-50"
              style={{ borderColor: '#D1DCE9' }}
            >
              Start at The Entrance
            </Link>
          </div>
        </div>

      </Container>
    </section>
  )
}
