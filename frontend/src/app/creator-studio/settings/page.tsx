import Link from 'next/link'
import {
  getActiveCreatorSpace,
  getCreatorSpace,
  getCreatorPathways,
  getCreatorEvents,
} from '@/lib/serverApi'
import type {
  CreatorSpaceDetail,
  CreatorPathway,
  CreatorEvent,
} from '@/types/platform'
import CollectiveSettingsForm from './CollectiveSettingsForm'
import GuidancePanelForm from './GuidancePanelForm'

type StepStatus = 'not_started' | 'in_progress' | 'complete'

const STATUS_CONFIG: Record<StepStatus, { label: string; bg: string; color: string }> = {
  complete:    { label: 'Complete',    bg: 'rgba(56,160,158,0.10)', color: '#38A09E' },
  in_progress: { label: 'In progress', bg: 'rgba(212,176,72,0.12)', color: '#b08d2a' },
  not_started: { label: 'Not started', bg: 'rgba(0,0,0,0.05)',      color: '#94a3b8' },
}

async function _safe<T>(p: Promise<T>, slug: string, label: string, fallback: T): Promise<T> {
  try {
    return await p
  } catch (err) {
    // Log a useful development error but do NOT blank the page.
    console.error(`[creator-studio/settings] ${label} failed for ${slug}:`, err)
    return fallback
  }
}

export default async function SettingsPage() {
  const primarySpace = await getActiveCreatorSpace()

  const [spaceDetail, pathways, events]: [
    CreatorSpaceDetail | null,
    CreatorPathway[],
    CreatorEvent[],
  ] = primarySpace
    ? await Promise.all([
        _safe(
          getCreatorSpace(primarySpace.slug) as Promise<CreatorSpaceDetail | null>,
          primarySpace.slug, 'getCreatorSpace', null,
        ),
        _safe(getCreatorPathways(primarySpace.slug), primarySpace.slug, 'getCreatorPathways', []),
        _safe(getCreatorEvents(primarySpace.slug),   primarySpace.slug, 'getCreatorEvents',  []),
      ])
    : [null, [], []]

  if (primarySpace && !spaceDetail) {
    // Backend returned null (usually a 500). Log a clear error but continue
    // rendering the rest of the page — the launch checklist and top chrome
    // are still useful even when the collective detail failed.
    console.error(
      `[creator-studio/settings] Space detail could not be loaded for slug=${primarySpace.slug}. ` +
      `Check the backend logs; the panels that depend on it will show local error states.`,
    )
  }

  const hasStepContent = pathways.some((p) => p.step_count > 0)

  // Launch checklist — migrated verbatim from the retired Setup page.
  const checklist: {
    label: string
    desc: string
    status: StepStatus
    href: string
  }[] = [
    {
      label: 'Create your collective',
      desc: 'Set the name, tagline, description, and who it is for.',
      status: primarySpace ? 'complete' : 'not_started',
      href: '/creator-studio/create',
    },
    {
      label: 'Shape your first pathway',
      desc: 'Turn your ideas into a sequence people can move through.',
      status: pathways.length > 0 ? 'complete' : primarySpace ? 'in_progress' : 'not_started',
      href: primarySpace ? `/creator/spaces/${primarySpace.slug}/pathways` : '/creator',
    },
    {
      label: 'Add your first step',
      desc: 'Add text, video, reflection, or practice to begin the experience.',
      status: hasStepContent
        ? 'complete'
        : pathways.length > 0
        ? 'in_progress'
        : 'not_started',
      href:
        primarySpace && pathways[0]
          ? `/creator/spaces/${primarySpace.slug}/pathways/${pathways[0].slug}`
          : primarySpace
          ? `/creator/spaces/${primarySpace.slug}/pathways`
          : '/creator',
    },
    {
      label: 'Schedule your first gathering',
      desc: 'Create a live touchpoint, session, circle, workshop, or conversation.',
      status: events.length > 0 ? 'complete' : primarySpace ? 'in_progress' : 'not_started',
      href: primarySpace ? `/creator/spaces/${primarySpace.slug}/events/new` : '/creator',
    },
    {
      label: 'Publish your collective',
      desc: 'Open the doors when it is ready enough to hold people.',
      status:
        primarySpace?.status === 'active'
          ? 'complete'
          : primarySpace
          ? 'in_progress'
          : 'not_started',
      href: primarySpace ? `/creator/spaces/${primarySpace.slug}` : '/creator',
    },
  ]

  const doneCount = checklist.filter((c) => c.status === 'complete').length
  const allComplete = doneCount === checklist.length

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">

      <div className="mb-8">
        <p
          className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}
        >
          Creator Studio
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Settings</h1>
        <p className="mt-2 text-[15px] leading-relaxed" style={{ color: '#000000' }}>
          Manage your collective details, member experience, visibility, and setup progress.
        </p>
      </div>

      {!primarySpace && (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">No collective yet</p>
          <p className="mb-6 text-[14px] leading-relaxed text-black">
            Set up your collective first to access its settings.
          </p>
          <Link
            href="/build-your-collective"
            className="inline-flex items-center rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Build your collective
          </Link>
        </div>
      )}

      {primarySpace && !spaceDetail && (
        <div className="mb-5 rounded-2xl bg-white p-6" style={{ border: '1px solid rgba(166, 69, 38, 0.24)' }}>
          <p className="text-[14.5px] font-semibold" style={{ color: '#A64526' }}>
            We couldn&apos;t load the details for this collective.
          </p>
          <p className="mt-2 text-[13px] leading-relaxed text-black">
            The launch checklist below is still available. Please refresh the page in a moment, or check the backend logs for the actual exception.
          </p>
        </div>
      )}

      {spaceDetail && (
        <div className="space-y-5">
          {/* Existing settings form — identity, about, banner, visibility, pricing, creator profile */}
          <CollectiveSettingsForm space={spaceDetail} />

          {/* Migrated from Setup — Member experience "Important panel" */}
          <section
            className="overflow-hidden rounded-2xl bg-white"
            style={{ border: '1px solid rgba(56,160,158,0.18)', borderTop: '3px solid rgba(191,152,48,0.55)' }}
          >
            <div className="px-6 pt-6 pb-1">
              <h2 className="mb-1 text-[17px] font-semibold text-navy-900">Member Hub</h2>
              <p className="mb-5 text-[14px] text-black">
                Choose the information members see in the Member Hub displayed throughout your collective.
              </p>
            </div>
            <div className="px-6 pb-6">
              <div className="mb-5 flex items-center gap-2.5">
                <div
                  className="h-[2px] w-5 rounded-full"
                  style={{ background: 'linear-gradient(90deg, #BF9830 0%, transparent 100%)' }}
                />
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-black">
                  Important panel
                </p>
              </div>
              <GuidancePanelForm space={spaceDetail} />
            </div>
          </section>

          {/* Migrated from Setup — Launch checklist */}
          <section className="rounded-2xl border border-border bg-white p-6">
            <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
              <div>
                <h2 className="mb-1 text-[17px] font-semibold text-navy-900">Launch checklist</h2>
                <p className="text-[13px] text-black">
                  {doneCount} of {checklist.length} complete
                </p>
              </div>
              {allComplete && (
                <span
                  className="rounded-full px-3 py-1 text-[11px] font-bold uppercase tracking-wide"
                  style={{ background: 'rgba(56,160,158,0.10)', color: '#38A09E', border: '1px solid rgba(56,160,158,0.22)' }}
                >
                  Setup complete
                </span>
              )}
            </div>

            {allComplete ? (
              /* Compact summary when everything is done */
              <div
                className="rounded-2xl px-6 py-5"
                style={{ background: 'rgba(56,160,158,0.05)', border: '1px solid rgba(56,160,158,0.16)' }}
              >
                <p className="text-[14px] font-semibold" style={{ color: '#0C1826' }}>
                  Your collective is ready.
                </p>
                <p className="mt-0.5 text-[13px] text-black">
                  All five launch steps are complete. Keep growing at your own pace.
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  {checklist.map(({ label }) => (
                    <span
                      key={label}
                      className="flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[12px] font-medium"
                      style={{ background: 'rgba(56,160,158,0.08)', color: '#38A09E' }}
                    >
                      <svg width="8" height="6" viewBox="0 0 8 6" fill="none" aria-hidden="true">
                        <path d="M1 3l2 2 4-4" stroke="#38A09E" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                      {label}
                    </span>
                  ))}
                </div>
              </div>
            ) : (
              /* Full checklist while items remain */
              <div className="space-y-3">
                {checklist.map(({ label, desc, status, href }, i) => {
                  const cfg = STATUS_CONFIG[status]
                  return (
                    <div
                      key={label}
                      className="flex items-start gap-4 rounded-2xl border bg-white p-5"
                      style={{
                        borderColor:
                          status === 'complete'
                            ? 'rgba(56,160,158,0.22)'
                            : status === 'in_progress'
                            ? 'rgba(212,176,72,0.20)'
                            : '#e2e8f0',
                      }}
                    >
                      <div
                        className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold"
                        style={{
                          background:
                            status === 'complete' ? 'rgba(56,160,158,0.12)' : 'rgba(0,0,0,0.05)',
                          color: status === 'complete' ? '#38A09E' : '#94a3b8',
                          border:
                            status === 'complete'
                              ? '1.5px solid rgba(56,160,158,0.40)'
                              : '1.5px solid rgba(0,0,0,0.12)',
                        }}
                      >
                        {status === 'complete' ? (
                          <svg width="8" height="6" viewBox="0 0 8 6" fill="none" aria-hidden="true">
                            <path
                              d="M1 3l2 2 4-4"
                              stroke="#38A09E"
                              strokeWidth="1.5"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            />
                          </svg>
                        ) : (
                          String(i + 1)
                        )}
                      </div>

                      <div className="flex-1">
                        <div className="mb-1.5 flex flex-wrap items-center gap-2.5">
                          <p className="text-[15px] font-medium text-navy-900">{label}</p>
                          <span
                            className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
                            style={{ background: cfg.bg, color: cfg.color }}
                          >
                            {cfg.label}
                          </span>
                        </div>
                        <p className="text-[13.5px] leading-relaxed text-black">{desc}</p>
                        {status !== 'complete' && (
                          <Link
                            href={href}
                            className="mt-3 inline-block text-[13px] font-medium text-teal-600 transition-colors hover:text-teal-700"
                          >
                            {status === 'in_progress' ? 'Continue →' : 'Start this step →'}
                          </Link>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </section>
        </div>
      )}

    </div>
  )
}
