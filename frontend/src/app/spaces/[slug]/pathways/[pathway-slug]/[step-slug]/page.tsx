import React from 'react'
import { notFound, redirect } from 'next/navigation'
import Link from 'next/link'
import { getStep, getPathwayOverview, getStepResources, getStepBlocks, getStepComments, getSpace } from '@/lib/serverApi'
import type { CollectivePaletteMeta } from '@/lib/collectivePalette'
import PathwayAutoRevalidate from '@/components/spaces/PathwayAutoRevalidate'
import { resolveMediaUrl } from '@/lib/api'
import StepActions from '@/components/spaces/StepActions'
import StepDiscussion from '@/components/spaces/StepDiscussion'
import { renderBlocks } from '@/components/spaces/BlockList'
import PathwayStepNav from '@/components/spaces/PathwayStepNav'
import type { PathwayWithSteps, StepDetail, StepSummary, StepResource, StepBlock, StepComment } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string; 'pathway-slug': string; 'step-slug': string }>
}

const CONTENT_TYPE_LABEL: Record<string, string> = {
  text: 'Read',
  reflection: 'Reflect',
  exercise: 'Exercise',
  video: 'Watch',
  audio: 'Listen',
}

function renderContent(body: string): React.ReactNode {
  return body
    .split('\n\n')
    .map((block, i) => {
      const trimmed = block.trim()
      if (!trimmed) return null

      if (trimmed.startsWith('**') && trimmed.endsWith('**') && !trimmed.slice(2, -2).includes('\n')) {
        return (
          <h3 key={i} className="mb-3 mt-9 font-semibold text-[1.1rem] text-navy-900 first:mt-0">
            {trimmed.slice(2, -2)}
          </h3>
        )
      }

      if (trimmed === '---') {
        return <hr key={i} className="my-10 border-border" />
      }

      if (trimmed.split('\n').every((l) => l.trimStart().startsWith('- '))) {
        const items = trimmed.split('\n').map((l) => l.replace(/^- /, '').trim())
        return (
          <ul key={i} className="my-5 space-y-2.5 pl-5">
            {items.map((item, j) => (
              <li
                key={j}
                className="relative text-[15px] leading-[1.8] text-black before:absolute before:-left-5 before:text-slate-300 before:content-['–']"
              >
                {item}
              </li>
            ))}
          </ul>
        )
      }

      const parts = trimmed.split(/(\*\*[^*]+\*\*)/)
      return (
        <p key={i} className="my-5 text-[15px] leading-[1.85] text-black first:mt-0 last:mb-0">
          {parts.map((part, j) =>
            part.startsWith('**') && part.endsWith('**') ? (
              <strong key={j} className="font-semibold text-navy-800">
                {part.slice(2, -2)}
              </strong>
            ) : (
              part
            ),
          )}
        </p>
      )
    })
    .filter(Boolean)
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'


const RESOURCE_GROUP: Record<string, string> = {
  video: 'Watch',
  audio: 'Listen',
  pdf: 'Download',
  file: 'Download',
  link: 'Links',
}

const RESOURCE_ACTION: Record<string, string> = {
  video: 'Watch',
  audio: 'Listen',
  pdf: 'Download',
  file: 'Open',
  link: 'Open',
}

function resourceHref(resource: StepResource): string {
  if (!resource.url) return '#'
  return resource.url.startsWith('http')
    ? resource.url
    : `${API_BASE}/api/uploads/${resource.url}`
}

function StepResourceList({ resources }: { resources: StepResource[] }) {
  const groups = ['Watch', 'Listen', 'Download', 'Links']
  const grouped: Record<string, StepResource[]> = {}
  for (const r of resources) {
    const g = RESOURCE_GROUP[r.resource_type] ?? 'Links'
    ;(grouped[g] ??= []).push(r)
  }

  return (
    <div className="flex flex-col gap-6">
      {groups
        .filter((g) => grouped[g]?.length)
        .map((group) => (
          <div key={group}>
            <p className="mb-2.5 text-xs font-semibold uppercase tracking-widest text-black">
              {group}
            </p>
            <div className="flex flex-col gap-2">
              {grouped[group].map((resource) => (
                <a
                  key={resource.id}
                  href={resourceHref(resource)}
                  target="_blank"
                  rel="noopener noreferrer"
                  download={resource.is_downloadable && resource.file_name ? resource.file_name : undefined}
                  className="group flex items-start justify-between gap-4 rounded-xl border border-border bg-surface px-4 py-3 transition-colors hover:border-navy-200 hover:bg-white"
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-navy-900 group-hover:underline underline-offset-2">
                      {resource.title}
                    </p>
                    {resource.description && (
                      <p className="mt-0.5 text-xs leading-relaxed text-black">
                        {resource.description}
                      </p>
                    )}
                  </div>
                  <span className="shrink-0 rounded-full border border-border bg-white px-2.5 py-1 text-xs font-medium text-black group-hover:border-navy-300 group-hover:text-navy-700">
                    {RESOURCE_ACTION[resource.resource_type] ?? 'Open'} ↗
                  </span>
                </a>
              ))}
            </div>
          </div>
        ))}
    </div>
  )
}

export default async function StepPage({ params }: Props) {
  const { slug, 'pathway-slug': pathwaySlug, 'step-slug': stepSlug } = await params

  const [step, overview, resources, blocks, comments, space]: [
    StepDetail | null,
    PathwayWithSteps | null,
    StepResource[],
    StepBlock[],
    StepComment[],
    { colour_palette?: CollectivePaletteMeta | null } | null,
  ] = await Promise.all([
    getStep(slug, pathwaySlug, stepSlug),
    getPathwayOverview(slug, pathwaySlug),
    getStepResources(slug, pathwaySlug, stepSlug),
    getStepBlocks(slug, pathwaySlug, stepSlug),
    getStepComments(slug, pathwaySlug, stepSlug),
    getSpace(slug),
  ])
  // The active palette resolves ``palette:<role>`` block colours to
  // hex at render time. Null when the collective has not yet chosen a
  // palette; the resolvers fall through to legacy/default handling.
  const collectivePalette: CollectivePaletteMeta | null = space?.colour_palette ?? null

  // Knowledge Guides are rendered as one continuous document on the
  // pathway landing — every step URL forwards to the same page,
  // anchored to the step's section on the continuous document.
  // Preserves bookmarks and notification deep-links after a pathway
  // is switched to Knowledge Guide.
  if (overview?.pathway_type === 'knowledge_guide') {
    redirect(`/spaces/${slug}/pathways/${pathwaySlug}#step-${stepSlug}`)
  }

  if (!step) notFound()

  // Locked step — the server has already stripped the reading body.
  // Render a calm "Waiting" panel instead of the full reader; the
  // sidebar-full page reappears once the step unlocks. When we know
  // when it unlocks, PathwayAutoRevalidate arms a timer so the page
  // flips itself at that moment.
  if (step.availability?.is_locked) {
    const av = step.availability
    // Gather every upcoming unlock across the pathway, not just this
    // step — a member sitting on a locked step might well unlock a
    // sibling step first, and we want the sidebar counts to catch up.
    const pathwayUnlocks = (overview?.steps ?? [])
      .map((s) => s.availability?.unlocks_at)
      .filter((v): v is string => !!v)
    const revalidateAt = av.unlocks_at
      ? [av.unlocks_at, ...pathwayUnlocks]
      : pathwayUnlocks
    return (
      <div>
        <PathwayAutoRevalidate upcomingUnlocks={revalidateAt} />
        <div className="mb-6">
          <Link
            href={`/spaces/${slug}/pathways/${pathwaySlug}`}
            className="text-sm text-black transition-colors hover:text-navy-700"
          >
            ← {overview?.title ?? 'Pathway'}
          </Link>
        </div>
        <div
          className="mx-auto max-w-xl rounded-2xl bg-white px-8 py-10 text-center"
          style={{ border: '1px solid rgba(12,24,38,0.08)', boxShadow: '0 4px 20px rgba(12,24,38,0.05)' }}
        >
          <div className="mb-4 text-4xl" aria-hidden="true">🔒</div>
          <h1 className="mb-2 font-serif text-2xl text-navy-900">{step.title}</h1>
          <p className="mb-4 text-[15px] leading-relaxed" style={{ color: 'rgba(12,24,38,0.65)', fontFamily: 'Georgia, serif' }}>
            {av.message ?? 'Not available yet.'}
          </p>
          {av.unlocks_at && (
            <p className="text-[13px] text-slate-500">
              Available on {new Date(av.unlocks_at).toLocaleString('en-AU', {
                weekday: 'long', day: 'numeric', month: 'long',
                hour: 'numeric', minute: '2-digit', hour12: true,
              })}
              {av.release_timezone ? ` ${av.release_timezone}` : ''}
            </p>
          )}
        </div>
      </div>
    )
  }

  const allSteps: StepSummary[] = overview?.steps ?? []
  const currentIndex = allSteps.findIndex((s) => s.slug === stepSlug)
  const prevStep = currentIndex > 0 ? allSteps[currentIndex - 1] : null
  const nextStep = currentIndex < allSteps.length - 1 ? allSteps[currentIndex + 1] : null

  const pathwayHref = `/spaces/${slug}/pathways`
  const pathwayTitle = overview?.title ?? 'Pathway'
  const completedCount = allSteps.filter((s) => s.is_completed).length
  const totalCount = allSteps.length
  const sections = overview?.sections ?? []

  return (
    <div>

      {/* ── Quiet pathway breadcrumb ──
          The large tinted banner was noise now that the Collective hero,
          left step navigator, and article title all communicate context.
          A compact two-line label preserves orientation without pushing
          the reading experience down the page. */}
      {overview && (
        <div className="mb-6">
          <Link
            href={pathwayHref}
            className="font-serif text-[15px] text-navy-900 transition-colors hover:text-teal-700"
          >
            {overview.title}
          </Link>
          {totalCount > 0 && currentIndex >= 0 && (
            <p className="mt-0.5 text-[12px] text-black">
              Step {currentIndex + 1} of {totalCount}
            </p>
          )}
        </div>
      )}

      {/* Two-column layout: sidebar on left (desktop), collapsed nav on mobile.
          On mobile the flex-col means PathwayStepNav renders its collapsible button
          at the top before the step content. On desktop (lg:) it becomes a sticky
          left sidebar alongside the content column. */}
      <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:gap-8">

      {/* ── Left: pathway step nav ── */}
      <div className="lg:w-[320px] lg:shrink-0">
        <PathwayStepNav
          pathwayTitle={pathwayTitle}
          pathwayHref={pathwayHref}
          steps={allSteps}
          sections={sections}
          currentStepSlug={stepSlug}
          spaceSlug={slug}
          pathwaySlug={pathwaySlug}
          completedCount={completedCount}
          totalCount={totalCount}
        />
      </div>

      {/* ── Right: step content ── */}
      <div className="min-w-0 flex-1">

        {/* Progress strip — shown on mobile only; desktop sidebar handles it */}
        <div className="mb-6 lg:hidden">
          <div className="mb-2 flex items-baseline justify-between text-xs text-black">
            <span>{completedCount} of {totalCount} complete</span>
            <span>Step {step.position} of {totalCount}</span>
          </div>
          <div
            className="h-1.5 w-full overflow-hidden rounded-full"
            style={{ background: 'var(--fc-accent-soft, rgba(56,160,158,0.10))' }}
          >
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0}%`,
                background: 'var(--fc-accent, #2dd4bf)',
              }}
            />
          </div>
        </div>

        {/* Section banner — shown on every step in the section so each lesson
            within a week has a consistent visual identity. Per-step banners
            are intentionally not rendered (data preserved in DB for later). */}
        {step.section_banner_image_url && (
          <div className="mb-6">
            <div className="overflow-hidden rounded-2xl bg-slate-100">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={resolveMediaUrl(step.section_banner_image_url) ?? step.section_banner_image_url}
                alt=""
                className="block aspect-[16/9] w-full object-cover sm:aspect-[21/9]"
              />
            </div>
            {step.section_title && (
              <p
                className="mt-3 text-[12px] font-semibold uppercase tracking-[0.16em]"
                style={{ color: 'var(--fc-accent, #0f766e)' }}
              >
                {step.section_title}
              </p>
            )}
          </div>
        )}

        {/* Step header */}
        <div className="mb-10">
          <div className="mb-2 flex items-center gap-2 text-xs text-black">
            <span className="font-medium uppercase tracking-wider">
              {CONTENT_TYPE_LABEL[step.content_type] ?? step.content_type}
            </span>
            {step.estimated_minutes && (
              <>
                <span className="text-slate-200">·</span>
                <span>{step.estimated_minutes} min</span>
              </>
            )}
          </div>
          <div
            className="mb-3 h-[2px] w-8 rounded-full"
            style={{ background: 'var(--fc-accent, #2dd4bf)' }}
          />
          <h1 className="font-serif text-3xl leading-snug text-navy-900 md:text-4xl">
            {step.title}
          </h1>
        </div>

        {/* Content — blocks take precedence over legacy content_body */}
        {blocks.length > 0 ? (
          <article
            className="overflow-hidden rounded-2xl border px-7 py-7 md:px-8 md:py-8"
            style={{ borderColor: 'rgba(56,160,158,0.15)', background: '#FFFFFF' }}
          >
            {renderBlocks(blocks, collectivePalette)}
          </article>
        ) : step.content_body ? (
          <article
            className="overflow-hidden rounded-2xl border px-7 py-7 md:px-8 md:py-8"
            style={{ borderColor: 'rgba(56,160,158,0.15)', background: '#FFFFFF' }}
          >
            {renderContent(step.content_body)}
          </article>
        ) : null}

        {/* Notes + complete */}
        <StepActions
          spaceSlug={slug}
          pathwaySlug={pathwaySlug}
          stepSlug={stepSlug}
          isCompleted={step.is_completed}
          initialNotes={step.reflection_text}
          reflectionEnabled={step.reflection_enabled ?? true}
        />

        {/* Resources */}
        {resources.length > 0 && (
          <section className="mt-10 border-t border-border pt-8">
            <p className="mb-5 text-[10px] font-semibold uppercase tracking-[0.12em] text-black">
              Resources for this step
            </p>
            <StepResourceList resources={resources} />
          </section>
        )}

        {/* Questions & discussion */}
        {(step.discussion_enabled ?? true) && (
          <StepDiscussion
            spaceSlug={slug}
            pathwaySlug={pathwaySlug}
            stepSlug={stepSlug}
            initialComments={comments}
          />
        )}

        {/* Prev / Next */}
        <div className="mt-10 flex items-center justify-between border-t border-border pt-6">
          {prevStep ? (
            <Link
              href={`/spaces/${slug}/pathways/${pathwaySlug}/${prevStep.slug}`}
              className="group flex items-center gap-2 text-sm text-black transition-colors hover:text-navy-700"
            >
              <span>←</span>
              <span className="hidden sm:inline underline-offset-2 group-hover:underline">
                {prevStep.title}
              </span>
              <span className="sm:hidden">Previous</span>
            </Link>
          ) : (
            <Link href={pathwayHref} className="text-sm text-black transition-colors hover:text-navy-700">
              ← {pathwayTitle}
            </Link>
          )}

          {nextStep ? (
            <Link
              href={`/spaces/${slug}/pathways/${pathwaySlug}/${nextStep.slug}`}
              className="group flex items-center gap-2 text-sm font-medium transition-opacity hover:opacity-80"
              style={{ color: 'var(--fc-accent, #0d9488)' }}
            >
              <span className="hidden sm:inline underline-offset-2 group-hover:underline">
                {nextStep.title}
              </span>
              <span className="sm:hidden">Next</span>
              <span>→</span>
            </Link>
          ) : (
            <Link
              href={pathwayHref}
              className="text-sm font-medium hover:underline underline-offset-2"
              style={{ color: 'var(--fc-accent, #0d9488)' }}
            >
              Back to {pathwayTitle} →
            </Link>
          )}
        </div>

      </div>
    </div>
    </div>
  )
}
