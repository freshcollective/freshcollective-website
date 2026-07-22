import React from 'react'
import { notFound } from 'next/navigation'
import Link from 'next/link'
import { getStep, getPathwayOverview, getStepResources, getStepBlocks, getStepComments, getSpace } from '@/lib/serverApi'
import type { CollectivePaletteMeta } from '@/lib/collectivePalette'
import PathwayAutoRevalidate from '@/components/spaces/PathwayAutoRevalidate'
import { getPathwayCoverStyle } from '@/lib/coverArt'
import { resolveMediaUrl } from '@/lib/api'
import {
  resolveCalloutPalette,
  resolveCalloutPurposeIcon,
  resolveCalloutPurposeLabel,
  resolveContainerPalette,
} from '@/lib/calloutPalette'
import { exerciseContentToRichText } from '@/lib/exerciseSteps'
import { decodeColumns, gridTemplateForVariant } from '@/lib/columnsBlock'
import StepActions from '@/components/spaces/StepActions'
import StepDiscussion from '@/components/spaces/StepDiscussion'
import RichTextRenderer from '@/components/RichTextRenderer'
import EmbedRenderer from '@/components/EmbedRenderer'
import ButtonBlock from '@/components/ButtonBlock'
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
          <h3 key={i} className="mt-8 mb-3 font-semibold text-[1.1rem] text-navy-900">
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
        <p key={i} className="my-4 text-[15px] leading-[1.85] text-black">
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
  if (url.startsWith('http')) return url
  return url.startsWith('/') ? `${API_BASE}${url}` : `${API_BASE}/api/uploads/${url}`
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

/**
 * Wrap a rendered block in a soft-coloured container when block.container_style
 * is set. Divider/heading/callout are excluded (callout is its own container;
 * divider/heading don't take wrappers). Otherwise returns the node unchanged.
 */
function withContainerBase(
  node: React.ReactNode,
  block: StepBlock,
  key: string,
  collectivePalette: CollectivePaletteMeta | null = null,
): React.ReactNode {
  if (node == null) return null
  const palette = resolveContainerPalette(block.container_style, collectivePalette)
  if (!palette) {
    // Callers invoke this from inside a ``blocks.map()``, so React
    // needs a stable ``key`` on whatever element we return — even
    // when no soft-tint wrapper is applied. Cloning here attaches
    // ``key`` at the single site every non-wrapped block flows
    // through, instead of asking every caller to pre-key its JSX.
    return React.isValidElement(node) ? React.cloneElement(node, { key }) : node
  }
  return (
    <div
      key={key}
      className="my-6 rounded-xl border px-5 py-5"
      style={{ background: palette.bg, borderColor: palette.border }}
    >
      {node}
    </div>
  )
}

function renderBlocks(blocks: StepBlock[], collectivePalette: CollectivePaletteMeta | null): React.ReactNode {
  // Closure-scoped helpers so every callsite below reads from the
  // active collective palette without having to thread it through
  // every call. Palette-linked block colours (``palette:primary`` …)
  // resolve here; ``custom:#hex`` and legacy chip keys are handled by
  // the resolver itself.
  const withContainer = (node: React.ReactNode, block: StepBlock, key: string): React.ReactNode =>
    withContainerBase(node, block, key, collectivePalette)
  const resolveContainer = (v: string | null | undefined) =>
    resolveContainerPalette(v, collectivePalette)
  const resolveCallout = (caption: string | null | undefined, label: string | null | undefined) =>
    resolveCalloutPalette(caption, label, undefined, collectivePalette)

  return blocks.map((block) => {
    const { id, block_type: t } = block

    if (t === 'divider') return <hr key={id} className="my-8 border-border" />

    if (t === 'columns') {
      const payload = decodeColumns(block.content)
      return withContainer(
        <div
          className="fc-columns-grid grid gap-6"
          style={{ ['--fc-cols' as string]: gridTemplateForVariant(payload.layout.variant) }}
        >
          {payload.cells.map((cell, i) => (
            <div key={i} className="min-w-0">
              {cell.content?.trim() ? <RichTextRenderer content={cell.content} /> : null}
            </div>
          ))}
        </div>,
        block, id,
      )
    }

    if (t === 'heading') {
      const level = block.label === 'h1' ? 'h1' : block.label === 'h3' ? 'h3' : 'h2'
      const cls = level === 'h1'
        ? 'mt-8 mb-3 font-semibold text-[1.5rem] leading-tight text-navy-900'
        : level === 'h3'
        ? 'mt-7 mb-2 font-semibold text-[1.05rem] text-navy-900'
        : 'mt-8 mb-3 font-semibold text-[1.2rem] text-navy-900'
      return React.createElement(level, { key: id, className: cls }, block.content)
    }

    if (t === 'text' && block.content) return withContainer(
      <div>
        <RichTextRenderer content={block.content} />
      </div>,
      block, id,
    )

    if (t === 'image') {
      const src = block.media_asset ? resolveUrl(block.media_asset.file_url) : block.embed_url
      if (!src) return null
      // Alt-text resolution — three-state semantics preserved:
      //   * ``label = null``  → legacy row; fall back to asset.title,
      //                          then '' if there's no asset title.
      //   * ``label = ''``    → decorative image; ``alt=""`` wins and
      //                          we do NOT fall back to the asset title.
      //   * ``label = '...'`` → writer's explicit alt text.
      // ``??`` is intentional — using ``||`` here would silently
      // replace an intentionally decorative image with the asset
      // title, breaking screen-reader intent.
      const alt = block.label ?? block.media_asset?.title ?? ''
      return withContainer(
        <figure className="my-6">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={src} alt={alt} className="w-full rounded-xl" />
          {block.caption && <figcaption className="mt-2 text-center text-[12px] text-black">{block.caption}</figcaption>}
        </figure>,
        block, id,
      )
    }

    if (t === 'video_embed' && block.embed_url) {
      const embedSrc = getVideoEmbed(block.embed_url)
      return withContainer(
        <figure className="my-6">
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
              <span className="text-black">▶</span>
              <span className="text-[14px] font-medium text-navy-900 group-hover:underline">
                {block.caption || block.embed_url}
              </span>
              <span className="ml-auto text-[12px] text-black">↗</span>
            </a>
          )}
          {embedSrc && block.caption && (
            <figcaption className="mt-2 text-center text-[12px] text-black">{block.caption}</figcaption>
          )}
        </figure>,
        block, id,
      )
    }

    if (t === 'audio') {
      const asset = block.media_asset
      if (!asset) return null
      // When wrapped in a soft container, drop the audio block's own
      // white-rounded border so we don't get a box-in-box look.
      const wrapped = !!resolveContainer(block.container_style)
      return withContainer(
        <figure className={wrapped ? '' : 'my-6 rounded-xl border border-border bg-white p-4'}>
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-black">Audio</p>
          <audio controls className="w-full" src={resolveUrl(asset.file_url)} />
          {block.caption && <figcaption className="mt-2 text-[12px] text-black">{block.caption}</figcaption>}
        </figure>,
        block, id,
      )
    }

    if (t === 'file_download' && block.media_asset) return withContainer(
      <div className="my-4">
        <a
          href={resolveUrl(block.media_asset.file_url)}
          download
          className="group inline-flex items-center gap-2 rounded-xl border border-border bg-white px-4 py-3 text-[14px] font-medium text-navy-900 transition-colors hover:border-teal-300 hover:text-teal-700"
        >
          <span>↓</span>
          {block.label || block.media_asset.title}
          <span className="ml-1 text-[11px] font-normal text-black">{block.media_asset.original_filename}</span>
        </a>
      </div>,
      block, id,
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
            {block.caption && <p className="mt-0.5 text-[12px] text-black">{block.caption}</p>}
          </div>
          <span className="shrink-0 text-[12px] text-black">↗</span>
        </a>
      </div>
    )

    if (t === 'reflection_prompt' && block.content) {
      // Journal-quote treatment: prompt rendered as a serif italic
      // question with the supporting context (caption) below in a
      // smaller plain paragraph. When wrapped in a soft container,
      // the container provides the visual treatment instead.
      const wrapped = !!resolveContainer(block.container_style)
      // Prompt content is plain text from the purpose-built PromptEditor;
      // legacy prompts may still be TipTap JSON, in which case
      // RichTextRenderer handles the rendering.
      const isJson = (() => { try { return JSON.parse(block.content!).type === 'doc' } catch { return false } })()
      return (
        <div
          key={id}
          className={wrapped ? 'my-6' : 'my-6 rounded-xl border-l-4 px-6 py-5'}
          style={wrapped ? undefined : {
            borderColor: 'var(--fc-accent-line, #5eead4)',
            background: 'var(--fc-accent-soft, #f0fdfa)',
          }}
        >
          <p
            className="mb-2 flex items-center gap-2 text-[10.5px] font-semibold uppercase tracking-[0.16em]"
            style={{ color: 'var(--fc-accent, #0d9488)' }}
          >
            <span aria-hidden="true" className="text-[15px] leading-none">❝</span>
            Reflection prompt
          </p>
          {isJson ? (
            <div className="font-serif italic text-[18px] leading-snug text-navy-900">
              <RichTextRenderer content={block.content} />
            </div>
          ) : (
            <p className="font-serif italic text-[18px] leading-snug text-navy-900">
              {block.content}
            </p>
          )}
          {block.caption && (
            <p className="mt-2 text-[14px] leading-relaxed text-black">
              {block.caption}
            </p>
          )}
        </div>
      )
    }

    if (t === 'exercise' && block.content) {
      // Exercise is now a specialised Content block: soft card + label
      // + optional title + rich body. Legacy step-envelope rows are
      // migrated to TipTap JSON on the fly by exerciseContentToRichText
      // so old and new rows render through the same path.
      const body = exerciseContentToRichText(block.content)
      const wrapped = !!resolveContainer(block.container_style)
      return (
        <div
          key={id}
          className={wrapped ? 'my-6' : 'my-6 rounded-xl border border-slate-200 bg-white px-6 py-5'}
        >
          <p className="mb-1 flex items-center gap-2 text-[10.5px] font-semibold uppercase tracking-[0.16em] text-slate-700">
            <span aria-hidden="true" className="text-[13px]">✏</span>
            Exercise
          </p>
          {block.label && (
            <p className="mt-1 mb-3 font-serif text-[20px] leading-tight text-navy-900">
              {block.label}
            </p>
          )}
          {body && <RichTextRenderer content={body} />}
        </div>
      )
    }

    if (t === 'callout' && block.content) {
      // Creator-chosen colour + purpose. If the writer set a purpose
      // (Highlight / Tip / Placeholder / …), we surface it as an
      // icon + label tag above the content so members can read the
      // intent, not just the tint. Callouts with no purpose set stay
      // as a soft tinted box.
      const palette = resolveCallout(block.caption, block.label)
      const icon = resolveCalloutPurposeIcon(block.label)
      const purposeLabel = resolveCalloutPurposeLabel(block.label)
      return (
        <div
          key={id}
          className="my-5 rounded-xl border px-5 py-4"
          style={{ background: palette.bg, borderColor: palette.border }}
        >
          {purposeLabel && (
            <p
              className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-widest"
              style={{ color: palette.border }}
            >
              {icon && <span aria-hidden="true" className="text-[13px] leading-none">{icon}</span>}
              <span>{purposeLabel}</span>
            </p>
          )}
          <RichTextRenderer content={block.content} />
        </div>
      )
    }

    if (t === 'embed' && block.embed_url) {
      return withContainer(
        <figure className="my-6">
          {block.label && (
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-black">
              {block.label}
            </p>
          )}
          <EmbedRenderer url={block.embed_url} title={block.label ?? undefined} />
          {block.caption && (
            <figcaption className="mt-2 text-center text-[12px] text-black">
              {block.caption}
            </figcaption>
          )}
        </figure>,
        block, id,
      )
    }

    if (t === 'button' && block.embed_url && block.label) {
      const newTab = block.content === 'new_tab' || block.content === 'same_tab' ? block.content : null
      return withContainer(
        <div className="my-5">
          <ButtonBlock
            href={block.embed_url}
            text={block.label}
            caption={block.caption ?? null}
            collectivePalette={collectivePalette}
            newTabPref={newTab}
          />
        </div>,
        block, id,
      )
    }

    if (t === 'resource') {
      // Hide entirely from members if the linked Resource was deleted or is
      // still in draft. Mirrors the Resources page rule (only `published`
      // resources surface to members) — see backend spaces/routes.py.
      const r = block.resource
      if (!r || r.status !== 'published') return null
      const title = block.label || r.title
      const description = block.caption || r.description
      const href = r.url ? (r.url.startsWith('http') ? r.url : `${API_BASE}${r.url.startsWith('/') ? r.url : `/api/uploads/${r.url}`}`) : null
      if (!href) return null
      const isFile = !!r.file_name || ['file', 'guide', 'template', 'replay', 'audio', 'video'].includes(r.resource_type)
      const ctaLabel = isFile ? 'Download resource' : 'Open resource'
      return withContainer(
        <a
          key={id}
          href={href}
          target={isFile ? undefined : '_blank'}
          rel={isFile ? undefined : 'noopener noreferrer'}
          download={isFile && r.file_name ? r.file_name : undefined}
          className="group my-5 flex items-start gap-4 rounded-xl border border-border bg-white px-5 py-4 transition-colors hover:border-teal-300"
        >
          <span
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-[16px]"
            style={{ background: 'rgba(56,160,158,0.08)', color: '#38A09E' }}
          >
            ◰
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <p className="truncate text-[15px] font-semibold text-navy-900 group-hover:text-teal-700">{title}</p>
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-500">
                {r.resource_type}
              </span>
            </div>
            {description && (
              <p className="mt-1 text-[13px] leading-relaxed text-black">{description}</p>
            )}
          </div>
          <span className="shrink-0 self-center rounded-full border border-border bg-white px-3 py-1.5 text-[12px] font-medium text-black group-hover:border-teal-300 group-hover:text-teal-700">
            {ctaLabel} {isFile ? '↓' : '↗'}
          </span>
        </a>,
        block, id,
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
              style={{ color: coverImageUrl ? '#FFFFFF' : cs.labelColor }}
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
            className="mb-8 overflow-hidden rounded-2xl border px-7 py-6"
            style={{ borderColor: 'rgba(56,160,158,0.15)', background: '#FFFFFF' }}
          >
            {renderBlocks(blocks, collectivePalette)}
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
