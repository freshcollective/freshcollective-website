import Container from '@/components/layout/Container'

function MockREALCard() {
  return (
    <div className="rounded-xl bg-white p-5" style={{ border: '1px solid #EBEBEB', boxShadow: 'var(--fc-shadow-card)' }}>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-teal-600">Phase 1 of 4</p>
          <p className="mt-0.5 text-[15px] font-semibold text-navy-950">Reconnect</p>
        </div>
        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-teal-50" style={{ border: '1px solid rgba(56,160,158,0.2)' }}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <circle cx="7" cy="7" r="5.5" stroke="#38A09E" strokeWidth="1.25" />
            <circle cx="7" cy="7" r="2.5" fill="#38A09E" />
          </svg>
        </div>
      </div>
      <div className="mb-4 h-1.5 rounded-full bg-navy-100">
        <div className="h-1.5 rounded-full bg-teal-400" style={{ width: '35%' }} />
      </div>
      <div className="space-y-2">
        {['Coming home to yourself', 'Your energy baseline', 'The patterns keeping you stuck'].map((t, i) => (
          <div key={t} className="flex items-center gap-2.5">
            <div className={`h-5 w-5 flex-shrink-0 rounded-full flex items-center justify-center text-[10px] ${i === 0 ? 'bg-teal-500 text-white' : 'bg-navy-50 text-navy-400'}`} style={{ border: i === 0 ? 'none' : '1px solid #E2E8F0' }}>
              {i === 0 ? '✓' : i + 1}
            </div>
            <span className={`text-[12.5px] ${i === 0 ? 'text-navy-400 line-through' : 'text-navy-700'}`}>{t}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function MockLiveCallCard() {
  return (
    <div className="rounded-xl bg-white p-5" style={{ border: '1px solid #EBEBEB', boxShadow: 'var(--fc-shadow-card)' }}>
      <div className="mb-4 flex items-center gap-2.5">
        <div className="flex h-2 w-2 items-center justify-center">
          <div className="h-2 w-2 rounded-full bg-teal-400" style={{ animation: 'glow-pulse 2.5s ease-in-out infinite' }} />
        </div>
        <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-teal-600">Monthly gathering</span>
      </div>
      <p className="mb-1 text-[15px] font-semibold text-navy-950">The Heart — June Call</p>
      <p className="mb-4 text-[12.5px] text-navy-400">Held on the first Thursday of each month</p>
      <div className="mb-4 rounded-lg p-3" style={{ background: 'rgba(56,160,158,0.05)', border: '1px solid rgba(56,160,158,0.12)' }}>
        <p className="text-[11px] font-medium text-teal-700">This month&apos;s theme</p>
        <p className="mt-0.5 text-[13px] font-semibold text-navy-900">What are you actually saying yes to?</p>
      </div>
      <div className="flex items-center justify-between">
        <div className="flex -space-x-1.5">
          {['#55B8B6', '#7FCFCD', '#AAE1E0', '#38A09E', '#2E8584'].map((c, i) => (
            <div key={i} className="h-5 w-5 rounded-full border-2 border-white" style={{ background: c }} />
          ))}
          <div className="flex h-5 w-5 items-center justify-center rounded-full border-2 border-white bg-navy-100 text-[8px] font-bold text-navy-500">+37</div>
        </div>
        <span className="text-[11px] text-navy-400">42 attending</span>
      </div>
    </div>
  )
}

function MockRoomCard() {
  return (
    <div className="rounded-xl bg-white p-5" style={{ border: '1px solid #EBEBEB', boxShadow: 'var(--fc-shadow-card)' }}>
      <div className="mb-3 flex items-center gap-2">
        <div className="rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em]" style={{ background: 'rgba(201,168,60,0.1)', color: '#A67E1E' }}>
          The Rooms
        </div>
      </div>
      <p className="mb-1 text-[15px] font-semibold text-navy-950">Work &amp; Money</p>
      <p className="mb-4 text-[12.5px] leading-[1.6] text-navy-400">
        Reconnect with what you actually want from your work — beyond output and obligation.
      </p>
      <div className="space-y-1.5">
        {['Your relationship with ambition', 'Money as energy, not evidence', 'The work that calls you'].map((t) => (
          <div key={t} className="flex items-center gap-2">
            <div className="h-1 w-1 flex-shrink-0 rounded-full" style={{ background: '#C9A83C' }} />
            <span className="text-[12px] text-navy-500">{t}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function MockReflectionCard() {
  return (
    <div className="rounded-xl bg-white p-5" style={{ border: '1px solid #EBEBEB', boxShadow: 'var(--fc-shadow-card)' }}>
      <div className="mb-3 flex items-center gap-2">
        <div className="rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em]" style={{ background: 'rgba(56,160,158,0.08)', color: '#2E8584' }}>
          Reflection
        </div>
      </div>
      <p className="mb-4 text-[14px] font-medium leading-[1.65] text-navy-800">
        &ldquo;What would it feel like to want what you already have?&rdquo;
      </p>
      <div className="rounded-lg p-3" style={{ background: '#F5F7FA', border: '1px solid #EBEBEB' }}>
        <p className="mb-1.5 text-[10px] font-medium uppercase tracking-[0.08em] text-navy-400">Your response</p>
        <div className="space-y-1">
          <div className="h-2 w-3/4 rounded-full bg-navy-100" />
          <div className="h-2 w-1/2 rounded-full bg-navy-100" />
          <div className="h-2 w-2/3 rounded-full bg-navy-100" />
        </div>
      </div>
      <p className="mt-3 text-[11px] text-navy-400">Saved · Shared with your group</p>
    </div>
  )
}

export default function WhatHappensInside() {
  return (
    <section className="bg-white py-24 sm:py-32">
      <Container>

        <div className="mb-16 max-w-[480px]">
          <div className="mb-5 flex items-center gap-3">
            <div className="h-px w-8 bg-teal-400" />
            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600">
              What happens inside
            </span>
          </div>
          <h2
            className="mb-4 text-navy-950"
            style={{ fontSize: 'clamp(1.875rem, 3vw, 2.75rem)', letterSpacing: '-0.04em', lineHeight: '1.1' }}
          >
            Real structure.<br />Not just content.
          </h2>
          <p className="text-[16px] leading-[1.75] text-navy-400">
            Every element is designed to move you — not just inform you.
          </p>
        </div>

        <div className="grid gap-5 sm:grid-cols-2">
          <MockREALCard />
          <MockLiveCallCard />
          <MockRoomCard />
          <MockReflectionCard />
        </div>

      </Container>
    </section>
  )
}
