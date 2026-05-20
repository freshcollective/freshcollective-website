import { notFound, redirect } from 'next/navigation'
import Link from 'next/link'
import { getPathwayOverview } from '@/lib/serverApi'
import { getPathwayCoverStyle } from '@/lib/coverArt'
import { resolveMediaUrl } from '@/lib/api'
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
  // Use server-computed user_has_access — covers free, included, paid+entitlement, admin/creator
  const locked = !isComingSoon && !pathway.user_has_access

  // Redirect locked users to the About page (preview/sales page) instead of showing a wall
  if (locked) {
    redirect(`/spaces/${slug}/pathways/${pathwaySlug}/about`)
  }

  // For accessible users with steps, skip the overview and go straight to the right step.
  // First incomplete step wins; fall back to first step if all are complete.
  if (!isComingSoon && pathway.steps.length > 0) {
    const nextIncomplete = pathway.steps.find((s) => !s.is_completed)
    const continueSlug = nextIncomplete?.slug ?? pathway.steps[0].slug
    redirect(`/spaces/${slug}/pathways/${pathwaySlug}/${continueSlug}`)
  }

  const progressPct =
    pathway.step_count > 0
      ? Math.round((pathway.completed_count / pathway.step_count) * 100)
      : 0

  return (
    <div className="max-w-2xl">
      <div className="mb-6">
        <Link
          href={`/spaces/${slug}/pathways`}
          className="text-sm text-slate-400 transition-colors hover:text-teal-600"
        >
          ← All Pathways
        </Link>
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

      {/* ── Coming soon or accessible pathway view ── */}
      {isComingSoon ? (
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
