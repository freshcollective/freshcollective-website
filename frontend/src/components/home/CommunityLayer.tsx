import Container from '@/components/layout/Container'

const MEMBER_COLORS = [
  '#55B8B6', '#7FCFCD', '#AAE1E0', '#38A09E', '#2E8584', '#D4B048',
]

const PRESENCE_ITEMS = [
  { label: 'Monthly live calls', sub: 'With the founder · structured' },
  { label: 'Ongoing conversations', sub: 'Integration prompts · ongoing' },
  { label: 'Real accountability', sub: 'Women walking the same path' },
]

export default function CommunityLayer() {
  return (
    <section
      className="relative overflow-hidden py-28 sm:py-36"
      style={{ background: 'linear-gradient(160deg, #080F1E 0%, #0D1F35 50%, #0C1826 100%)' }}
    >
      {/* Atmosphere */}
      <div className="pointer-events-none absolute inset-0" aria-hidden="true">
        <div
          style={{
            position: 'absolute', bottom: '-15%', right: '-10%',
            width: '600px', height: '600px', borderRadius: '50%',
            background: 'radial-gradient(circle, rgba(56,160,158,0.14) 0%, transparent 65%)',
            filter: 'blur(80px)',
          }}
        />
        <div
          style={{
            position: 'absolute', top: '-10%', left: '-5%',
            width: '500px', height: '500px', borderRadius: '50%',
            background: 'radial-gradient(circle, rgba(212,176,72,0.06) 0%, transparent 65%)',
            filter: 'blur(100px)',
          }}
        />
      </div>

      <Container className="relative">
        <div className="mx-auto max-w-[780px]">

          {/* Accent line */}
          <div
            className="mb-10 h-px w-12"
            style={{ background: 'linear-gradient(to right, #38A09E, transparent)' }}
          />

          {/* Quote */}
          <blockquote className="mb-12">
            <p
              className="font-serif italic leading-[1.6] text-white"
              style={{ fontSize: 'clamp(1.35rem, 2.8vw, 2rem)' }}
            >
              &ldquo;You are not doing this work alone. Other women are moving through
              the same phases, sitting in the same live calls, reading the same prompts
              — at the same time as you.&rdquo;
            </p>
          </blockquote>

          {/* Members cluster + presence */}
          <div className="flex flex-col gap-8 sm:flex-row sm:items-center sm:justify-between">

            {/* Avatar cluster */}
            <div className="flex items-center gap-4">
              <div className="flex -space-x-2.5">
                {MEMBER_COLORS.map((c, i) => (
                  <div
                    key={i}
                    className="h-9 w-9 rounded-full border-[2.5px]"
                    style={{ background: c, borderColor: '#080F1E' }}
                  />
                ))}
              </div>
              <div>
                <p className="text-[14px] font-semibold text-white">42 women in The Heart</p>
                <p className="text-[12px] text-navy-400">Active · Growing</p>
              </div>
            </div>

            {/* Presence indicators */}
            <div className="flex flex-col gap-3">
              {PRESENCE_ITEMS.map(({ label, sub }) => (
                <div key={label} className="flex items-center gap-3">
                  <div className="h-1.5 w-1.5 shrink-0 rounded-full bg-teal-500" />
                  <div>
                    <span className="text-[13px] font-medium text-white">{label}</span>
                    <span className="ml-2 text-[12px] text-navy-400">{sub}</span>
                  </div>
                </div>
              ))}
            </div>

          </div>

          {/* Bottom accent line */}
          <div
            className="mt-10 h-px"
            style={{ background: 'linear-gradient(to right, rgba(56,160,158,0.3), transparent)' }}
          />

        </div>
      </Container>
    </section>
  )
}
