import Link from 'next/link'
import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import HomeHero from '@/components/home/HomeHero'

/* ─── Dual Intent ───────────────────────────────────────────────────────────── */

function DualIntent() {
  return (
    <section
      className="py-16 sm:py-24"
      style={{
        background: 'linear-gradient(to bottom, #ECEAE7 0%, #F5F4F1 50%, #F9F8F5 100%)',
      }}
    >
      <Container>
        <div className="grid gap-12 sm:grid-cols-2 sm:gap-16 lg:gap-24">

          <div>
            <div className="mb-5 h-px w-7" style={{ background: 'rgba(56,160,158,0.50)' }} />
            <h2
              className="mb-4 text-navy-950"
              style={{ fontSize: 'clamp(1.375rem, 2.2vw, 1.875rem)', letterSpacing: '-0.03em', lineHeight: '1.15', fontWeight: 650 }}
            >
              A more intentional<br />way to grow.
            </h2>
            <p className="text-[15px] leading-[1.80] text-navy-500">
              Most growth happens by accident — in reaction to pressure, to loss, to necessity.
              Fresh Collective offers something rarer: a structured environment where growth
              is deliberate, paced, and yours to keep.
            </p>
          </div>

          <div className="sm:pt-10">
            <div className="mb-5 h-px w-7" style={{ background: 'rgba(212,176,72,0.50)' }} />
            <h2
              className="mb-4 text-navy-950"
              style={{ fontSize: 'clamp(1.375rem, 2.2vw, 1.875rem)', letterSpacing: '-0.03em', lineHeight: '1.15', fontWeight: 650 }}
            >
              Environments where<br />people actually change.
            </h2>
            <p className="text-[15px] leading-[1.80] text-navy-500">
              Information is abundant. What changes people is the right container —
              the right questions, at the right time, with others moving through the same thing.
              That is what we have built.
            </p>
          </div>

        </div>
      </Container>
    </section>
  )
}

/* ─── Ecosystem Statement ───────────────────────────────────────────────────── */

function EcosystemStatement() {
  return (
    <section className="py-14 sm:py-20" style={{ background: '#F9F8F5' }}>
      <Container>
        <div className="max-w-[600px]">
          <h2
            className="mb-4 text-navy-950"
            style={{ fontSize: 'clamp(1.875rem, 3.75vw, 3.25rem)', letterSpacing: '-0.04em', lineHeight: '1.09', fontWeight: 650 }}
          >
            Not a product.{' '}
            <span style={{ color: 'rgba(12,24,38,0.26)', fontStyle: 'italic' }}>
              An ecosystem.
            </span>
          </h2>
          <p className="text-[15.5px] leading-[1.80] text-navy-500" style={{ maxWidth: '460px' }}>
            One foundation. A live community layer. Deepening pathways — designed to
            work together, not as separate courses you buy and forget.
          </p>
        </div>
      </Container>
    </section>
  )
}

/* ─── Fresh Ideas — floating dark card ─────────────────────────────────────── */

function FreshIdeas() {
  return (
    <section className="py-3 sm:py-4" style={{ background: '#F9F8F5' }}>
      <Container>
        <div
          className="relative overflow-hidden"
          style={{
            background: '#0D2020',
            borderRadius: '20px',
            padding: 'clamp(2.5rem, 5vw, 4rem)',
          }}
        >
          {/* Atmospheric glow */}
          <div className="pointer-events-none absolute inset-0" aria-hidden="true">
            <div style={{
              position: 'absolute', top: '-30%', right: '-8%',
              width: '600px', height: '600px', borderRadius: '50%',
              background: 'radial-gradient(circle, rgba(56,160,158,0.11) 0%, transparent 60%)',
              filter: 'blur(70px)',
            }} />
          </div>

          <div className="relative grid items-center gap-12 sm:grid-cols-[54%_46%] sm:gap-8">

            {/* Left */}
            <div>
              <div className="mb-7 flex items-center gap-3">
                <div className="h-px w-7" style={{ background: 'rgba(85,184,182,0.32)' }} />
                <span className="text-[10.5px] font-semibold uppercase tracking-[0.14em]" style={{ color: 'rgba(255,255,255,0.26)' }}>
                  A different kind of learning
                </span>
              </div>

              <h2
                className="mb-7 text-white"
                style={{ fontSize: 'clamp(2rem, 4vw, 3.5rem)', letterSpacing: '-0.04em', lineHeight: '1.07', fontWeight: 650 }}
              >
                Fresh ideas need
                <br />
                <span style={{ color: 'rgba(255,255,255,0.26)' }}>spaces to grow.</span>
              </h2>

              <p
                className="mb-10 text-[15.5px] leading-[1.85]"
                style={{ color: 'rgba(255,255,255,0.44)', maxWidth: '420px' }}
              >
                We do not believe in passive consumption. Inside Fresh Collective,
                you are always in motion — reflecting, connecting, integrating — with
                enough structure to hold you and enough space to breathe.
              </p>

              <div
                className="grid grid-cols-3 gap-5"
                style={{ borderTop: '1px solid rgba(255,255,255,0.07)', paddingTop: '2rem' }}
              >
                {[
                  { stat: '4', label: 'REAL phases' },
                  { stat: '1×', label: 'Live monthly', gold: true },
                  { stat: '∞', label: 'Your pace' },
                ].map(({ stat, label, gold }) => (
                  <div key={label}>
                    <div
                      style={{
                        fontSize: 'clamp(1.5rem, 2.5vw, 2.25rem)',
                        letterSpacing: '-0.04em',
                        lineHeight: '1',
                        fontWeight: 650,
                        color: gold ? '#D4B048' : 'rgba(255,255,255,0.85)',
                        marginBottom: '4px',
                      }}
                    >
                      {stat}
                    </div>
                    <div className="text-[11px] font-medium uppercase tracking-[0.10em]" style={{ color: 'rgba(255,255,255,0.26)' }}>
                      {label}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Right — documentary artifacts */}
            <div className="relative hidden sm:block" style={{ height: '380px' }}>

              <div
                className="absolute rounded-2xl bg-white p-5"
                style={{
                  width: '200px', bottom: '24px', left: '0',
                  transform: 'rotate(-3deg)',
                  boxShadow: '0 16px 48px rgba(0,0,0,0.55)',
                }}
              >
                <div className="mb-2.5 text-[9.5px] font-semibold uppercase tracking-[0.16em] text-teal-600">
                  REAL Journey · Phase 1
                </div>
                <div className="mb-3 text-navy-950" style={{ fontSize: '13px', fontWeight: 620, letterSpacing: '-0.02em' }}>
                  Recognise
                </div>
                <div className="space-y-1.5">
                  <div className="h-1.5 rounded-full" style={{ background: '#E8E8E5' }} />
                  <div className="h-1.5 w-4/5 rounded-full" style={{ background: '#E8E8E5' }} />
                  <div className="h-1.5 w-3/5 rounded-full" style={{ background: '#E8E8E5' }} />
                </div>
                <div className="mt-3.5 flex gap-1">
                  <div className="h-1 flex-1 rounded-full bg-teal-500" />
                  <div className="h-1 flex-1 rounded-full" style={{ background: '#E8E8E5' }} />
                  <div className="h-1 flex-1 rounded-full" style={{ background: '#E8E8E5' }} />
                  <div className="h-1 flex-1 rounded-full" style={{ background: '#E8E8E5' }} />
                </div>
              </div>

              <div
                className="absolute rounded-2xl p-5"
                style={{
                  width: '210px', top: '32px', left: '62px',
                  background: '#F5F0E8',
                  transform: 'rotate(2deg)',
                  boxShadow: '0 16px 48px rgba(0,0,0,0.45)',
                }}
              >
                <div className="mb-2.5 text-[9.5px] font-semibold uppercase tracking-[0.16em]" style={{ color: '#9A7420' }}>
                  Monthly Prompt
                </div>
                <div className="mb-3 text-navy-950" style={{ fontSize: '12.5px', fontWeight: 500, lineHeight: '1.55', letterSpacing: '-0.01em' }}>
                  What would it feel like to stop carrying this alone?
                </div>
                <div className="space-y-1.5">
                  <div className="h-1.5 rounded-full" style={{ background: '#DFCA7A' }} />
                  <div className="h-1.5 w-5/6 rounded-full" style={{ background: '#DFCA7A' }} />
                  <div className="h-1.5 w-2/3 rounded-full" style={{ background: '#DFCA7A' }} />
                </div>
              </div>

              <div
                className="absolute rounded-2xl p-5"
                style={{
                  width: '186px', top: '6px', right: '6px',
                  background: '#0C1826',
                  border: '1px solid rgba(255,255,255,0.08)',
                  transform: 'rotate(-1deg)',
                  boxShadow: '0 20px 56px rgba(0,0,0,0.70)',
                }}
              >
                <div className="mb-2.5 text-[9.5px] font-semibold uppercase tracking-[0.16em] text-teal-400">
                  Live Call
                </div>
                <div className="mb-0.5 text-[13px] font-semibold text-white">Monthly gathering</div>
                <div className="mb-4 text-[11px]" style={{ color: 'rgba(255,255,255,0.32)' }}>60 min · Structured · Led</div>
                <div
                  className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[9.5px] font-semibold"
                  style={{ background: 'rgba(212,176,72,0.12)', color: '#D4B048' }}
                >
                  <span className="h-1.5 w-1.5 rounded-full bg-current" />
                  Upcoming
                </div>
              </div>

              <div
                className="absolute rounded-2xl p-4"
                style={{
                  width: '162px', bottom: '14px', right: '2px',
                  background: 'rgba(255,255,255,0.07)',
                  backdropFilter: 'blur(10px)',
                  border: '1px solid rgba(255,255,255,0.11)',
                  transform: 'rotate(2.5deg)',
                  boxShadow: '0 10px 32px rgba(0,0,0,0.40)',
                }}
              >
                <div className="mb-1.5 text-[9.5px] font-semibold uppercase tracking-[0.16em] text-teal-300">
                  Community
                </div>
                <div className="text-[11.5px] leading-[1.62]" style={{ color: 'rgba(255,255,255,0.52)' }}>
                  Women in the same phase, at the same time.
                </div>
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
    <section className="py-16 sm:py-24" style={{ background: '#F9F8F5' }}>
      <Container>

        <div className="mb-10 max-w-[520px]">
          <h2
            className="text-navy-950"
            style={{ fontSize: 'clamp(1.75rem, 3.5vw, 3rem)', letterSpacing: '-0.04em', lineHeight: '1.09', fontWeight: 650 }}
          >
            The way we feel changes<br />
            <span style={{ color: 'rgba(12,24,38,0.28)' }}>what becomes possible.</span>
          </h2>
        </div>

        <div
          className="grid gap-0 sm:grid-cols-3"
          style={{ borderTop: '1px solid rgba(0,0,0,0.06)' }}
        >
          {[
            {
              rule: 'A more settled mind.',
              body: 'When you have a framework for where you are and where you are headed, the noise quiets. Clarity is not a luxury — it is the starting point.',
              accent: 'rgba(56,160,158,0.65)',
            },
            {
              rule: 'In it with others, honestly.',
              body: 'Not a curated highlight reel. Real people moving through real phases — with enough structure that the conversations go somewhere.',
              accent: 'rgba(212,176,72,0.65)',
              border: true,
            },
            {
              rule: 'A thread back to yourself.',
              body: 'When life is full and loud, the REAL Journey gives you something to return to — a stable, consistent thread through all of it.',
              accent: 'rgba(45,77,115,0.55)',
            },
          ].map(({ rule, body, accent, border }) => (
            <div
              key={rule}
              className="py-8 sm:pr-8"
              style={border ? { borderLeft: '1px solid rgba(0,0,0,0.06)', borderRight: '1px solid rgba(0,0,0,0.06)', paddingLeft: '2rem' } : {}}
            >
              <div className="mb-4 h-px w-6" style={{ background: accent }} />
              <p className="mb-2.5 text-navy-950" style={{ fontSize: '15px', fontWeight: 620, letterSpacing: '-0.02em', lineHeight: '1.4' }}>
                {rule}
              </p>
              <p className="text-[14.5px] leading-[1.80] text-navy-500">{body}</p>
            </div>
          ))}
        </div>

      </Container>
    </section>
  )
}

/* ─── Where the Learning Lives — editorial ──────────────────────────────────── */

function WhereTheLearningLives() {
  return (
    <section
      className="py-14 sm:py-20"
      style={{ background: '#F9F8F5', borderTop: '1px solid rgba(0,0,0,0.05)' }}
    >
      <Container>
        <div className="grid gap-10 sm:grid-cols-[36%_64%] sm:gap-14">

          {/* Left: heading */}
          <div className="sm:pt-1">
            <div className="mb-3 flex items-center gap-2.5">
              <div className="h-px w-6" style={{ background: 'rgba(56,160,158,0.45)' }} />
              <span className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-teal-600">
                The structure
              </span>
            </div>
            <h2
              className="text-navy-950"
              style={{ fontSize: 'clamp(1.625rem, 3vw, 2.5rem)', letterSpacing: '-0.04em', lineHeight: '1.10', fontWeight: 650 }}
            >
              Where the<br />learning lives.
            </h2>
          </div>

          {/* Right: editorial three-part list */}
          <div>
            {[
              {
                num: '01',
                label: 'Start Here',
                title: 'REAL Journey',
                body: 'Four phases — Recognise, Explore, Align, Lead. The foundation every member begins with. Bite-sized. Stabilising. Something to return to.',
                href: '/real-journey',
                accentColor: '#38A09E',
              },
              {
                num: '02',
                label: 'The Heart',
                title: 'Live Layer',
                body: 'Monthly live calls. Community prompts. Integration threads. The place where the membership comes alive.',
                href: '/membership',
                accentColor: '#BF9830',
              },
              {
                num: '03',
                label: 'The Rooms',
                title: 'Deepening Pathways',
                body: 'Growth, Transformation, Essence. Once you have your foundation, the pathways take you deeper — at your own pace.',
                href: '/membership',
                accentColor: '#3D6289',
              },
            ].map(({ num, label, title, body, href, accentColor }, i) => (
              <div
                key={num}
                className="grid grid-cols-[2rem_1fr] gap-4 py-7"
                style={{ borderTop: i === 0 ? 'none' : '1px solid rgba(0,0,0,0.06)' }}
              >
                <div
                  className="pt-0.5 text-[11px] font-semibold tabular-nums"
                  style={{ color: 'rgba(12,24,38,0.25)', letterSpacing: '0.02em' }}
                >
                  {num}
                </div>
                <div>
                  <div className="mb-1 flex items-center gap-2.5">
                    <span
                      className="text-[10.5px] font-semibold uppercase tracking-[0.12em]"
                      style={{ color: accentColor }}
                    >
                      {label}
                    </span>
                  </div>
                  <p
                    className="mb-2 text-navy-950"
                    style={{ fontSize: '15px', fontWeight: 630, letterSpacing: '-0.02em', lineHeight: '1.35' }}
                  >
                    {title}
                  </p>
                  <p className="mb-3 text-[14px] leading-[1.78] text-navy-500">{body}</p>
                  <Link
                    href={href}
                    className="text-[13px] font-semibold underline-offset-2 transition-opacity hover:opacity-60 hover:underline"
                    style={{ color: accentColor }}
                  >
                    Learn more →
                  </Link>
                </div>
              </div>
            ))}
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
      className="py-14 sm:py-20"
      style={{ background: '#F9F8F5', borderTop: '1px solid rgba(0,0,0,0.05)' }}
    >
      <Container>

        <div className="mb-10 max-w-[520px]">
          <h2
            className="text-navy-950"
            style={{ fontSize: 'clamp(1.75rem, 3.25vw, 2.875rem)', letterSpacing: '-0.04em', lineHeight: '1.09', fontWeight: 650 }}
          >
            The conditions matter<br />
            <span style={{ color: 'rgba(12,24,38,0.26)', fontStyle: 'italic' }}>
              as much as the content.
            </span>
          </h2>
        </div>

        <div className="grid gap-0 sm:grid-cols-3" style={{ borderTop: '1px solid rgba(0,0,0,0.06)' }}>
          {[
            {
              num: '01',
              heading: 'A pace that does not break you.',
              body: 'Everything inside Fresh Collective is designed to be returned to — not raced through. There is no urgency here. The structure holds.',
              numColor: 'rgba(56,160,158,0.22)',
              border: false,
            },
            {
              num: '02',
              heading: 'People building the same things.',
              body: 'You are not dropped into a general community. You are alongside people working through the same phases, the same questions, the same moments.',
              numColor: 'rgba(212,176,72,0.28)',
              border: true,
            },
            {
              num: '03',
              heading: 'A leader who has been there.',
              body: 'Fresh Collective was built from the inside out — by someone who has moved through these phases herself, not just observed them.',
              numColor: 'rgba(30,51,84,0.18)',
              border: false,
            },
          ].map(({ num, heading, body, numColor, border }) => (
            <div
              key={num}
              className="py-8 sm:pr-8"
              style={border ? { borderLeft: '1px solid rgba(0,0,0,0.06)', borderRight: '1px solid rgba(0,0,0,0.06)', paddingLeft: '2rem' } : {}}
            >
              <div
                className="mb-4 select-none"
                style={{ fontSize: '3.5rem', fontWeight: 650, lineHeight: '1', letterSpacing: '-0.06em', color: numColor }}
                aria-hidden="true"
              >
                {num}
              </div>
              <p className="mb-2.5 text-navy-950" style={{ fontSize: '15px', fontWeight: 620, letterSpacing: '-0.02em', lineHeight: '1.4' }}>
                {heading}
              </p>
              <p className="text-[14.5px] leading-[1.80] text-navy-500">{body}</p>
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
    <section
      className="py-14 sm:py-20"
      style={{ background: '#F9F8F5', borderTop: '1px solid rgba(0,0,0,0.05)' }}
    >
      <Container>
        <div className="grid gap-10 sm:grid-cols-[36%_64%] sm:gap-14">

          <div>
            <h2
              className="text-navy-950"
              style={{ fontSize: 'clamp(1.375rem, 2.25vw, 1.875rem)', letterSpacing: '-0.035em', lineHeight: '1.18', fontWeight: 650 }}
            >
              Good questions deserve honest answers.
            </h2>
          </div>

          <div>
            {qa.map(({ q, a }, i) => (
              <div
                key={q}
                className="py-5"
                style={{ borderTop: i === 0 ? 'none' : '1px solid rgba(0,0,0,0.05)' }}
              >
                <p className="mb-2 text-navy-950" style={{ fontSize: '15px', fontWeight: 620, letterSpacing: '-0.02em', lineHeight: '1.4' }}>
                  {q}
                </p>
                <p className="text-[14.5px] leading-[1.80] text-navy-500">{a}</p>
              </div>
            ))}
          </div>

        </div>
      </Container>
    </section>
  )
}

/* ─── Final CTA — contained dark card ──────────────────────────────────────── */

function FinalCTA() {
  return (
    <section className="py-8 pb-20 sm:py-10 sm:pb-28" style={{ background: '#F9F8F5' }}>
      <Container>
        <div
          className="relative overflow-hidden text-center"
          style={{
            background: '#06111A',
            borderRadius: '20px',
            padding: 'clamp(3rem, 6vw, 5rem) clamp(1.5rem, 4vw, 4rem)',
          }}
        >
          {/* Teal glow from below */}
          <div
            className="pointer-events-none absolute inset-0"
            aria-hidden="true"
            style={{
              background: 'radial-gradient(ellipse 75% 50% at 50% 115%, rgba(56,160,158,0.16) 0%, transparent 65%)',
            }}
          />

          <div className="relative mx-auto max-w-[460px]">
            <div className="mx-auto mb-8 h-px w-8" style={{ background: 'rgba(212,176,72,0.38)' }} />

            <h2
              className="mb-5"
              style={{
                fontSize: 'clamp(2rem, 4vw, 3.625rem)',
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
              className="mb-9 text-[15px] leading-[1.80]"
              style={{ color: 'rgba(255,255,255,0.55)' }}
            >
              There&apos;s a collective for where you are now.
              Or build the one that doesn&apos;t exist yet.
            </p>

            <div className="flex flex-col items-center gap-3.5">
              <Link
                href="/spaces"
                className="inline-flex items-center rounded-xl px-8 py-3.5 text-[14.5px] font-semibold text-white transition-all hover:-translate-y-px hover:opacity-90"
                style={{
                  background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                  boxShadow: '0 2px 18px rgba(56,160,158,0.38)',
                }}
              >
                Explore Collectives
              </Link>
              <Link
                href="/signup"
                className="text-[13px] font-medium transition-opacity hover:opacity-80"
                style={{ color: 'rgba(255,255,255,0.44)' }}
              >
                or Build a Collective →
              </Link>
            </div>

            <div className="mx-auto mt-8 h-px w-8" style={{ background: 'rgba(212,176,72,0.38)' }} />
          </div>
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
      <div style={{ background: '#F9F8F5' }}>
        <DualIntent />
        <EcosystemStatement />
        <FreshIdeas />
        <TheWayWeFeelSection />
        <WhereTheLearningLives />
        <Conditions />
        <GoodQuestions />
        <FinalCTA />
      </div>
    </SiteShell>
  )
}
