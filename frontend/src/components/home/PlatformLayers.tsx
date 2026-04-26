import Container from '@/components/layout/Container'

export default function PlatformLayers() {
  return (
    <section className="bg-white py-24 sm:py-32">
      <Container>

        <div className="mb-16 grid gap-8 lg:grid-cols-[1fr_1fr] lg:items-end">
          <div>
            <p className="mb-4 text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600">
              How it works
            </p>
            <h2
              className="font-semibold text-navy-950"
              style={{ fontSize: 'clamp(2rem, 4vw, 3.25rem)', lineHeight: '1.07', letterSpacing: '-0.04em' }}
            >
              One structure.
              <br />Three layers.
            </h2>
          </div>
          <p className="max-w-[440px] text-[16px] leading-[1.8] text-[#666]">
            Everything inside Fresh Collective is designed to work together — not as separate
            courses, but as a connected system that builds on itself over time.
          </p>
        </div>

        {/* Card grid: REAL spans full, then 2-col below */}
        <div className="grid gap-4 md:grid-cols-2">

          {/* REAL Journey — full width */}
          <div
            className="group relative overflow-hidden rounded-2xl p-7 transition-all duration-300 hover:-translate-y-0.5 md:col-span-2"
            style={{
              background: 'linear-gradient(130deg, #EAF7F7 0%, #F8FDFD 100%)',
              border: '1px solid rgba(56,160,158,0.12)',
              boxShadow: 'var(--fc-shadow-card)',
            }}
          >
            <div className="pointer-events-none absolute -right-16 -top-16 h-64 w-64 rounded-full opacity-50"
              style={{ background: 'radial-gradient(circle, rgba(56,160,158,0.15) 0%, transparent 65%)' }}
              aria-hidden="true"
            />

            <div className="flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
              <div className="flex-1">
                <div className="mb-4 flex items-center gap-2.5">
                  <span
                    className="rounded-full px-3 py-1 text-[11px] font-semibold text-teal-700"
                    style={{ background: 'rgba(56,160,158,0.10)', border: '1px solid rgba(56,160,158,0.20)' }}
                  >
                    01 · Foundation · Free access
                  </span>
                </div>
                <h3
                  className="mb-3 font-semibold text-navy-950"
                  style={{ fontSize: 'clamp(1.3rem, 2vw, 1.6rem)', letterSpacing: '-0.03em' }}
                >
                  REAL Journey
                </h3>
                <p className="max-w-[480px] text-[15px] leading-[1.8] text-[#555]">
                  The foundation every member begins with. Four phases — Recognise, Explore, Align,
                  Lead — designed to be bite-sized, stabilising, and easy to return to.
                </p>
              </div>
              <div className="flex flex-wrap gap-2 sm:flex-nowrap sm:flex-col sm:items-end">
                {['Recognise', 'Explore', 'Align', 'Lead'].map((phase, i) => (
                  <span
                    key={phase}
                    className="rounded-full px-4 py-1.5 text-[12px] font-semibold transition-all"
                    style={
                      i === 0
                        ? { background: '#38A09E', color: '#fff', boxShadow: '0 2px 12px rgba(56,160,158,0.35)' }
                        : { background: 'rgba(56,160,158,0.08)', color: '#246B6A', border: '1px solid rgba(56,160,158,0.18)' }
                    }
                  >
                    {phase}
                  </span>
                ))}
              </div>
            </div>
          </div>

          {/* The Heart */}
          <div
            className="group relative overflow-hidden rounded-2xl p-7 transition-all duration-300 hover:-translate-y-1"
            style={{
              background: 'linear-gradient(130deg, #FFFBF0 0%, #FFFDF8 100%)',
              border: '1px solid rgba(245,158,11,0.10)',
              boxShadow: 'var(--fc-shadow-card)',
            }}
          >
            <div className="mb-4 flex items-center gap-2.5">
              <span
                className="rounded-full px-3 py-1 text-[11px] font-semibold text-amber-700"
                style={{ background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.18)' }}
              >
                02 · The Heart
              </span>
              <div className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-400" />
                <span className="text-[11px] font-medium text-amber-600">Monthly</span>
              </div>
            </div>
            <h3
              className="mb-3 font-semibold text-navy-950"
              style={{ fontSize: 'clamp(1.2rem, 1.8vw, 1.4rem)', letterSpacing: '-0.03em' }}
            >
              The Heart
            </h3>
            <p className="text-[14px] leading-[1.8] text-[#555]">
              Monthly live calls, community prompts, and integration threads. Real connection
              with women walking the same path — at the same time as you.
            </p>
          </div>

          {/* The Rooms */}
          <div
            className="group relative overflow-hidden rounded-2xl p-7 transition-all duration-300 hover:-translate-y-1"
            style={{
              background: 'linear-gradient(130deg, #EEF2F8 0%, #F5F8FC 100%)',
              border: '1px solid rgba(30,51,84,0.08)',
              boxShadow: 'var(--fc-shadow-card)',
            }}
          >
            <div className="mb-4 flex items-center gap-2.5">
              <span
                className="rounded-full px-3 py-1 text-[11px] font-semibold text-navy-700"
                style={{ background: 'rgba(30,51,84,0.06)', border: '1px solid rgba(30,51,84,0.12)' }}
              >
                03 · The Rooms
              </span>
            </div>
            <h3
              className="mb-3 font-semibold text-navy-950"
              style={{ fontSize: 'clamp(1.2rem, 1.8vw, 1.4rem)', letterSpacing: '-0.03em' }}
            >
              The Rooms
            </h3>
            <p className="text-[14px] leading-[1.8] text-[#555]">
              Once you have your foundation, The Rooms take you deeper — into nervous
              system work, Human Design, and personal leadership.
            </p>
          </div>

        </div>
      </Container>
    </section>
  )
}
