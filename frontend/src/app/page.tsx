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
    <section className="py-16 sm:py-24" style={{ background: '#FDFCF9' }}>
      <Container>
        <div className="mx-auto max-w-[640px]">

          <div className="mb-8">
            <div className="mb-3 flex items-center gap-3">
              <div className="h-px w-8 bg-teal-400" />
              <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600">
                This is for you if
              </span>
            </div>
            <h2
              className="text-navy-950"
              style={{ fontSize: 'clamp(1.75rem, 3vw, 2.625rem)', letterSpacing: '-0.04em', lineHeight: '1.1' }}
            >
              You recognise yourself
              <br />in any of these.
            </h2>
          </div>

          <div className="divide-y divide-[#EEEDE9]" style={{ borderTop: '1px solid #EEEDE9', borderBottom: '1px solid #EEEDE9' }}>
            {FOR_YOU_IF.map((line, i) => (
              <div key={i} className="flex items-baseline gap-4 py-4">
                <div className="mt-[6px] h-1.5 w-1.5 flex-shrink-0 rounded-full bg-teal-400" />
                <p className="text-[15.5px] leading-[1.65] text-navy-700">{line}</p>
              </div>
            ))}
          </div>

          <div
            className="mt-8 rounded-2xl p-6"
            style={{ background: 'rgba(56,160,158,0.04)', border: '1px solid rgba(56,160,158,0.11)' }}
          >
            <p className="text-[15px] leading-[1.75] text-navy-600">
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
    <section className="bg-white py-16 sm:py-24">
      <Container>
        <div className="mx-auto max-w-[560px] text-center">

          <div className="mb-6 inline-flex items-center gap-3">
            <div className="h-px w-8 bg-teal-400" />
            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600">
              The shift
            </span>
            <div className="h-px w-8 bg-teal-400" />
          </div>

          <h2
            className="mb-5 text-navy-950"
            style={{ fontSize: 'clamp(1.75rem, 3vw, 2.625rem)', letterSpacing: '-0.04em', lineHeight: '1.12' }}
          >
            Information was never the problem.
          </h2>

          <p className="mb-4 text-[16.5px] leading-[1.78] text-navy-500">
            Thousands of hours of content, advice, and self-help did not move you
            because information is not transformation.
          </p>

          <p className="text-[15px] leading-[1.82] text-navy-400">
            Fresh Collective is built differently. It is a structured system with a beginning,
            a rhythm, and a community that holds you through the work — not just a library
            of things to read when you find the time.
          </p>

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
    <section className="py-16 sm:py-24" style={{ background: '#FDFCF9' }}>
      <Container>
        <div className="mb-10 max-w-[460px]">
          <div className="mb-3 flex items-center gap-3">
            <div className="h-px w-8 bg-teal-400" />
            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600">
              What it actually feels like
            </span>
          </div>
          <h2
            className="text-navy-950"
            style={{ fontSize: 'clamp(1.75rem, 3vw, 2.5rem)', letterSpacing: '-0.04em', lineHeight: '1.1' }}
          >
            Not a temporary high.
            <br />A lasting shift.
          </h2>
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          {FEELS_LIKE.map(({ quote, detail }) => (
            <div
              key={quote}
              className="rounded-2xl bg-white p-6"
              style={{
                border: '1px solid rgba(0,0,0,0.07)',
                boxShadow: '0 1px 3px rgba(0,0,0,0.04), 0 8px 20px rgba(0,0,0,0.04)',
              }}
            >
              <p
                className="mb-2.5 font-semibold text-navy-950"
                style={{ fontSize: '1.125rem', letterSpacing: '-0.02em', lineHeight: '1.35' }}
              >
                {quote}
              </p>
              <p className="text-[14px] leading-[1.7] text-navy-400">{detail}</p>
            </div>
          ))}
        </div>
      </Container>
    </section>
  )
}

/* ─── Section 7: The Heart ──────────────────────────────────────────────────── */

const HEART_FEATURES = [
  { label: 'Monthly live gathering', desc: 'One structured call per month. Real connection, real conversation, real support.' },
  { label: '42 women and growing', desc: 'A private community of women at all stages of their journey.' },
  { label: 'The founder present', desc: 'Not outsourced to coaches. Lindsey shows up, every single month.' },
  { label: 'Between-call community', desc: 'A place to land between sessions. To share, to ask, to be seen.' },
]

function TheHeart() {
  return (
    <section className="bg-white py-16 sm:py-24">
      <Container>
        <div className="grid items-start gap-12 lg:grid-cols-2 lg:gap-16">

          <div>
            <div className="mb-3 flex items-center gap-3">
              <div className="h-px w-8 bg-teal-400" />
              <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600">
                The Heart of the Collective
              </span>
            </div>
            <h2
              className="mb-5 text-navy-950"
              style={{ fontSize: 'clamp(1.75rem, 3vw, 2.625rem)', letterSpacing: '-0.04em', lineHeight: '1.1' }}
            >
              You are not meant to
              <br />do this alone.
            </h2>
            <p className="mb-4 text-[16px] leading-[1.78] text-navy-500">
              Every month, the whole Collective gathers live — not for another masterclass,
              but for real conversation. Questions without easy answers. Women holding space
              for each other through the actual work.
            </p>
            <p className="text-[14.5px] leading-[1.78] text-navy-400">
              The Heart is what makes Fresh Collective different. You can read every piece of
              content alone. You cannot build real change alone. That is why this exists.
            </p>
          </div>

          <div className="divide-y" style={{ borderTop: '1px solid #EEEDE9', borderBottom: '1px solid #EEEDE9' }}>
            {HEART_FEATURES.map(({ label, desc }) => (
              <div key={label} className="flex items-start gap-4 py-5">
                <div className="mt-[5px] h-1.5 w-1.5 flex-shrink-0 rounded-full bg-teal-400" />
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
    <section className="py-16 sm:py-24" style={{ background: '#FDFCF9' }}>
      <Container>
        <div className="mx-auto max-w-[560px] text-center">

          <div className="mb-6 inline-flex items-center gap-3">
            <div className="h-px w-8 bg-teal-400" />
            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600">
              Ready when you are
            </span>
            <div className="h-px w-8 bg-teal-400" />
          </div>

          <h2
            className="mb-5 text-navy-950"
            style={{ fontSize: 'clamp(1.875rem, 3.5vw, 3rem)', letterSpacing: '-0.04em', lineHeight: '1.1' }}
          >
            You can keep holding
            <br />it all together…
            <br />
            <span className="text-navy-400">or you can start living differently.</span>
          </h2>

          <p className="mb-10 text-[16px] leading-[1.78] text-navy-500">
            Start where you are.
            <br />
            Come inside when you&apos;re ready.
          </p>

          <div className="flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
            <Link
              href="/membership"
              className="inline-flex items-center rounded-xl px-8 py-3.5 text-[15px] font-semibold text-white transition-opacity hover:opacity-90"
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
              className="inline-flex items-center rounded-xl border px-8 py-3.5 text-[15px] font-semibold text-navy-700 transition-colors hover:bg-navy-50"
              style={{ borderColor: '#C8D5E3' }}
            >
              Start at The Entrance
            </Link>
          </div>

          <p className="mt-6 text-[13px] text-navy-400">
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
