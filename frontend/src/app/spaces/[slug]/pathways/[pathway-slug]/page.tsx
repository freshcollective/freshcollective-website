import { notFound } from 'next/navigation'
import Link from 'next/link'
import { getPathwayOverview } from '@/lib/serverApi'
import { getPathwayCoverStyle } from '@/lib/coverArt'
import { resolveMediaUrl } from '@/lib/api'
import { isPathwayLocked, unlockCtaLabel, formatPathwayPrice } from '@/lib/pathwayAccess'
import PathwaySubNav from '@/components/spaces/PathwaySubNav'
import type { PathwayWithSteps, StepSummary } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string; 'pathway-slug': string }>
}

const CONTENT_TYPE_LABEL: Record<string, string> = {
  text: 'Read',
  reflection: 'Reflect',
  exercise: 'Exercise',
  video: 'Watch',
  audio: 'Listen',
}

function StepRow({
  step,
  spaceSlug,
  pathwaySlug,
  index,
}: {
  step: StepSummary
  spaceSlug: string
  pathwaySlug: string
  index: number
}) {
  const href = `/spaces/${spaceSlug}/pathways/${pathwaySlug}/${step.slug}`

  return (
    <Link
      href={href}
      className={[
        'group flex items-start gap-4 rounded-2xl border px-5 py-4 transition-all hover:-translate-y-0.5 hover:shadow-sm',
        step.is_completed
          ? 'border-teal-200 bg-teal-50/40 hover:border-teal-300'
          : 'border-border bg-white hover:border-teal-200',
      ].join(' ')}
    >
      <div
        className={[
          'mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
          step.is_completed
            ? 'bg-teal-500 text-white'
            : 'bg-teal-50 text-teal-600',
        ].join(' ')}
      >
        {step.is_completed ? '✓' : index + 1}
      </div>

      <div className="min-w-0 flex-1">
        <p
          className={[
            'font-medium leading-snug',
            step.is_completed ? 'text-teal-700' : 'text-navy-900',
          ].join(' ')}
        >
          {step.title}
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-slate-400">
          <span>{CONTENT_TYPE_LABEL[step.content_type] ?? step.content_type}</span>
          {step.estimated_minutes && <span>{step.estimated_minutes} min</span>}
        </div>
      </div>

      <span className="shrink-0 self-center text-slate-300 transition-colors group-hover:text-teal-500">
        →
      </span>
    </Link>
  )
}

export default async function PathwayDetailPage({ params }: Props) {
  const { slug, 'pathway-slug': pathwaySlug } = await params
  const pathway: PathwayWithSteps | null = await getPathwayOverview(slug, pathwaySlug)

  if (!pathway) notFound()

  const cs = getPathwayCoverStyle(pathwaySlug)
  const coverImageUrl = resolveMediaUrl(pathway.cover_image_url)
  const isComingSoon = pathway.status === 'coming_soon'
  const locked = !isComingSoon && isPathwayLocked(pathway.access_type)

  const progressPct =
    pathway.step_count > 0
      ? Math.round((pathway.completed_count / pathway.step_count) * 100)
      : 0

  const nextIncomplete = pathway.steps.find((s) => !s.is_completed)
  const continueHref = nextIncomplete
    ? `/spaces/${slug}/pathways/${pathwaySlug}/${nextIncomplete.slug}`
    : `/spaces/${slug}/pathways/${pathwaySlug}/${pathway.steps[0]?.slug}`

  const priceLabel = locked
    ? formatPathwayPrice(pathway.price_cents, pathway.currency, pathway.billing_interval)
    : null
  const unlockLabel = locked
    ? unlockCtaLabel(pathway.access_type, pathway.price_cents, pathway.currency, pathway.billing_interval)
    : null

  return (
    <div className="max-w-2xl">
      <div className="mb-4">
        <Link
          href={`/spaces/${slug}/pathways`}
          className="text-sm text-slate-400 transition-colors hover:text-teal-600"
        >
          ← All Pathways
        </Link>
      </div>
      <div className="mb-6">
        <PathwaySubNav spaceSlug={slug} pathwaySlug={pathwaySlug} activeTab="pathway" />
      </div>

      {/* ── Pathway hero banner ── */}
      <div
        className="relative mb-6 overflow-hidden rounded-2xl"
        style={{
          background: cs.background,
          backgroundSize: cs.backgroundSize ?? 'auto',
        }}
      >
        {/* Uploaded cover image — layers over CSS gradient */}
        {coverImageUrl && (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={coverImageUrl}
              alt=""
              aria-hidden="true"
              className="absolute inset-0 h-full w-full object-cover"
            />
            <div
              className="absolute inset-0"
              style={{
                background:
                  'linear-gradient(135deg, rgba(7,24,36,0.75) 0%, rgba(7,56,58,0.58) 100%)',
              }}
            />
          </>
        )}

        <div className="relative px-7 py-10 md:px-9 md:py-12">
          <div className="mb-3 h-[2px] w-8 rounded-full bg-teal-400" />
          <p
            className="mb-1 text-[9px] font-bold uppercase tracking-[0.20em]"
            style={{ color: coverImageUrl ? 'rgba(255,255,255,0.65)' : cs.labelColor }}
          >
            {isComingSoon ? 'Coming soon' : locked ? 'Pathway' : 'Pathway'}
          </p>
          <h2
            className="font-serif text-2xl md:text-3xl"
            style={{ color: coverImageUrl ? '#FFFFFF' : cs.titleColor }}
          >
            {pathway.title}
          </h2>
          {pathway.description && (
            <p
              className="mt-2.5 max-w-md text-[14px] leading-relaxed"
              style={{ color: (coverImageUrl || cs.isDark) ? 'rgba(255,255,255,0.72)' : '#64748B' }}
            >
              {pathway.description}
            </p>
          )}
        </div>
      </div>

      {/* ── Locked pathway view ── */}
      {locked ? (
        <div
          className="rounded-2xl border bg-white p-6"
          style={{ borderColor: 'rgba(56,160,158,0.20)' }}
        >
          <div className="flex items-start gap-4">
            <div
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
              style={{ background: 'rgba(56,160,158,0.08)' }}
            >
              <svg
                className="h-5 w-5 text-teal-500"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
                aria-hidden="true"
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
            </div>
            <div className="flex-1">
              <p className="font-serif text-[17px] text-navy-900">
                {pathway.access_type === 'subscription'
                  ? 'Monthly access required'
                  : 'Individual access required'}
              </p>
              {priceLabel && (
                <p className="mt-1 text-[14px] text-slate-500">
                  Available for{' '}
                  <span className="font-semibold text-navy-900">{priceLabel}</span>
                </p>
              )}
              {/* TODO: Route paid pathway unlock through checkout once Stripe is wired. */}
              <div
                className="mt-4 inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-[13px] font-medium"
                style={{ background: 'rgba(56,160,158,0.08)', color: '#073B3A' }}
              >
                <svg className="h-3.5 w-3.5 text-teal-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Unlock access — coming soon
              </div>
            </div>
          </div>
        </div>
      ) : isComingSoon ? (
        /* ── Coming soon view ── */
        <div className="rounded-2xl border border-teal-100 bg-white p-6 text-sm text-slate-500">
          This pathway is coming soon.
        </div>
      ) : (
        /* ── Accessible pathway view ── */
        <>
          {pathway.step_count > 0 && (
            <div className="mb-8">
              <div className="mb-1.5 flex items-baseline justify-between text-xs text-slate-400">
                <span>{pathway.completed_count} of {pathway.step_count} steps complete</span>
                <span>{progressPct}%</span>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-teal-100">
                <div
                  className="h-full rounded-full bg-teal-500 transition-all"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
            </div>
          )}

          {pathway.steps.length > 0 && continueHref && (
            <div className="mb-8">
              <Link
                href={continueHref}
                className="inline-block rounded-full px-5 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90"
                style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
              >
                {pathway.completed_count === 0 ? 'Begin' : pathway.completed_count >= pathway.step_count ? 'Review' : 'Continue'}
              </Link>
            </div>
          )}

          {pathway.steps.length === 0 ? (
            <div className="rounded-2xl border border-teal-100 bg-white p-6 text-sm text-slate-500">
              Steps for this pathway are coming soon.
            </div>
          ) : pathway.sections.length > 0 ? (
            /* Section-grouped view */
            <div className="flex flex-col gap-6">
              {(() => {
                const sectionedIds = new Set(pathway.sections.flatMap((s) => s.steps.map((st) => st.id)))
                const unsectioned = pathway.steps.filter((s) => !sectionedIds.has(s.id))
                let globalIndex = 0
                const groups: React.ReactNode[] = []

                // Sections first (in position order as returned by backend)
                pathway.sections.forEach((section) => {
                  groups.push(
                    <div key={section.id}>
                      <p className="mb-3 text-[13px] font-semibold text-slate-600">
                        {section.title}
                      </p>
                      <div className="flex flex-col gap-3">
                        {section.steps.map((step) => {
                          const el = <StepRow key={step.id} step={step} spaceSlug={slug} pathwaySlug={pathwaySlug} index={globalIndex} />
                          globalIndex++
                          return el
                        })}
                      </div>
                    </div>
                  )
                })

                // Unsectioned steps at the bottom
                if (unsectioned.length > 0) {
                  groups.push(
                    <div key="__unsectioned" className="flex flex-col gap-3">
                      {unsectioned.map((step) => {
                        const el = <StepRow key={step.id} step={step} spaceSlug={slug} pathwaySlug={pathwaySlug} index={globalIndex} />
                        globalIndex++
                        return el
                      })}
                    </div>
                  )
                }

                return groups
              })()}
            </div>
          ) : (
            /* Flat list (no sections) */
            <div className="flex flex-col gap-3">
              {pathway.steps.map((step, i) => (
                <StepRow
                  key={step.id}
                  step={step}
                  spaceSlug={slug}
                  pathwaySlug={pathwaySlug}
                  index={i}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
