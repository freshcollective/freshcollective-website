import Link from 'next/link'
import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import HomeHero from '@/components/home/HomeHero'
import InsideTheCollective from '@/components/home/InsideTheCollective'
import WhatHappensInside from '@/components/home/WhatHappensInside'

/* ─── Section 2: This is for you if ────────────────────────────────────────── */

const FOR_YOU_IF = [
  'You are exhausted by how hard you work just to stay afloat.',
  'You know something needs to change, but you cannot see where to begin.',
  'You give everything to everyone else and quietly wonder when it will be your turn.',
  'You are craving depth — not more content, more advice, or more to do.',
  'You want to feel like yourself again, and you are not sure you remember who that is.',
  'You are ready to stop coping and start actually changing.',
]

function ForYouIf() {
  return (
    <section className="py-24 sm:py-32" style={{ background: '#FDFCF9' }}>
      <Container>
        <div className="mx-auto max-w-[680px]">

          <div className="mb-12">
            <div className="mb-5 flex items-center gap-3">
              <div className="h-px w-8 bg-teal-400" />
              <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600">
                This is for you if
              </span>
            </div>
            <h2
              className="text-navy-950"
              style={{ fontSize: 'clamp(1.875rem, 3vw, 2.75rem)', letterSpacing: '-0.04em', lineHeight: '1.1' }}
            >
              You recognise yourself
              <br />
              in any of these.
            </h2>
          </div>

          <div className="space-y-4">
            {FOR_YOU_IF.map((line, i) => (
              <div
                key={i}
                className="flex items-start gap-4 rounded-xl bg-white p-5"
                style={{ border: '1px solid #EBEBEB' }}
              >
                <div
                  className="mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full text-[10px] font-bold text-white"
                  style={{ background: 'linear-gradient(135deg, #38A09E, #55B8B6)' }}
                >
                  {i + 1}
                </div>
                <p className="text-[15.5px] leading-[1.65] text-navy-700">{line}</p>
              </div>
            ))}
          </div>

          <div className="mt-10 rounded-xl p-6" style={{ background: 'rgba(56,160,158,0.05)', border: '1px solid rgba(56,160,158,0.12)' }}>
            <p className="text-[15px] leading-[1.75] text-navy-700">
              If you felt even one of those — you are in the right place.
              Fresh Collective exists for exactly this moment.
            </p>
          </div>

        </div>
      </Container>
    </section>
  )
}

/* ─── Section 3: The Shift ──────────────────────────────────────────────────── */

function TheShift() {
  return (
    <section className="bg-white py-24 sm:py-32">
      <Container>
        <div className="mx-auto max-w-[580px] text-center">

          <div className="mb-8 inline-flex items-center gap-3">
            <div className="h-px w-8 bg-teal-400" />
            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600">
              The shift
            </span>
            <div className="h-px w-8 bg-teal-400" />
          </div>

          <h2
            className="mb-8 text-navy-950"
            style={{ fontSize: 'clamp(1.75rem, 3vw, 2.625rem)', letterSpacing: '-0.04em', lineHeight: '1.15' }}
          >
            Information was never the problem.
          </h2>

          <p className="mb-6 text-[17px] leading-[1.8] text-navy-500">
            Thousands of hours of content, advice, and self-help did not move you
            because information is not transformation.
          </p>

          <p className="text-[15px] leading-[1.85] text-navy-400">
            Fresh Collective is built differently. It is a structured system with a beginning,
            a rhythm, and a community that holds you through the work — not just a library
            of things to read when you find the time.
          </p>

          <div className="mt-12 flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
            <div className="flex items-center gap-2.5 rounded-full px-4 py-2" style={{ background: '#F5F7FA', border: '1px solid #EBEBEB' }}>
              <div className="h-1.5 w-1.5 rounded-full bg-teal-400" />
              <span className="text-[13px] text-navy-500">Structured, not scattered</span>
            </div>
            <div className="flex items-center gap-2.5 rounded-full px-4 py-2" style={{ background: '#F5F7FA', border: '1px solid #EBEBEB' }}>
              <div className="h-1.5 w-1.5 rounded-full bg-teal-400" />
              <span className="text-[13px] text-navy-500">Paced, not overwhelming</span>
            </div>
            <div className="flex items-center gap-2.5 rounded-full px-4 py-2" style={{ background: '#F5F7FA', border: '1px solid #EBEBEB' }}>
              <div className="h-1.5 w-1.5 rounded-full bg-teal-400" />
              <span className="text-[13px] text-navy-500">Held, not alone</span>
            </div>
          </div>

        </div>
      </Container>
    </section>
  )
}

/* ─── Section 6: What it actually feels like ───────────────────────────────── */

const FEELS_LIKE = [
  {
    quote: 'Less noise. More clarity.',
    detail: 'A quieter relationship with the constant pressure to do more.',
  },
  {
    quote: 'Held by something bigger than willpower.',
    detail: 'Structure that carries you when motivation runs out.',
  },
  {
    quote: 'Like you stopped performing your life.',
    detail: 'And started actually living it.',
  },
]

function WhatItFeelsLike() {
  return (
    <section className="py-24 sm:py-32" style={{ background: '#FDFCF9' }}>
      <Container>
        <div className="mb-16 max-w-[480px]">
          <div className="mb-5 flex items-center gap-3">
            <div className="h-px w-8 bg-teal-400" />
            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600">
              What it actually feels like
            </span>
          </div>
          <h2
            className="text-navy-950"
            style={{ fontSize: 'clamp(1.875rem, 3vw, 2.75rem)', letterSpacing: '-0.04em', lineHeight: '1.1' }}
          >
            Not a temporary high.
            <br />A lasting shift.
          </h2>
        </div>

        <div className="grid gap-6 sm:grid-cols-3">
          {FEELS_LIKE.map(({ quote, detail }) => (
            <div
              key={quote}
              className="rounded-2xl bg-white p-8"
              style={{ border: '1px solid #EBEBEB', boxShadow: 'var(--fc-shadow-card)' }}
            >
              <p
                className="mb-3 font-semibold text-navy-950"
                style={{ fontSize: '1.1875rem', letterSpacing: '-0.02em', lineHeight: '1.3' }}
              >
                &ldquo;{quote}&rdquo;
              </p>
              <p className="text-[14.5px] leading-[1.7] text-navy-400">{detail}</p>
            </div>
          ))}
        </div>
      </Container>
    </section>
  )
}

/* ─── Section 7: The Heart ──────────────────────────────────────────────────── */

function TheHeart() {
  return (
    <section className="bg-white py-24 sm:py-32">
      <Container>
        <div className="grid items-center gap-16 lg:grid-cols-2">

          <div>
            <div className="mb-5 flex items-center gap-3">
              <div className="h-px w-8 bg-teal-400" />
              <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600">
                The Heart of the Collective
              </span>
            </div>
            <h2
              className="mb-6 text-navy-950"
              style={{ fontSize: 'clamp(1.875rem, 3vw, 2.75rem)', letterSpacing: '-0.04em', lineHeight: '1.1' }}
            >
              You are not meant to
              <br />do this alone.
            </h2>
            <p className="mb-4 text-[16.5px] leading-[1.78] text-navy-500">
              Every month, the whole Collective gathers live — not for another masterclass,
              but for real conversation. Questions without easy answers. Women holding space
              for each other through the actual work.
            </p>
            <p className="text-[15px] leading-[1.8] text-navy-400">
              The Heart is what makes Fresh Collective different. You can read every piece of
              content alone. You cannot build real change alone. That is why this exists.
            </p>
          </div>

          <div className="space-y-4">
            {[
              { icon: '◎', label: 'Monthly live gathering', desc: 'One structured call per month. Real connection, real conversation, real support.' },
              { icon: '◎', label: '42 women and growing', desc: 'A private community of women at all stages of the REAL Journey.' },
              { icon: '◎', label: 'The founder present', desc: 'Not outsourced to coaches. Lindsey shows up, every single month.' },
              { icon: '◎', label: 'Between-call community', desc: 'A place to land between sessions. To share, to ask, to be seen.' },
            ].map(({ icon, label, desc }) => (
              <div
                key={label}
                className="flex items-start gap-4 rounded-xl bg-white p-5"
                style={{ border: '1px solid #EBEBEB' }}
              >
                <span className="mt-0.5 text-[14px] text-teal-500">{icon}</span>
                <div>
                  <p className="mb-1 text-[14px] font-semibold text-navy-950">{label}</p>
                  <p className="text-[13.5px] leading-[1.6] text-navy-400">{desc}</p>
                </div>
              </div>
            ))}
          </div>

        </div>
      </Container>
    </section>
  )
}

/* ─── Section 8: Final CTA ──────────────────────────────────────────────────── */

function FinalCTA() {
  return (
    <section className="py-24 sm:py-32" style={{ background: '#FDFCF9' }}>
      <Container>
        <div className="mx-auto max-w-[580px] text-center">

          <div className="mb-8 inline-flex items-center gap-3">
            <div className="h-px w-8 bg-teal-400" />
            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600">
              Ready when you are
            </span>
            <div className="h-px w-8 bg-teal-400" />
          </div>

          <h2
            className="mb-8 text-navy-950"
            style={{ fontSize: 'clamp(2rem, 3.5vw, 3.25rem)', letterSpacing: '-0.04em', lineHeight: '1.1' }}
          >
            You can keep holding
            <br />
            it all together…
            <br />
            <span className="text-navy-500">or you can start living differently.</span>
          </h2>

          <p className="mb-14 text-[16px] leading-[1.8] text-navy-400">
            Start where you are.
            <br />
            Come inside when you&apos;re ready.
          </p>

          <div className="flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
            <Link
              href="/membership"
              className="inline-flex items-center rounded-xl px-8 py-4 text-[15px] font-semibold text-white transition-opacity hover:opacity-90"
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
              className="inline-flex items-center rounded-xl border px-8 py-4 text-[15px] font-semibold text-navy-700 transition-colors hover:bg-navy-50"
              style={{ borderColor: '#D1DCE9' }}
            >
              Start at The Entrance
            </Link>
          </div>

          <p className="mt-8 text-[13px] text-navy-400">
            AUD $39/month · No lock-in · Cancel anytime
          </p>

        </div>
      </Container>
    </section>
  )
}

/* ─── Page ──────────────────────────────────────────────────────────────────── */

export default function Home() {
  return (
    <SiteShell>
      <HomeHero />
      <ForYouIf />
      <TheShift />
      <InsideTheCollective />
      <WhatHappensInside />
      <WhatItFeelsLike />
      <TheHeart />
      <FinalCTA />
    </SiteShell>
  )
}
