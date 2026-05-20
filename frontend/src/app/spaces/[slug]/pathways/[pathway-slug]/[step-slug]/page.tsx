import React from 'react'
import { notFound } from 'next/navigation'
import Link from 'next/link'
import { getStep, getPathwayOverview, getStepResources, getStepBlocks } from '@/lib/serverApi'
import { getPathwayCoverStyle } from '@/lib/coverArt'
import { resolveMediaUrl } from '@/lib/api'
import StepActions from '@/components/spaces/StepActions'
import RichTextRenderer from '@/components/RichTextRenderer'
import PathwayStepNav from '@/components/spaces/PathwayStepNav'
import type { PathwayWithSteps, StepDetail, StepSummary, StepResource, StepBlock } from '@/types/platform'

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
          <h3 key={i} className="mt-8 mb-3 font-serif text-xl text-navy-900">
            {trimmed.slice(2, -2)}
          </h3>
        )
      }

      if (trimmed === '---') {
        return <hr key={i} className="my-8 border-border" />
      }

      if (trimmed.split('\n').every((l) => l.trimStart().startsWith('- '))) {
        const items = trimmed.split('\n').map((l) => l.replace(/^- /, '').trim())
        return (
          <ul key={i} className="my-4 space-y-2 pl-5">
            {items.map((item, j) => (
              <li
                key={j}
                className="relative text-[15px] leading-[1.8] text-slate-600 before:absolute before:-left-5 before:text-slate-300 before:content-['–']"
              >
                {item}
              </li>
            ))}
          </ul>
        )
      }

      const parts = trimmed.split(/(\*\*[^*]+\*\*)/)
      return (
        <p key={i} className="my-4 text-[15px] leading-[1.85] text-slate-600">
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

function resolveUrl(url: string): string {
  return url.startsWith('http') ? url : `${API_BASE}/api/uploads/${url}`
}

function getVideoEmbed(url: string): string | null {
  try {
    const u = new URL(url)
    if (u.hostname.includes('youtube.com')) {
      const id = u.searchParams.get('v')
      return id ? `https://www.youtube.com/embed/${id}` : null
    }
    if (u.hostname.includes('youtu.be')) {
      const id = u.pathname.slice(1)
      return id ? `https://www.youtube.com/embed/${id}` : null
    }
    if (u.hostname.includes('vimeo.com')) {
      const id = u.pathname.split('/').filter(Boolean).pop()
      return id ? `https://player.vimeo.com/video/${id}` : null
    }
    if (u.hostname.includes('loom.com') && u.pathname.includes('/share/')) {
      const id = u.pathname.split('/share/')[1]?.split('?')[0]
      return id ? `https://www.loom.com/embed/${id}` : null
    }
  } catch {}
  return null
}

function renderBlocks(blocks: StepBlock[]): React.ReactNode {
  return blocks.map((block) => {
    const { id, block_type: t } = block

    if (t === 'divider') return <hr key={id} className="my-8 border-border" />

    if (t === 'heading') {
      const level = block.label === 'h1' ? 'h2' : block.label === 'h3' ? 'h3' : 'h2'
      const cls = level === 'h3'
        ? 'mt-7 mb-2 font-serif text-xl text-navy-900'
        : 'mt-8 mb-3 font-serif text-2xl text-navy-900'
      return React.createElement(level, { key: id, className: cls }, block.content)
    }

    if (t === 'text' && block.content) return (
      <div key={id}>
        <RichTextRenderer content={block.content} />
      </div>
    )

    if (t === 'image') {
      const src = block.media_asset ? resolveUrl(block.media_asset.file_url) : block.embed_url
      if (!src) return null
      return (
        <figure key={id} className="my-6">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={src} alt={block.caption ?? ''} className="w-full rounded-xl" />
          {block.caption && <figcaption className="mt-2 text-center text-[12px] text-slate-400">{block.caption}</figcaption>}
        </figure>
      )
    }

    if (t === 'video_embed' && block.embed_url) {
      const embedSrc = getVideoEmbed(block.embed_url)
      return (
        <figure key={id} className="my-6">
          {embedSrc ? (
            <div className="aspect-video overflow-hidden rounded-xl bg-slate-100">
              <iframe
                src={embedSrc}
                className="h-full w-full"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowFullScreen
              />
            </div>
          ) : (
            <a
              href={block.embed_url}
              target="_blank"
              rel="noopener noreferrer"
              className="group flex items-center gap-3 rounded-xl border border-border bg-white px-4 py-3 hover:border-teal-300"
            >
              <span className="text-slate-400">▶</span>
              <span className="text-[14px] font-medium text-navy-900 group-hover:underline">
                {block.caption || block.embed_url}
              </span>
              <span className="ml-auto text-[12px] text-slate-400">↗</span>
            </a>
          )}
          {embedSrc && block.caption && (
            <figcaption className="mt-2 text-center text-[12px] text-slate-400">{block.caption}</figcaption>
          )}
        </figure>
      )
    }

    if (t === 'audio') {
      const asset = block.media_asset
      if (!asset) return null
      return (
        <figure key={id} className="my-6 rounded-xl border border-border bg-white p-4">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-slate-400">Audio</p>
          <audio controls className="w-full" src={resolveUrl(asset.file_url)} />
          {block.caption && <figcaption className="mt-2 text-[12px] text-slate-400">{block.caption}</figcaption>}
        </figure>
      )
    }

    if (t === 'file_download' && block.media_asset) return (
      <div key={id} className="my-4">
        <a
          href={resolveUrl(block.media_asset.file_url)}
          download
          className="group inline-flex items-center gap-2 rounded-xl border border-border bg-white px-4 py-3 text-[14px] font-medium text-navy-900 transition-colors hover:border-teal-300 hover:text-teal-700"
        >
          <span>↓</span>
          {block.label || block.media_asset.title}
          <span className="ml-1 text-[11px] font-normal text-slate-400">{block.media_asset.original_filename}</span>
        </a>
      </div>
    )

    if (t === 'link' && block.embed_url) return (
      <div key={id} className="my-4">
        <a
          href={block.embed_url}
          target="_blank"
          rel="noopener noreferrer"
          className="group flex items-start justify-between gap-4 rounded-xl border border-border bg-white px-4 py-3 transition-colors hover:border-teal-300"
        >
          <div>
            <p className="text-[14px] font-medium text-navy-900 group-hover:underline underline-offset-2">
              {block.label || block.embed_url}
            </p>
            {block.caption && <p className="mt-0.5 text-[12px] text-slate-500">{block.caption}</p>}
          </div>
          <span className="shrink-0 text-[12px] text-slate-400">↗</span>
        </a>
      </div>
    )

    if (t === 'reflection_prompt' && block.content) return (
      <div
        key={id}
        className="my-6 rounded-xl border-l-4 border-teal-300 bg-teal-50 px-5 py-4"
      >
        <p className="mb-2 text-[10px] font-bold uppercase tracking-widest text-teal-600">Reflection</p>
        <RichTextRenderer content={block.content} />
      </div>
    )

    if (t === 'exercise' && block.content) return (
      <div
        key={id}
        className="my-6 rounded-xl border border-slate-200 bg-white px-5 py-4"
      >
        <p className="mb-2 text-[10px] font-bold uppercase tracking-widest text-slate-400">Exercise</p>
        <RichTextRenderer content={block.content} />
      </div>
    )

    if (t === 'callout' && block.content) {
      const style = block.label ?? 'info'
      const bg = style === 'warning' ? 'rgba(234,179,8,0.10)' : style === 'tip' ? 'rgba(56,160,158,0.08)' : 'rgba(59,130,246,0.08)'
      const accent = style === 'warning' ? '#92400e' : style === 'tip' ? '#0f766e' : '#1d4ed8'
      return (
        <div key={id} className="my-5 rounded-xl px-5 py-4" style={{ background: bg }}>
          <p className="text-[10px] font-bold uppercase tracking-widest mb-1.5" style={{ color: accent }}>
            {style.charAt(0).toUpperCase() + style.slice(1)}
          </p>
          <RichTextRenderer content={block.content} />
        </div>
      )
    }

    return null
  })
}

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
            <p className="mb-2.5 text-xs font-semibold uppercase tracking-widest text-slate-400">
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
                      <p className="mt-0.5 text-xs leading-relaxed text-slate-500">
                        {resource.description}
                      </p>
                    )}
                  </div>
                  <span className="shrink-0 rounded-full border border-border bg-white px-2.5 py-1 text-xs font-medium text-slate-600 group-hover:border-navy-300 group-hover:text-navy-700">
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

  const [step, overview, resources, blocks]: [
    StepDetail | null,
    PathwayWithSteps | null,
    StepResource[],
    StepBlock[],
  ] = await Promise.all([
    getStep(slug, pathwaySlug, stepSlug),
    getPathwayOverview(slug, pathwaySlug),
    getStepResources(slug, pathwaySlug, stepSlug),
    getStepBlocks(slug, pathwaySlug, stepSlug),
  ])

  if (!step) notFound()

  const allSteps: StepSummary[] = overview?.steps ?? []
  const currentIndex = allSteps.findIndex((s) => s.slug === stepSlug)
  const prevStep = currentIndex > 0 ? allSteps[currentIndex - 1] : null
  const nextStep = currentIndex < allSteps.length - 1 ? allSteps[currentIndex + 1] : null

  const pathwayHref = `/spaces/${slug}/pathways`
  const pathwayTitle = overview?.title ?? 'Pathway'
  const cs = getPathwayCoverStyle(pathwaySlug)
  const coverImageUrl = overview?.cover_image_url ? resolveMediaUrl(overview.cover_image_url) : null
  const completedCount = allSteps.filter((s) => s.is_completed).length
  const totalCount = allSteps.length
  const sections = overview?.sections ?? []

  return (
    <div>

      {/* ── Compact pathway header card ── */}
      {overview && (
        <div
          className="relative mb-6 overflow-hidden rounded-2xl"
          style={{
            background: cs.background,
            backgroundSize: cs.backgroundSize ?? 'auto',
            minHeight: '96px',
          }}
        >
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
                  background: 'linear-gradient(135deg, rgba(7,24,36,0.80) 0%, rgba(7,56,58,0.62) 100%)',
                }}
              />
            </>
          )}
          <div className="relative px-6 py-5 md:px-8">
            <p
              className="mb-0.5 text-[9px] font-bold uppercase tracking-[0.20em]"
              style={{ color: coverImageUrl ? 'rgba(255,255,255,0.60)' : cs.labelColor }}
            >
              Pathway
            </p>
            <h2
              className="font-serif text-xl leading-snug md:text-2xl"
              style={{ color: coverImageUrl ? '#FFFFFF' : cs.titleColor }}
            >
              {overview.title}
            </h2>
          </div>
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
          <div className="mb-2 flex items-baseline justify-between text-xs text-slate-400">
            <span>{completedCount} of {totalCount} complete</span>
            <span>Step {step.position} of {totalCount}</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-teal-100">
            <div
              className="h-full rounded-full bg-teal-400 transition-all duration-500"
              style={{ width: `${totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0}%` }}
            />
          </div>
        </div>

        {/* Step header */}
        <div className="mb-10">
          <div className="mb-2 flex items-center gap-2 text-xs text-slate-400">
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
          <div className="mb-3 h-[2px] w-8 rounded-full bg-teal-400" />
          <h1 className="font-serif text-3xl leading-snug text-navy-900 md:text-4xl">
            {step.title}
          </h1>
        </div>

        {/* Content — blocks take precedence over legacy content_body */}
        {blocks.length > 0 ? (
          <article
            className="mb-8 overflow-hidden rounded-2xl border px-7 py-6"
            style={{ borderColor: 'rgba(56,160,158,0.15)', background: '#FFFFFF' }}
          >
            {renderBlocks(blocks)}
          </article>
        ) : step.content_body ? (
          <article
            className="mb-8 overflow-hidden rounded-2xl border px-7 py-6"
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
        />

        {/* Resources */}
        {resources.length > 0 && (
          <section className="mt-10 border-t border-border pt-8">
            <p className="mb-5 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">
              Resources for this step
            </p>
            <StepResourceList resources={resources} />
          </section>
        )}

        {/* Prev / Next */}
        <div className="mt-10 flex items-center justify-between border-t border-border pt-6">
          {prevStep ? (
            <Link
              href={`/spaces/${slug}/pathways/${pathwaySlug}/${prevStep.slug}`}
              className="group flex items-center gap-2 text-sm text-slate-400 transition-colors hover:text-navy-700"
            >
              <span>←</span>
              <span className="hidden sm:inline underline-offset-2 group-hover:underline">
                {prevStep.title}
              </span>
              <span className="sm:hidden">Previous</span>
            </Link>
          ) : (
            <Link href={pathwayHref} className="text-sm text-slate-400 transition-colors hover:text-navy-700">
              ← {pathwayTitle}
            </Link>
          )}

          {nextStep ? (
            <Link
              href={`/spaces/${slug}/pathways/${pathwaySlug}/${nextStep.slug}`}
              className="group flex items-center gap-2 text-sm font-medium text-teal-600 transition-colors hover:text-teal-700"
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
              className="text-sm font-medium text-teal-600 hover:underline underline-offset-2"
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
