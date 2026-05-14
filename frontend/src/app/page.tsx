import Link from 'next/link'
import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import HomeHero from '@/components/home/HomeHero'

/* ─── Dual Intent ───────────────────────────────────────────────────────────── */

function DualIntent() {
  return (
    <section
      className="py-20 sm:py-28"
      style={{ background: '#F5F3EF' }}
    >
      <Container>

        {/* Section heading */}
        <div className="mb-14 sm:mb-16 max-w-[600px]">
          <h2
            className="mb-4 text-navy-950"
            style={{ fontSize: 'clamp(1.75rem, 3vw, 2.5rem)', letterSpacing: '-0.04em', lineHeight: '1.1', fontWeight: 650 }}
          >
            Two ways forward.
          </h2>
          <p
            style={{ fontSize: '16px', lineHeight: '1.78', color: 'rgba(12,24,38,0.50)', maxWidth: '480px' }}
          >
            Join a collective shaped around what you&apos;re ready to explore — or build one around the work you&apos;re here to share.
          </p>
        </div>

        {/* Columns */}
        <div className="grid gap-0 sm:grid-cols-2" style={{ borderTop: '1px solid rgba(12,24,38,0.08)' }}>

          <div
            className="py-10 sm:py-12 sm:pr-16"
            style={{ borderBottom: '1px solid rgba(12,24,38,0.06)' }}
          >
            <p
              className="mb-4 text-navy-950"
              style={{ fontSize: '11px', fontWeight: 650, letterSpacing: '0.16em', textTransform: 'uppercase', color: 'rgba(56,160,158,0.80)' }}
            >
              For people ready to grow
            </p>
            <p className="mb-7 text-[15.5px] leading-[1.80]" style={{ color: 'rgba(12,24,38,0.56)' }}>
              Find guided collectives built around real practice, shared conversation, and ideas that move into everyday life.
            </p>
            <Link
              href="/spaces"
              className="text-[14px] font-semibold transition-opacity hover:opacity-60"
              style={{ color: '#38A09E', letterSpacing: '-0.01em' }}
            >
              Explore Collectives →
            </Link>
          </div>

          <div
            className="py-10 sm:py-12 sm:pl-16"
            style={{
              borderLeft: '1px solid rgba(12,24,38,0.08)',
              borderBottom: '1px solid rgba(12,24,38,0.06)',
            }}
          >
            <p
              className="mb-4"
              style={{ fontSize: '11px', fontWeight: 650, letterSpacing: '0.16em', textTransform: 'uppercase', color: 'rgba(140,100,30,0.75)' }}
            >
              For people ready to guide
            </p>
            <p className="mb-7 text-[15.5px] leading-[1.80]" style={{ color: 'rgba(12,24,38,0.56)' }}>
              Build an intentional collective around your work, your questions, and the change you want to help people practise.
            </p>
            <Link
              href="/signup"
              className="text-[14px] font-semibold transition-opacity hover:opacity-60"
              style={{ color: '#9A7420', letterSpacing: '-0.01em' }}
            >
              Build a Collective →
            </Link>
          </div>

        </div>

      </Container>
    </section>
  )
}

/* ─── Ecosystem Statement ───────────────────────────────────────────────────── */

function EcosystemStatement() {
  return (
    <section
      className="py-16 sm:py-20"
      style={{ background: '#FDFCF9', borderTop: '1px solid rgba(0,0,0,0.04)' }}
    >
      <Container>
        <div className="max-w-[680px]">
          <h2
            className="mb-5 text-navy-950"
            style={{ fontSize: 'clamp(2rem, 4vw, 3.5rem)', letterSpacing: '-0.04em', lineHeight: '1.08', fontWeight: 650 }}
          >
            Not a product.{' '}
            <span style={{ color: 'rgba(12,24,38,0.28)', fontStyle: 'italic' }}>
              An ecosystem.
            </span>
          </h2>
          <p className="text-[16px] leading-[1.82] text-navy-500" style={{ maxWidth: '500px' }}>
            One foundation. A live community layer. Deepening pathways — designed to
            work together as a connected system, not as separate courses you buy and forget.
          </p>
        </div>
      </Container>
    </section>
  )
}

/* ─── Fresh Ideas (dark) ────────────────────────────────────────────────────── */

function FreshIdeas() {
  return (
    <section
      className="relative overflow-hidden py-24 sm:py-32"
      style={{ background: '#0C1F1F' }}
    >
      <div className="pointer-events-none absolute inset-0" aria-hidden="true">
        <div style={{
          position: 'absolute', top: '-20%', right: '-10%',
          width: '700px', height: '700px', borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(56,160,158,0.10) 0%, transparent 60%)',
          filter: 'blur(80px)',
        }} />
      </div>

      <Container className="relative">
        <div className="grid items-center gap-14 sm:grid-cols-[55%_45%] sm:gap-10">

          <div>
            <div className="mb-8 flex items-center gap-3">
              <div className="h-px w-8" style={{ background: 'rgba(85,184,182,0.35)' }} />
              <span
                className="text-[11px] font-semibold uppercase tracking-[0.14em]"
                style={{ color: 'rgba(255,255,255,0.28)' }}
              >
                A different kind of learning
              </span>
            </div>

            <h2
              className="mb-8 text-white"
              style={{ fontSize: 'clamp(2.25rem, 4.5vw, 4rem)', letterSpacing: '-0.04em', lineHeight: '1.07', fontWeight: 650 }}
            >
              Fresh ideas need
              <br />
              <span style={{ color: 'rgba(255,255,255,0.28)' }}>spaces to grow.</span>
            </h2>

            <p
              className="mb-12 text-[16px] leading-[1.88]"
              style={{ color: 'rgba(255,255,255,0.46)', maxWidth: '440px' }}
            >
              We do not believe in passive consumption. Inside Fresh Collective,
              you are always in motion — reflecting, connecting, integrating — with
              enough structure to hold you and enough space to breathe.
            </p>

            <div
              className="grid grid-cols-3 gap-6"
              style={{ borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: '2.5rem' }}
            >
              {[
                { stat: '4', label: 'REAL phases' },
                { stat: '1×', label: 'Live call monthly', gold: true },
                { stat: '∞', label: 'Your pace' },
              ].map(({ stat, label, gold }) => (
                <div key={label}>
                  <div
                    className="mb-1 font-semibold"
                    style={{
                      fontSize: 'clamp(1.75rem, 3vw, 2.5rem)',
                      letterSpacing: '-0.04em',
                      lineHeight: '1',
                      color: gold ? '#D4B048' : 'rgba(255,255,255,0.88)',
                    }}
                  >
                    {stat}
                  </div>
                  <div
                    className="text-[12px] font-medium uppercase tracking-[0.10em]"
                    style={{ color: 'rgba(255,255,255,0.28)' }}
                  >
                    {label}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Documentary artifacts */}
          <div className="relative hidden sm:block" style={{ height: '420px' }}>

            <div
              className="absolute rounded-xl bg-white p-5"
              style={{
                width: '215px', bottom: '28px', left: '0',
                transform: 'rotate(-3.5deg)',
                boxShadow: '0 20px 60px rgba(0,0,0,0.50)',
              }}
            >
              <div className="mb-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-teal-600">
                REAL Journey · Phase 1
              </div>
              <div className="mb-3 text-navy-950" style={{ fontSize: '13.5px', fontWeight: 620, letterSpacing: '-0.02em' }}>
                Recognise
              </div>
              <div className="space-y-1.5">
                <div className="h-1.5 rounded-full" style={{ background: '#E8E8E5' }} />
                <div className="h-1.5 w-4/5 rounded-full" style={{ background: '#E8E8E5' }} />
                <div className="h-1.5 w-3/5 rounded-full" style={{ background: '#E8E8E5' }} />
              </div>
              <div className="mt-4 flex gap-1">
                <div className="h-1 flex-1 rounded-full bg-teal-500" />
                <div className="h-1 flex-1 rounded-full" style={{ background: '#E8E8E5' }} />
                <div className="h-1 flex-1 rounded-full" style={{ background: '#E8E8E5' }} />
                <div className="h-1 flex-1 rounded-full" style={{ background: '#E8E8E5' }} />
              </div>
            </div>

            <div
              className="absolute rounded-xl p-5"
              style={{
                width: '225px', top: '38px', left: '72px',
                background: '#F5F0E8',
                transform: 'rotate(1.8deg)',
                boxShadow: '0 20px 60px rgba(0,0,0,0.45)',
              }}
            >
              <div className="mb-3 text-[10px] font-semibold uppercase tracking-[0.18em]" style={{ color: '#9A7420' }}>
                Monthly Prompt
              </div>
              <div className="mb-3 text-navy-950" style={{ fontSize: '13px', fontWeight: 500, lineHeight: '1.55', letterSpacing: '-0.01em' }}>
                What would it feel like to stop carrying this alone?
              </div>
              <div className="space-y-1.5">
                <div className="h-1.5 rounded-full" style={{ background: '#DFCA7A' }} />
                <div className="h-1.5 w-5/6 rounded-full" style={{ background: '#DFCA7A' }} />
                <div className="h-1.5 w-2/3 rounded-full" style={{ background: '#DFCA7A' }} />
              </div>
            </div>

            <div
              className="absolute rounded-xl p-5"
              style={{
                width: '198px', top: '8px', right: '8px',
                background: '#0C1826',
                border: '1px solid rgba(255,255,255,0.08)',
                transform: 'rotate(-1.2deg)',
                boxShadow: '0 24px 64px rgba(0,0,0,0.65)',
              }}
            >
              <div className="mb-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-teal-400">
                Live Call
              </div>
              <div className="mb-0.5 text-[13.5px] font-semibold text-white">Monthly gathering</div>
              <div className="mb-5 text-[11.5px]" style={{ color: 'rgba(255,255,255,0.35)' }}>60 min · Structured · Led</div>
              <div
                className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[10px] font-semibold"
                style={{ background: 'rgba(212,176,72,0.12)', color: '#D4B048' }}
              >
                <span className="h-1.5 w-1.5 rounded-full bg-current" />
                Upcoming
              </div>
            </div>

            <div
              className="absolute rounded-xl p-4"
              style={{
                width: '172px', bottom: '18px', right: '4px',
                background: 'rgba(255,255,255,0.08)',
                backdropFilter: 'blur(10px)',
                border: '1px solid rgba(255,255,255,0.12)',
                transform: 'rotate(2.2deg)',
                boxShadow: '0 12px 36px rgba(0,0,0,0.40)',
              }}
            >
              <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-teal-300">
                Community
              </div>
              <div className="text-[12px] leading-[1.65]" style={{ color: 'rgba(255,255,255,0.55)' }}>
                Women in the same phase, at the same time.
              </div>
            </div>

          </div>

        </div>
      </Container>
    </section>
  )
}

/* ─── The Way We Feel ───────────────────────────────────────────────────────── */

function TheWayWeFeelSection() {
  return (
    <section className="py-16 sm:py-24" style={{ background: '#FAFAF8' }}>
      <Container>

        <div className="mb-12 max-w-[560px]">
          <h2
            className="text-navy-950"
            style={{ fontSize: 'clamp(1.875rem, 3.75vw, 3.25rem)', letterSpacing: '-0.04em', lineHeight: '1.08', fontWeight: 650 }}
          >
            The way we feel changes<br />
            <span style={{ color: 'rgba(12,24,38,0.30)' }}>what becomes possible.</span>
          </h2>
        </div>

        <div className="grid gap-10 sm:grid-cols-3">
          {[
            {
              rule: 'A more settled mind.',
              body: 'When you have a framework for where you are and where you are headed, the noise quiets. Clarity is not a luxury — it is the starting point.',
              accent: 'rgba(56,160,158,0.70)',
            },
            {
              rule: 'In it with others, honestly.',
              body: 'Not a curated highlight reel. Real people moving through real phases — with enough structure that the conversations go somewhere.',
              accent: 'rgba(212,176,72,0.70)',
              offset: true,
            },
            {
              rule: 'A thread back to yourself.',
              body: 'When life is full and loud, the REAL Journey gives you something to return to — a stable, consistent thread through all of it.',
              accent: 'rgba(45,77,115,0.60)',
            },
          ].map(({ rule, body, accent, offset }) => (
            <div key={rule} className={offset ? 'sm:pt-10' : ''}>
              <div className="mb-5 h-px w-6" style={{ background: accent }} />
              <p className="mb-3 text-navy-950" style={{ fontSize: '15.5px', fontWeight: 620, letterSpacing: '-0.02em', lineHeight: '1.4' }}>
                {rule}
              </p>
              <p className="text-[15px] leading-[1.82] text-navy-500">{body}</p>
            </div>
          ))}
        </div>

      </Container>
    </section>
  )
}

/* ─── Where the Learning Lives ──────────────────────────────────────────────── */

function WhereTheLearningLives() {
  return (
    <section className="py-16 sm:py-24" style={{ background: '#F5F0E8' }}>
      <Container>

        <div className="mb-10">
          <div className="mb-3 flex items-center gap-3">
            <div className="h-px w-8 bg-teal-500" style={{ opacity: 0.5 }} />
            <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-teal-600">
              The structure
            </span>
          </div>
          <h2
            className="text-navy-950"
            style={{ fontSize: 'clamp(1.75rem, 3.25vw, 2.75rem)', letterSpacing: '-0.04em', lineHeight: '1.1', fontWeight: 650 }}
          >
            Where the learning lives.
          </h2>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">

          <div
            className="rounded-2xl p-7 sm:col-span-2 lg:col-span-1 lg:row-span-2"
            style={{
              background: '#ffffff',
              border: '1px solid rgba(0,0,0,0.06)',
              boxShadow: '0 1px 3px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.05)',
            }}
          >
            <div
              className="mb-4 select-none"
              style={{ fontSize: '5.5rem', fontWeight: 650, lineHeight: '1', letterSpacing: '-0.06em', color: 'rgba(56,160,158,0.12)' }}
              aria-hidden="true"
            >
              01
            </div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-teal-600">
              Start Here
            </p>
            <h3 className="mb-4 text-navy-950" style={{ fontSize: '1.25rem', fontWeight: 650, letterSpacing: '-0.03em', lineHeight: '1.25' }}>
              REAL Journey
            </h3>
            <p className="mb-6 text-[15px] leading-[1.82] text-navy-500">
              Four phases — Recognise, Explore, Align, Lead. The foundation every member
              begins with. Bite-sized. Stabilising. Something to return to, again and again.
            </p>
            <Link href="/real-journey" className="text-[13.5px] font-semibold text-teal-600 underline-offset-2 transition-opacity hover:opacity-70 hover:underline">
              Learn more →
            </Link>
          </div>

          <div
            className="rounded-2xl p-7"
            style={{
              background: '#ffffff',
              border: '1px solid rgba(0,0,0,0.06)',
              boxShadow: '0 1px 3px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.05)',
            }}
          >
            <div
              className="mb-4 select-none"
              style={{ fontSize: '5.5rem', fontWeight: 650, lineHeight: '1', letterSpacing: '-0.06em', color: 'rgba(212,176,72,0.15)' }}
              aria-hidden="true"
            >
              02
            </div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em]" style={{ color: '#9A7420' }}>
              The Heart
            </p>
            <h3 className="mb-3 text-navy-950" style={{ fontSize: '1.125rem', fontWeight: 650, letterSpacing: '-0.03em', lineHeight: '1.25' }}>
              Live Layer
            </h3>
            <p className="mb-5 text-[15px] leading-[1.82] text-navy-500">
              Monthly live calls. Community prompts. Integration threads.
              The place where the membership comes alive.
            </p>
            <Link href="/membership" className="text-[13.5px] font-semibold underline-offset-2 transition-opacity hover:opacity-70 hover:underline" style={{ color: '#9A7420' }}>
              Explore Membership →
            </Link>
          </div>

          <div
            className="rounded-2xl p-7"
            style={{
              background: '#ffffff',
              border: '1px solid rgba(0,0,0,0.06)',
              boxShadow: '0 1px 3px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.05)',
            }}
          >
            <div
              className="mb-4 select-none"
              style={{ fontSize: '5.5rem', fontWeight: 650, lineHeight: '1', letterSpacing: '-0.06em', color: 'rgba(30,51,84,0.10)' }}
              aria-hidden="true"
            >
              03
            </div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-navy-400">
              The Rooms
            </p>
            <h3 className="mb-3 text-navy-950" style={{ fontSize: '1.125rem', fontWeight: 650, letterSpacing: '-0.03em', lineHeight: '1.25' }}>
              Deepening Pathways
            </h3>
            <p className="mb-5 text-[15px] leading-[1.82] text-navy-500">
              Growth, Transformation, Essence. Once you have your foundation,
              the pathways take you deeper — at your own pace.
            </p>
            <Link href="/membership" className="text-[13.5px] font-semibold text-navy-500 underline-offset-2 transition-opacity hover:opacity-70 hover:underline">
              Explore Membership →
            </Link>
          </div>

        </div>
      </Container>
    </section>
  )
}

/* ─── Conditions ────────────────────────────────────────────────────────────── */

function Conditions() {
  return (
    <section
      className="py-16 sm:py-24"
      style={{ background: '#F5F4F0', borderTop: '1px solid rgba(0,0,0,0.04)' }}
    >
      <Container>

        <div className="mb-12 max-w-[560px]">
          <h2
            className="text-navy-950"
            style={{ fontSize: 'clamp(1.875rem, 3.5vw, 3rem)', letterSpacing: '-0.04em', lineHeight: '1.08', fontWeight: 650 }}
          >
            The conditions matter<br />
            <span style={{ color: 'rgba(12,24,38,0.28)', fontStyle: 'italic' }}>
              as much as the content.
            </span>
          </h2>
        </div>

        <div className="grid gap-10 sm:grid-cols-3">
          {[
            {
              num: '01',
              heading: 'A pace that does not break you.',
              body: 'Everything inside Fresh Collective is designed to be returned to — not raced through. There is no urgency here. The structure holds.',
              numColor: 'rgba(56,160,158,0.25)',
            },
            {
              num: '02',
              heading: 'People building the same things.',
              body: 'You are not dropped into a general community. You are alongside people working through the same phases, the same questions, the same moments.',
              numColor: 'rgba(212,176,72,0.30)',
              offset: true,
            },
            {
              num: '03',
              heading: 'A leader who has been there.',
              body: 'Fresh Collective was built from the inside out — by someone who has moved through these phases herself, not just observed them.',
              numColor: 'rgba(30,51,84,0.20)',
            },
          ].map(({ num, heading, body, numColor, offset }) => (
            <div key={num} className={offset ? 'sm:pt-10' : ''}>
              <div
                className="mb-5 select-none"
                style={{ fontSize: '4.5rem', fontWeight: 650, lineHeight: '1', letterSpacing: '-0.06em', color: numColor }}
                aria-hidden="true"
              >
                {num}
              </div>
              <p className="mb-3 text-navy-950" style={{ fontSize: '15.5px', fontWeight: 620, letterSpacing: '-0.02em', lineHeight: '1.4' }}>
                {heading}
              </p>
              <p className="text-[15px] leading-[1.82] text-navy-500">{body}</p>
            </div>
          ))}
        </div>

      </Container>
    </section>
  )
}

/* ─── Good Questions ────────────────────────────────────────────────────────── */

function GoodQuestions() {
  const qa = [
    {
      q: 'What if I am already overwhelmed?',
      a: 'That is exactly the right time to start. The REAL Journey is designed for people who are already full — structured to be light enough to actually do, even when everything else is heavy.',
    },
    {
      q: 'Is this another online course I will not finish?',
      a: 'Fresh Collective is not built around consumption. It is built around consistency — short touchpoints, a live layer, and a community that keeps you moving even when motivation is low.',
    },
    {
      q: 'What is the difference between the REAL Journey and full membership?',
      a: 'The REAL Journey is the foundation — four phases, your own pace. Full membership adds the live layer and access to The Rooms. Both are meaningful starting points.',
    },
    {
      q: 'How much time do I need each week?',
      a: 'The REAL Journey is designed around bite-sized sessions. The monthly live call is 60 minutes. Most members find 30–60 minutes a week is enough to stay connected and moving.',
    },
  ]

  return (
    <section className="py-16 sm:py-24" style={{ background: '#FDFCF9' }}>
      <Container>
        <div className="grid gap-12 sm:grid-cols-[38%_62%] sm:gap-16">

          <div>
            <h2
              className="text-navy-950"
              style={{ fontSize: 'clamp(1.5rem, 2.5vw, 2.125rem)', letterSpacing: '-0.04em', lineHeight: '1.14', fontWeight: 650 }}
            >
              Good questions deserve honest answers.
            </h2>
          </div>

          <div>
            {qa.map(({ q, a }, i) => (
              <div
                key={q}
                className="py-6"
                style={{ borderTop: i === 0 ? 'none' : '1px solid rgba(0,0,0,0.05)' }}
              >
                <p className="mb-2.5 text-navy-950" style={{ fontSize: '15.5px', fontWeight: 620, letterSpacing: '-0.02em', lineHeight: '1.4' }}>
                  {q}
                </p>
                <p className="text-[15px] leading-[1.82] text-navy-500">{a}</p>
              </div>
            ))}
          </div>

        </div>
      </Container>
    </section>
  )
}

/* ─── Final CTA ─────────────────────────────────────────────────────────────── */

function FinalCTA() {
  return (
    <section
      className="relative overflow-hidden py-24 sm:py-32"
      style={{ background: '#060C17' }}
    >
      {/* Teal glow from below */}
      <div
        className="pointer-events-none absolute inset-0"
        aria-hidden="true"
        style={{
          background: 'radial-gradient(ellipse 80% 55% at 50% 110%, rgba(56,160,158,0.14) 0%, transparent 65%)',
        }}
      />

      <Container className="relative">
        <div className="mx-auto max-w-[520px] text-center">

          <div className="mx-auto mb-10 h-px w-10" style={{ background: 'rgba(212,176,72,0.35)' }} />

          <h2
            className="mb-6"
            style={{
              fontSize: 'clamp(2.25rem, 4.5vw, 4rem)',
              letterSpacing: '-0.04em',
              lineHeight: '1.07',
              fontWeight: 650,
              color: '#ffffff',
            }}
          >
            Find your collective.
            <br />
            <span
              style={{
                background: 'linear-gradient(108deg, #7FCFCD 0%, #D4B048 100%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
              }}
            >
              Or build one.
            </span>
          </h2>

          <p
            className="mb-10 text-[15.5px] leading-[1.82]"
            style={{ color: 'rgba(255,255,255,0.58)' }}
          >
            There&apos;s a collective for where you are now.
            Or build the one that doesn&apos;t exist yet.
          </p>

          <div className="flex flex-col items-center gap-4">
            <Link
              href="/spaces"
              className="inline-flex items-center rounded-xl px-9 py-4 text-[15px] font-semibold text-white transition-all hover:-translate-y-px hover:opacity-90"
              style={{
                background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                boxShadow: '0 2px 20px rgba(56,160,158,0.40)',
              }}
            >
              Explore Collectives
            </Link>
            <Link
              href="/signup"
              className="text-[13.5px] font-medium transition-opacity hover:opacity-80"
              style={{ color: 'rgba(255,255,255,0.48)' }}
            >
              or Build a Collective →
            </Link>
          </div>

          <div className="mx-auto mt-10 h-px w-10" style={{ background: 'rgba(212,176,72,0.35)' }} />

        </div>
      </Container>
    </section>
  )
}

/* ─── Page ──────────────────────────────────────────────────────────────────── */

export default function Home() {
  return (
    <SiteShell heroHeader>
      <HomeHero />
      <DualIntent />
      <EcosystemStatement />
      <FreshIdeas />
      <TheWayWeFeelSection />
      <WhereTheLearningLives />
      <Conditions />
      <GoodQuestions />
      <FinalCTA />
    </SiteShell>
  )
}
