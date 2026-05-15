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
      href: activeSpace ? `/creator/spaces/${activeSpace.slug}/pathways` : '/creator-studio/create',
    },
    {
      label: 'First gathering scheduled',
      done: events.length > 0,
      href: activeSpace ? `/creator/spaces/${activeSpace.slug}/events/new` : '/creator-studio/create',
    },
    {
      label: 'Collective published',
      done: activeSpace?.status === 'active',
      href: activeSpace ? `/creator/spaces/${activeSpace.slug}` : '/creator-studio/create',
    },
  ]

  const allDone = checklist.every((c) => c.done)
  const isEarlyStage = activeSpace && pathways.length === 0
  const atLimit = spaces.length >= MAX_COLLECTIVES_FOR_FOUNDING_CREATOR

  return (
    <div className="max-w-4xl px-8 py-8 md:px-10 md:py-10">

      {/* Page header */}
      <div className="mb-8">
        <p
          className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}
        >
          Creator Studio
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">
          Welcome to your Creator Studio.
        </h1>
        <p className="mt-2 text-[15px] leading-relaxed" style={{ color: '#334155' }}>
          Build, shape, and manage the collective you wish existed.
        </p>
      </div>

      {/* Empty state — no collective yet */}
      {!activeSpace && (
        <div
          className="mb-6 overflow-hidden rounded-xl border"
          style={{
            borderColor: 'rgba(56,160,158,0.20)',
            background: 'linear-gradient(135deg, #071824 0%, #073B3A 100%)',
          }}
        >
          <div className="px-8 py-10">
            <p
              className="mb-1 text-[11px] font-semibold uppercase tracking-[0.16em]"
              style={{ color: '#8DE8E6' }}
            >
              Get started
            </p>
            <p className="mb-3 font-serif text-xl text-white">Create your first collective.</p>
            <p className="mb-6 max-w-md text-[14px] leading-relaxed" style={{ color: 'rgba(255,255,255,0.75)' }}>
              Start by giving your work a home. You can create up to{' '}
              {MAX_COLLECTIVES_FOR_FOUNDING_CREATOR} collectives with Founding Creator access.
            </p>
            <Link
              href="/creator-studio/create"
              className="inline-flex items-center rounded-lg px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
            >
              Create collective
            </Link>
          </div>
        </div>
      )}

      {activeSpace && (
        <>
          {/* Next step card */}
          {!allDone && (
            <div
              className="mb-6 rounded-xl border px-7 py-6"
              style={{
                borderColor: 'rgba(56,160,158,0.18)',
                background: 'linear-gradient(135deg, #071824 0%, #073B3A 100%)',
              }}
            >
              <p
                className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em]"
                style={{ color: '#8DE8E6' }}
              >
                {isEarlyStage ? 'Getting started' : 'Next step'}
              </p>
              <p className="mb-2 font-serif text-xl text-white">
                {isEarlyStage
                  ? 'Start with your collective foundation.'
                  : 'Your collective is taking shape.'}
              </p>
              <p
                className="mb-5 max-w-md text-[14px] leading-relaxed"
                style={{ color: 'rgba(255,255,255,0.75)' }}
              >
                {isEarlyStage
                  ? 'Name your collective, describe who it is for, and define the change your work helps people practise.'
                  : 'Keep building the pathways, gatherings, and resources that will help people move through the work.'}
              </p>
              <Link
                href={
                  isEarlyStage
                    ? `/creator/spaces/${activeSpace.slug}`
                    : `/creator/spaces/${activeSpace.slug}/pathways`
                }
                className="inline-flex items-center rounded-lg px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
                style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
              >
                {isEarlyStage ? 'Set up collective' : 'Continue building'}
              </Link>
            </div>
          )}

          {/* Stats */}
          <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { label: 'Pathways', value: pathways.length },
              { label: 'Published', value: activePathways.length },
              { label: 'Gatherings', value: events.length },
              { label: 'Upcoming', value: upcoming.length },
            ].map(({ label, value }) => (
              <div key={label} className="rounded-xl border border-border bg-white p-4">
                <p className="font-serif text-2xl text-navy-900">{value}</p>
                <p className="mt-0.5 text-[13px] text-slate-500">{label}</p>
              </div>
            ))}
          </div>

          {/* Condensed checklist */}
          {!allDone && (
            <div className="mb-6 rounded-xl border border-border bg-white p-6">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-[17px] font-semibold text-navy-900">Setup progress</h2>
                <Link
                  href="/creator-studio/setup"
                  className="text-[13px] font-medium text-teal-600 transition-colors hover:text-teal-700"
                >
                  Full checklist →
                </Link>
              </div>
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

          {/* Quick actions */}
          <div className="mb-8 grid gap-3 sm:grid-cols-3">
            {[
              {
                label: 'Build pathways',
                desc: pathways.length > 0
                  ? `${pathways.length} pathway${pathways.length !== 1 ? 's' : ''}`
                  : 'No pathways yet',
                href: `/creator/spaces/${activeSpace.slug}/pathways`,
              },
              {
                label: 'Schedule a gathering',
                desc: upcoming.length > 0 ? `${upcoming.length} coming up` : 'No upcoming gatherings',
                href: `/creator/spaces/${activeSpace.slug}/events/new`,
              },
              {
                label: 'Engage community',
                desc: 'Posts, prompts, and discussion',
                href: `/creator/spaces/${activeSpace.slug}/community`,
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
        </>
      )}

      {/* Your collectives */}
      <div className="rounded-xl border border-border bg-white p-6">
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
          <p className="text-[14px] text-slate-500">
            No collectives yet.{' '}
            <Link href="/creator-studio/create" className="text-teal-600 hover:text-teal-700">
              Create your first →
            </Link>
          </p>
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

        {atLimit && (
          <div
            className="mt-4 rounded-xl p-4"
            style={{
              background: 'rgba(56,160,158,0.05)',
              border: '1px solid rgba(56,160,158,0.16)',
            }}
          >
            <p className="mb-0.5 text-[13px] font-semibold text-navy-900">
              Need more than {MAX_COLLECTIVES_FOR_FOUNDING_CREATOR} collectives?
            </p>
            <p className="mb-2 text-[12px] text-slate-500">
              Creator Plus is coming soon for creators who want to run additional collectives under one account.
            </p>
            <span
              className="inline-block rounded-lg px-3 py-1.5 text-[12px] font-medium"
              style={{
                background: 'rgba(56,160,158,0.10)',
                color: '#38A09E',
                cursor: 'default',
              }}
            >
              Coming soon
            </span>
          </div>
        )}
      </div>

    </div>
  )
}
