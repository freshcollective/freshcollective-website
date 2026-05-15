import Link from 'next/link'
import { getCreatorSpaces, getActiveCreatorSpace, getCreatorPathways, getCreatorEvents } from '@/lib/serverApi'
import { MAX_COLLECTIVES_FOR_FOUNDING_CREATOR } from '@/lib/creatorPlan'
import type { CreatorPathway, CreatorEvent, SpaceSummary } from '@/types/platform'
import CollectiveRow from './CollectiveRow'

export default async function CreatorStudioOverviewPage() {
  const [spaces, activeSpace]: [SpaceSummary[], SpaceSummary | null] = await Promise.all([
    getCreatorSpaces(),
    getActiveCreatorSpace(),
  ])

  const [pathways, events]: [CreatorPathway[], CreatorEvent[]] = activeSpace
    ? await Promise.all([
        getCreatorPathways(activeSpace.slug),
        getCreatorEvents(activeSpace.slug),
      ])
    : [[], []]

  const now = new Date()
  const upcoming = events.filter((e) => new Date(e.starts_at) > now)
  const activePathways = pathways.filter((p) => p.status === 'active')

  const checklist = [
    {
      label: 'Collective created',
      done: !!activeSpace,
      href: '/creator-studio/create',
    },
    {
      label: 'First pathway added',
      done: pathways.length > 0,
      href: '/creator-studio/pathways',
    },
    {
      label: 'First gathering scheduled',
      done: events.length > 0,
      href: '/creator-studio/gatherings',
    },
    {
      label: 'Collective published',
      done: activeSpace?.status === 'active',
      href: '/creator-studio/settings',
    },
  ]

  const allDone = checklist.every((c) => c.done)
  const atLimit = spaces.length >= MAX_COLLECTIVES_FOR_FOUNDING_CREATOR

  return (
    <div className="max-w-4xl px-8 py-8 md:px-10 md:py-10 space-y-6">

      {/* ── 1. Page header ── */}
      <div>
        <p
          className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}
        >
          Studio Home
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">
          Welcome to your Creator Studio.
        </h1>
        <p className="mt-2 text-[15px] leading-relaxed" style={{ color: '#334155' }}>
          All your collectives, at a glance. Select one to start building.
        </p>
      </div>

      {/* ── 2. Your collectives ── */}
      <div className="rounded-2xl border border-border bg-white p-6">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-[17px] font-semibold text-navy-900">Your collectives</h2>
          {!atLimit ? (
            <Link
              href="/creator-studio/create"
              className="text-[13px] font-medium text-teal-600 transition-colors hover:text-teal-700"
            >
              + Create new collective
            </Link>
          ) : (
            <span className="text-[12px] text-slate-500">
              {spaces.length} of {MAX_COLLECTIVES_FOR_FOUNDING_CREATOR} collectives used
            </span>
          )}
        </div>

        {spaces.length === 0 ? (
          <div className="py-4 text-center">
            <p className="mb-4 text-[14px] text-slate-500">No collectives yet.</p>
            <Link
              href="/creator-studio/create"
              className="inline-flex items-center rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
            >
              Create your first collective
            </Link>
          </div>
        ) : (
          <div className="space-y-2.5">
            {spaces.map((s) => (
              <CollectiveRow
                key={s.id}
                space={s}
                isActive={s.slug === activeSpace?.slug}
              />
            ))}
          </div>
        )}

        {!atLimit && spaces.length > 0 && (
          <p className="mt-4 text-[12px] text-slate-400">
            Founding Creator access includes up to {MAX_COLLECTIVES_FOR_FOUNDING_CREATOR} collectives.
          </p>
        )}
      </div>

      {/* ── 3. Currently working on ── */}
      <div className="rounded-2xl border border-border bg-white p-6">
        <h2 className="mb-1 text-[17px] font-semibold text-navy-900">Currently working on</h2>

        {!activeSpace ? (
          <p className="text-[14px] text-slate-400">
            Select a collective above to see its next steps.
          </p>
        ) : (
          <>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <span className="font-sans text-[20px] font-semibold text-navy-900">{activeSpace.name}</span>
              <span
                className="rounded-full px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wide"
                style={{
                  background: activeSpace.status === 'active' ? 'rgba(56,160,158,0.12)' : 'rgba(0,0,0,0.06)',
                  color: activeSpace.status === 'active' ? '#38A09E' : '#94a3b8',
                }}
              >
                {activeSpace.status === 'active' ? 'Active' : 'Draft'}
              </span>
            </div>
            {activeSpace.tagline && (
              <p className="mt-1.5 text-[14px] text-slate-500">{activeSpace.tagline}</p>
            )}
            <p className="mt-3 text-[13px]" style={{ color: '#64748b' }}>
              The stats, setup progress, and quick actions below all relate to this collective.
            </p>
          </>
        )}
      </div>

      {/* ── 4. Stats ── (only shown if active collective exists) */}
      {activeSpace && (
        <div>
          <p
            className="mb-3 text-[11px] font-semibold uppercase tracking-[0.16em]"
            style={{ color: '#38A09E' }}
          >
            Selected collective snapshot
          </p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { label: 'Pathways',   value: pathways.length },
              { label: 'Published',  value: activePathways.length },
              { label: 'Gatherings', value: events.length },
              { label: 'Upcoming',   value: upcoming.length },
            ].map(({ label, value }) => (
              <div key={label} className="rounded-xl border border-border bg-white p-4">
                <p className="font-serif text-2xl text-navy-900">{value}</p>
                <p className="mt-0.5 text-[13px] text-slate-500">{label}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── 5. Setup progress ── */}
      {activeSpace && !allDone && (
        <div className="rounded-2xl border border-border bg-white p-6">
          <div className="mb-1 flex items-center justify-between gap-3">
            <h2 className="text-[17px] font-semibold text-navy-900">Setup progress</h2>
            <Link
              href="/creator-studio/setup"
              className="text-[13px] font-medium text-teal-600 transition-colors hover:text-teal-700"
            >
              Full checklist →
            </Link>
          </div>
          <p className="mb-4 text-[13px] text-slate-400">
            For {activeSpace.name}
          </p>
          <ul className="space-y-3">
            {checklist.map(({ label, done, href }) => (
              <li key={label} className="flex items-center gap-3">
                <div
                  className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full"
                  style={{
                    background: done ? 'rgba(56,160,158,0.12)' : 'rgba(0,0,0,0.05)',
                    border: done
                      ? '1.5px solid rgba(56,160,158,0.40)'
                      : '1.5px solid rgba(0,0,0,0.12)',
                  }}
                >
                  {done && (
                    <svg width="8" height="6" viewBox="0 0 8 6" fill="none" aria-hidden="true">
                      <path
                        d="M1 3l2 2 4-4"
                        stroke="#38A09E"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  )}
                </div>
                <span
                  className="flex-1 text-[14px]"
                  style={{ color: done ? 'rgba(0,0,0,0.36)' : '#1e293b' }}
                >
                  {label}
                </span>
                {!done && (
                  <Link
                    href={href}
                    className="text-[13px] font-medium text-teal-600 transition-colors hover:text-teal-700"
                  >
                    Do this →
                  </Link>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ── 6. Quick actions ── */}
      {activeSpace && (
        <div>
          <p
            className="mb-3 text-[11px] font-semibold uppercase tracking-[0.16em]"
            style={{ color: '#38A09E' }}
          >
            Next actions for {activeSpace.name}
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {[
              {
                label: 'Collective overview',
                desc: 'Stats, next steps, quick actions',
                href: '/creator-studio/collective',
              },
              {
                label: 'Build pathways',
                desc: pathways.length > 0
                  ? `${pathways.length} pathway${pathways.length !== 1 ? 's' : ''}`
                  : 'No pathways yet',
                href: '/creator-studio/pathways',
              },
              {
                label: 'Schedule gathering',
                desc: upcoming.length > 0 ? `${upcoming.length} coming up` : 'None scheduled',
                href: '/creator-studio/gatherings',
              },
              {
                label: 'Engage community',
                desc: 'Posts, prompts, and discussion',
                href: '/creator-studio/community',
              },
            ].map(({ label, desc, href }) => (
              <Link
                key={href}
                href={href}
                className="group rounded-xl border border-border bg-white p-5 transition-all hover:border-teal-200 hover:shadow-sm"
              >
                <p className="text-[14px] font-medium text-navy-900 transition-colors group-hover:text-teal-700">
                  {label}
                </p>
                <p className="mt-1 text-[13px] text-slate-500">{desc}</p>
              </Link>
            ))}
          </div>
        </div>
      )}

      {/* ── 7. Creator Plus / limit ── */}
      {atLimit && (
        <div
          className="rounded-2xl p-6"
          style={{
            background: 'rgba(56,160,158,0.05)',
            border: '1px solid rgba(56,160,158,0.16)',
          }}
        >
          <p className="mb-1 text-[14px] font-semibold text-navy-900">
            Need more than {MAX_COLLECTIVES_FOR_FOUNDING_CREATOR} collectives?
          </p>
          <p className="mb-4 text-[13px] text-slate-500">
            Creator Plus is coming soon for creators who want to run additional collectives under one account.
          </p>
          <span
            className="inline-block rounded-xl px-5 py-2.5 text-[13px] font-medium"
            style={{
              background: 'rgba(56,160,158,0.10)',
              color: '#38A09E',
              cursor: 'default',
            }}
          >
            Creator Plus coming soon
          </span>
        </div>
      )}

    </div>
  )
}
