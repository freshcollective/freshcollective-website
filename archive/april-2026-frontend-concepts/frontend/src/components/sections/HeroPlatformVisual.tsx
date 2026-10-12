const PHASES = [
  { letter: 'R', name: 'Recognise', active: true  },
  { letter: 'E', name: 'Explore',   active: false },
  { letter: 'A', name: 'Align',     active: false },
  { letter: 'L', name: 'Lead',      active: false },
]

export default function HeroPlatformVisual() {
  return (
    <div className="relative w-full select-none" aria-hidden="true">
      <div
        className="relative overflow-hidden rounded-2xl bg-white"
        style={{
          border: '1px solid rgba(0,0,0,0.08)',
          boxShadow:
            '0 0 0 1px rgba(0,0,0,0.03), 0 4px 12px rgba(0,0,0,0.05), 0 16px 48px rgba(0,0,0,0.07), 0 40px 96px rgba(0,0,0,0.04)',
        }}
      >
        {/* Top teal accent line */}
        <div
          className="h-px w-full"
          style={{ background: 'linear-gradient(to right, #38A09E, #7FCFCD 60%, rgba(0,0,0,0.04))' }}
        />

        {/* Platform header */}
        <div
          className="flex items-center justify-between px-5 py-3.5"
          style={{ borderBottom: '1px solid rgba(0,0,0,0.06)' }}
        >
          <div className="flex items-center gap-2">
            <div className="flex h-5 w-5 items-center justify-center rounded-md bg-teal-500">
              <div className="h-2 w-2 rounded-sm bg-white" />
            </div>
            <span className="text-[12px] font-semibold tracking-[-0.01em] text-navy-950">
              Fresh Collective
            </span>
          </div>
          <div
            className="flex items-center gap-1.5 rounded-full bg-teal-50 px-2.5 py-1"
            style={{ border: '1px solid rgba(56,160,158,0.2)' }}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-teal-500" />
            <span className="text-[10px] font-semibold text-teal-700">Active member</span>
          </div>
        </div>

        {/* REAL Journey section */}
        <div className="px-5 pt-4 pb-3">
          <p className="mb-3 text-[10px] font-medium text-[#999]">REAL Journey · Phase 1 of 4</p>

          {/* Phase progress track */}
          <div className="relative mb-3.5">
            <div className="absolute inset-y-[11px] left-3 right-3 h-px bg-[#EBEBEB]" />
            <div className="absolute inset-y-[11px] left-3 h-px w-[12%] bg-teal-400" />
            <div className="relative flex justify-between">
              {PHASES.map(({ letter, name, active }) => (
                <div key={letter} className="flex flex-col items-center gap-1.5">
                  <div
                    className={`relative z-10 flex h-[22px] w-[22px] items-center justify-center rounded-full text-[10px] font-bold ${
                      active ? 'bg-teal-500 text-white' : 'bg-white text-[#CCC]'
                    }`}
                    style={
                      active
                        ? { boxShadow: '0 0 0 3px rgba(56,160,158,0.14)' }
                        : { border: '1.5px solid #E4E4E4' }
                    }
                  >
                    {letter}
                  </div>
                  <span
                    className={`text-[9px] font-medium ${active ? 'text-navy-900' : 'text-[#CCC]'}`}
                  >
                    {name}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Active phase detail */}
          <div
            className="rounded-xl px-4 py-3.5"
            style={{
              background: 'rgba(56,160,158,0.05)',
              border: '1px solid rgba(56,160,158,0.12)',
            }}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-[11px] font-semibold text-teal-800">Phase 1 · Recognise</p>
                <p className="mt-0.5 text-[10px] leading-relaxed text-teal-600/70">
                  Seeing clearly what is true right now.
                </p>
              </div>
              <svg
                className="mt-0.5 shrink-0 text-teal-300"
                width="12"
                height="12"
                viewBox="0 0 12 12"
                fill="none"
              >
                <path
                  d="M4 2l4 4-4 4"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </div>

            <div className="mt-3 flex items-center gap-2">
              <div className="h-1 flex-1 rounded-full bg-teal-100">
                <div className="h-full w-[15%] rounded-full bg-teal-400" />
              </div>
              <span className="text-[9px] font-medium text-teal-500">15%</span>
            </div>
          </div>
        </div>

        {/* Separator */}
        <div className="mx-5 h-px bg-[#F0F0EE]" />

        {/* Library + Community panels */}
        <div className="grid grid-cols-2 gap-3 p-4">
          <div
            className="rounded-xl p-3"
            style={{ background: '#F8F9FA', border: '1px solid rgba(0,0,0,0.05)' }}
          >
            <div
              className="mb-2 flex h-6 w-6 items-center justify-center rounded-lg bg-white"
              style={{ border: '1px solid rgba(0,0,0,0.07)' }}
            >
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                <rect x="1" y="1" width="4" height="4" rx="0.75" fill="#38A09E" fillOpacity="0.55" />
                <rect x="7" y="1" width="4" height="4" rx="0.75" fill="#38A09E" fillOpacity="0.3" />
                <rect x="1" y="7" width="4" height="4" rx="0.75" fill="#38A09E" fillOpacity="0.25" />
                <rect x="7" y="7" width="4" height="4" rx="0.75" fill="#38A09E" fillOpacity="0.12" />
              </svg>
            </div>
            <p className="text-[10px] font-semibold text-navy-950">Content Library</p>
            <p className="mt-0.5 text-[9px] text-[#999]">Practices · Tools</p>
          </div>

          <div
            className="rounded-xl p-3"
            style={{ background: '#F8F9FA', border: '1px solid rgba(0,0,0,0.05)' }}
          >
            <div className="mb-2 flex items-center gap-1">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-400" />
              <span className="text-[9px] font-medium text-amber-600">Live</span>
            </div>
            <p className="text-[10px] font-semibold text-navy-950">The Heart</p>
            <p className="mt-0.5 text-[9px] text-[#999]">Monthly calls</p>
          </div>
        </div>

        {/* Social proof */}
        <div
          className="flex items-center justify-between px-5 py-3"
          style={{ borderTop: '1px solid rgba(0,0,0,0.05)' }}
        >
          <div className="flex -space-x-1.5">
            {(['#55B8B6', '#7FCFCD', '#AAE1E0', '#D5F0EF'] as const).map((c, i) => (
              <div
                key={i}
                className="h-5 w-5 rounded-full border-2 border-white"
                style={{ background: c }}
              />
            ))}
          </div>
          <p className="text-[10px] text-[#BBB]">42 members in The Heart</p>
        </div>
      </div>
    </div>
  )
}
