import Link from 'next/link'
import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import HomeHero from '@/components/home/HomeHero'

/* ─── Two Ways In ───────────────────────────────────────────────────────────── */

function TwoWaysIn() {
  return (
    <section className="py-16 sm:py-24" style={{ background: '#FDFCF9' }}>
      <Container>

        <div className="mb-12">
          <div className="mb-3 flex items-center gap-3">
            <div className="h-px w-8 bg-teal-400" />
            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600">
              Who it&apos;s for
            </span>
          </div>
          <h2
            className="text-navy-950"
            style={{ fontSize: 'clamp(1.875rem, 3.5vw, 3rem)', letterSpacing: '-0.04em', lineHeight: '1.08', fontWeight: 650 }}
          >
            Two ways in.
          </h2>
        </div>

        <div
          className="grid gap-12 sm:grid-cols-2 sm:gap-0"
          style={{ borderTop: '1px solid #EEEDE9', paddingTop: '3rem' }}
        >

          <div className="sm:pr-12 lg:pr-20">
            <p className="mb-4 text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600">
              For learners
            </p>
            <p
              className="mb-5 text-navy-950"
              style={{ fontSize: 'clamp(1.125rem, 1.75vw, 1.375rem)', letterSpacing: '-0.02em', lineHeight: '1.3', fontWeight: 620 }}
            >
              Seeking a more intentional way to grow
            </p>
            <p className="mb-7 text-[15.5px] leading-[1.82] text-navy-500">
              Find guided spaces built around genuine expertise and lived experience.
              Attend live gatherings. Participate in a focused community. Learn at a
              pace that lets ideas move from understanding into how you actually live.
            </p>
            <Link
              href="/spaces"
              className="text-[14px] font-semibold text-teal-600 transition-colors hover:underline underline-offset-2"
            >
              Explore Spaces →
            </Link>
          </div>

          <div
            className="sm:pl-12 lg:pl-20"
            style={{ borderLeft: '1px solid #EEEDE9' }}
          >
            <p className="mb-4 text-[11px] font-semibold uppercase tracking-[0.12em]" style={{ color: '#9A7420' }}>
              For creators
            </p>
            <p
              className="mb-5 text-navy-950"
              style={{ fontSize: 'clamp(1.125rem, 1.75vw, 1.375rem)', letterSpacing: '-0.02em', lineHeight: '1.3', fontWeight: 620 }}
            >
              Building environments where people actually change
            </p>
            <p className="mb-7 text-[15.5px] leading-[1.82] text-navy-500">
              Design intentional learning spaces around the work you know deeply.
              Host live gatherings. Build a community grounded in shared growth.
              Create the kind of environment you always wished existed.
            </p>
            <Link
              href="/signup"
              className="text-[14px] font-semibold transition-colors hover:underline underline-offset-2"
              style={{ color: '#9A7420' }}
            >
              Start Building →
            </Link>
          </div>

        </div>
      </Container>
    </section>
  )
}

/* ─── Vision (emotional centre — dark) ─────────────────────────────────────── */

function Vision() {
  return (
    <section className="relative overflow-hidden py-24 sm:py-32" style={{ background: '#060C17' }}>

      <div className="pointer-events-none absolute inset-0" aria-hidden="true">
        <div style={{
          position: 'absolute', top: '-20%', right: '-5%',
          width: '700px', height: '700px', borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(56,160,158,0.08) 0%, transparent 60%)',
          filter: 'blur(80px)',
        }} />
        <div style={{
          position: 'absolute', bottom: '-15%', left: '-8%',
          width: '600px', height: '600px', borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(201,168,60,0.05) 0%, transparent 60%)',
          filter: 'blur(100px)',
        }} />
      </div>

      <Container className="relative">
        <div className="max-w-[680px]">

          <div className="mb-8 flex items-center gap-3">
            <div className="h-px w-8 bg-teal-400/40" />
            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-400/60">
              What we&apos;re building
            </span>
          </div>

          <h2
            style={{
              fontSize: 'clamp(2.25rem, 4.5vw, 4rem)',
              letterSpacing: '-0.04em',
              lineHeight: '1.07',
              fontWeight: 650,
              color: '#ffffff',
            }}
          >
            Fresh ideas need
            <br />
            <span style={{ color: 'rgba(255,255,255,0.30)' }}>spaces to grow.</span>
          </h2>

          <div className="mt-10 space-y-5" style={{ maxWidth: '500px' }}>
            <p className="text-[16px] leading-[1.88]" style={{ color: 'rgba(255,255,255,0.55)' }}>
              Fresh Collective is a place for people who sense there are better ways to live,
              lead, create, and grow — and want environments that help them move from
              understanding to embodiment.
            </p>
            <p className="text-[15px] leading-[1.88]" style={{ color: 'rgba(255,255,255,0.26)' }}>
              Not content libraries. Not passive consumption. Structured environments where
              learning happens in community — guided, grounded, and oriented toward what
              comes next.
            </p>
          </div>

          <div
            className="mt-14 grid grid-cols-1 gap-6 sm:grid-cols-3 sm:gap-8"
            style={{ borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: '2.5rem' }}
          >
            {[
              { label: 'Educators and guides', sub: 'Building spaces where deep ideas become lived experience.' },
              { label: 'Depth-seeking learners', sub: 'Finding environments where new ways of thinking can take hold.' },
              { label: 'Emerging ways forward', sub: 'Explored with the structure and community they need to develop.' },
            ].map(({ label, sub }) => (
              <div key={label}>
                <p
                  className="mb-1.5 font-semibold"
                  style={{ color: 'rgba(255,255,255,0.70)', fontSize: '0.9375rem', letterSpacing: '-0.01em' }}
                >
                  {label}
                </p>
                <p style={{ color: 'rgba(255,255,255,0.24)', fontSize: '13px', lineHeight: '1.65' }}>
                  {sub}
                </p>
              </div>
            ))}
          </div>

        </div>
      </Container>
    </section>
  )
}

/* ─── Platform Preview (compact — 3 items) ──────────────────────────────────── */

const CARD_STYLE = {
  border: '1px solid rgba(0,0,0,0.07)',
  boxShadow: '0 1px 3px rgba(0,0,0,0.04), 0 6px 18px rgba(0,0,0,0.04)',
}

function PlatformPreview() {
  return (
    <section className="bg-white py-16 sm:py-20">
      <Container>

        <div className="mb-8">
          <div className="mb-3 flex items-center gap-3">
            <div className="h-px w-8 bg-teal-400" />
            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600">
              Inside a space
            </span>
          </div>
          <h2
            className="text-navy-950"
            style={{ fontSize: 'clamp(1.625rem, 2.75vw, 2.25rem)', letterSpacing: '-0.04em', lineHeight: '1.1', fontWeight: 650 }}
          >
            What it actually looks like.
          </h2>
        </div>

        <div className="grid gap-4 sm:grid-cols-3">

          {/* Pathway */}
          <div className="rounded-2xl bg-white p-5" style={CARD_STYLE}>
            <p className="mb-3 text-[10px] font-semibold uppercase tracking-[0.1em] text-teal-600">Pathway · Step 3 of 12</p>
            <p className="mb-3 text-[13.5px] font-semibold text-navy-950">The REAL Journey</p>
            <div className="mb-3 h-0.5 rounded-full bg-navy-100">
              <div className="h-0.5 w-1/4 rounded-full bg-teal-400" />
            </div>
            <div className="space-y-2">
              {['Coming home to yourself', 'Your energy baseline', 'The patterns keeping you stuck'].map((t, i) => (
                <div key={t} className="flex items-center gap-2">
                  <div
                    className={`h-3.5 w-3.5 flex-shrink-0 rounded-full text-[8px] font-bold flex items-center justify-center ${i === 0 ? 'bg-teal-500 text-white' : 'bg-navy-50 text-navy-300'}`}
                    style={{ border: i === 0 ? 'none' : '1px solid #E2E8F0' }}
                  >
                    {i === 0 ? '✓' : i + 1}
                  </div>
                  <span className={`text-[11.5px] ${i === 0 ? 'text-navy-300 line-through' : 'text-navy-700'}`}>{t}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Event */}
          <div className="rounded-2xl bg-white p-5" style={CARD_STYLE}>
            <div className="mb-3 flex items-center gap-2">
              <div className="h-1.5 w-1.5 rounded-full bg-teal-400" />
              <span className="text-[10px] font-semibold uppercase tracking-[0.1em] text-teal-600">Live event</span>
            </div>
            <p className="mb-0.5 text-[13.5px] font-semibold text-navy-950">Monthly gathering — June</p>
            <p className="mb-4 text-[11.5px] text-navy-400">First Thursday · 7:30 pm AEST</p>
            <div className="mb-3 rounded-xl p-3" style={{ background: 'rgba(56,160,158,0.05)', border: '1px solid rgba(56,160,158,0.09)' }}>
              <p className="mb-0.5 text-[9.5px] font-semibold uppercase tracking-[0.08em] text-teal-700">This month</p>
              <p className="text-[12px] font-semibold text-navy-900">What are you actually saying yes to?</p>
            </div>
            <p className="text-[11px] text-navy-400">42 attending</p>
          </div>

          {/* Community */}
          <div className="rounded-2xl bg-white p-5" style={CARD_STYLE}>
            <div className="mb-3">
              <span className="rounded-lg px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em]" style={{ background: 'rgba(56,160,158,0.07)', color: '#2E8584' }}>
                Community prompt
              </span>
            </div>
            <p className="mb-4 text-[13px] font-medium leading-[1.55] text-navy-800">
              What shifted for you this week — even something small?
            </p>
            <div className="space-y-2">
              {[
                { c: '#55B8B6', t: 'I stopped apologising before asking for help.' },
                { c: '#AAE1E0', t: 'Noticed I was bracing — chose to stay open.' },
              ].map(({ c, t }, i) => (
                <div key={i} className="flex items-start gap-2 rounded-lg p-2" style={{ background: '#F5F7FA' }}>
                  <div className="mt-0.5 h-4 w-4 flex-shrink-0 rounded-full border-2 border-white" style={{ background: c }} />
                  <p className="text-[11px] leading-[1.55] text-navy-600">{t}</p>
                </div>
              ))}
            </div>
            <p className="mt-3 text-[11px] text-navy-400">23 responses · 3 hrs ago</p>
          </div>

        </div>
      </Container>
    </section>
  )
}

/* ─── Featured Spaces ───────────────────────────────────────────────────────── */

const FEATURED = [
  {
    slug: 'fresh-collective',
    name: 'Fresh Collective',
    tagline: 'The founding space — structured pathways, live monthly gatherings, and an active learning community.',
    creator: 'Lindsey',
    isFlagship: true,
    color: '#38A09E',
  },
  {
    slug: 'the-creative-thread',
    name: 'The Creative Thread',
    tagline: 'For makers, writers, and visual artists building a sustainable creative practice.',
    creator: 'Priya Mehta',
    isFlagship: false,
    color: '#C06B3A',
  },
  {
    slug: 'letters-to-myself',
    name: 'Letters to Myself',
    tagline: 'A reflective journaling practice for people in it for the long game.',
    creator: 'Caitlin Marsh',
    isFlagship: false,
    color: '#B8922A',
  },
]

function FeaturedSpaces() {
  return (
    <section className="py-16 sm:py-24" style={{ background: '#FDFCF9' }}>
      <Container>

        <div className="mb-10 flex items-end justify-between">
          <div>
            <div className="mb-3 flex items-center gap-3">
              <div className="h-px w-8 bg-teal-400" />
              <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600">
                Spaces
              </span>
            </div>
            <h2
              className="text-navy-950"
              style={{ fontSize: 'clamp(1.625rem, 2.75vw, 2.25rem)', letterSpacing: '-0.04em', lineHeight: '1.1', fontWeight: 650 }}
            >
              Where the learning lives.
            </h2>
          </div>
          <Link
            href="/spaces"
            className="hidden text-[13.5px] font-semibold text-teal-600 hover:underline underline-offset-2 sm:block"
          >
            Explore all →
          </Link>
        </div>

        <div className="divide-y" style={{ borderTop: '1px solid #EEEDE9', borderBottom: '1px solid #EEEDE9' }}>
          {FEATURED.map(({ slug, name, tagline, creator, isFlagship, color }) => (
            <div key={slug} className="group flex items-center justify-between gap-6 py-6">
              <div className="flex items-start gap-4 min-w-0">
                <div
                  className="mt-1 h-7 w-1 flex-shrink-0 rounded-full"
                  style={{ background: color }}
                />
                <div className="min-w-0">
                  <div className="mb-0.5 flex flex-wrap items-center gap-2">
                    <p className="text-[15px] font-semibold text-navy-950">{name}</p>
                    {isFlagship && (
                      <span
                        className="rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.06em]"
                        style={{ background: 'rgba(201,168,60,0.10)', color: '#9A7420' }}
                      >
                        Flagship
                      </span>
                    )}
                  </div>
                  <p className="text-[13.5px] leading-[1.6] text-navy-400 line-clamp-1">{tagline}</p>
                  <p className="mt-0.5 text-[12px] text-navy-300">by {creator}</p>
                </div>
              </div>
              <Link
                href={isFlagship ? '/spaces/fresh-collective' : '/spaces'}
                className="hidden flex-shrink-0 text-[13px] font-semibold text-navy-400 transition-colors group-hover:text-navy-700 sm:block"
              >
                Explore →
              </Link>
            </div>
          ))}
        </div>

        <div className="mt-6 sm:hidden">
          <Link
            href="/spaces"
            className="text-[14px] font-semibold text-teal-600 hover:underline underline-offset-2"
          >
            Explore all spaces →
          </Link>
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
      <div
        className="pointer-events-none absolute inset-0"
        aria-hidden="true"
        style={{
          background: 'radial-gradient(ellipse 80% 60% at 50% 100%, rgba(56,160,158,0.12) 0%, transparent 70%)',
        }}
      />

      <Container className="relative">
        <div className="mx-auto max-w-[520px] text-center">

          <h2
            className="mb-6"
            style={{
              fontSize: 'clamp(2.25rem, 4vw, 3.5rem)',
              letterSpacing: '-0.04em',
              lineHeight: '1.08',
              fontWeight: 650,
              color: '#ffffff',
            }}
          >
            Find your space.
            <br />
            <span style={{ color: 'rgba(255,255,255,0.30)' }}>Or build one.</span>
          </h2>

          <p className="mb-10 text-[15.5px] leading-[1.82]" style={{ color: 'rgba(255,255,255,0.40)' }}>
            Join a guided learning space — or create an intentional one of your own.
          </p>

          <div className="flex flex-col items-center gap-4">
            <Link
              href="/spaces"
              className="inline-flex items-center rounded-xl px-9 py-4 text-[15px] font-semibold text-white transition-all hover:opacity-90 hover:-translate-y-px"
              style={{
                background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                boxShadow: '0 2px 20px rgba(56,160,158,0.40)',
              }}
            >
              Explore Spaces
            </Link>
            <Link
              href="/signup"
              className="text-[13.5px] font-medium transition-opacity hover:opacity-60"
              style={{ color: 'rgba(255,255,255,0.32)' }}
            >
              or Create a Space →
            </Link>
          </div>

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
      <TwoWaysIn />
      <Vision />
      <PlatformPreview />
      <FeaturedSpaces />
      <FinalCTA />
    </SiteShell>
  )
}
