import React from 'react'
import { notFound } from 'next/navigation'
import Link from 'next/link'
import { getPathwayOverview, getPathwayAboutBlocks, getSpace } from '@/lib/serverApi'
import type { CollectivePaletteMeta } from '@/lib/collectivePalette'
import { getPathwayCoverStyle } from '@/lib/coverArt'
import { resolveMediaUrl, apiUrl } from '@/lib/api'
import {
  resolveCalloutPalette,
  resolveCalloutPurposeIcon,
  resolveCalloutPurposeLabel,
  resolveContainerPalette,
} from '@/lib/calloutPalette'
import { isPathwayLocked, formatPathwayPrice, unlockCtaLabel } from '@/lib/pathwayAccess'
import RichTextRenderer from '@/components/RichTextRenderer'
import EmbedRenderer from '@/components/EmbedRenderer'
import ButtonBlock from '@/components/ButtonBlock'
import { decodeColumns, gridTemplateForVariant } from '@/lib/columnsBlock'
import { exerciseContentToRichText } from '@/lib/exerciseSteps'
import type { PathwayWithSteps, PathwayAboutBlock, StepBlockMedia, PaymentOptionSummary } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string; 'pathway-slug': string }>
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

function resolveAssetUrl(url: string): string {
  if (url.startsWith('http')) return url
  return url.startsWith('/') ? `${API_BASE}${url}` : `${API_BASE}/api/uploads/${url}`
}

function getEmbedUrl(raw: string): string | null {
  if (!raw) return null
  try {
    const url = new URL(raw)
    if (url.hostname.includes('youtube.com')) {
      const id = url.searchParams.get('v')
      return id ? `https://www.youtube.com/embed/${id}` : null
    }
    if (url.hostname.includes('youtu.be')) {
      const id = url.pathname.slice(1)
      return id ? `https://www.youtube.com/embed/${id}` : null
    }
    if (url.hostname.includes('vimeo.com')) {
      const id = url.pathname.split('/').filter(Boolean).pop()
      return id ? `https://player.vimeo.com/video/${id}` : null
    }
    if (url.hostname.includes('loom.com') && url.pathname.includes('/share/')) {
      const id = url.pathname.split('/share/')[1]?.split('?')[0]
      return id ? `https://www.loom.com/embed/${id}` : null
    }
  } catch {}
  return null
}

// Callouts use the shared `resolveCalloutPalette` resolver — no per-page
// palette constant is needed. The collective's active palette is threaded
// in from the page so palette-linked block colours resolve to the
// collective's actual hex at render time.

function BlockRenderer({
  block, collectivePalette,
}: {
  block: PathwayAboutBlock
  collectivePalette: CollectivePaletteMeta | null
}) {
  const inner = renderAboutBlockInner(block, collectivePalette)
  if (inner == null) return null
  const palette = resolveContainerPalette(block.container_style, collectivePalette)
  if (!palette) return inner
  return (
    <div
      className="rounded-xl border px-5 py-5"
      style={{ background: palette.bg, borderColor: palette.border }}
    >
      {inner}
    </div>
  )
}

function renderAboutBlockInner(
  block: PathwayAboutBlock,
  collectivePalette: CollectivePaletteMeta | null,
): React.ReactElement | null {
  const t = block.block_type
  const asset = block.media_asset as StepBlockMedia | null
  // True when this block will be wrapped in a soft container; lets inner
  // styling shed its own border/background to avoid box-in-box.
  const wrapped = !!resolveContainerPalette(block.container_style, collectivePalette)

  if (t === 'divider') return <hr className="border-slate-200" />

  if (t === 'columns') {
    const payload = decodeColumns(block.content)
    return (
      <div
        className="fc-columns-grid grid gap-6"
        style={{ ['--fc-cols' as string]: gridTemplateForVariant(payload.layout.variant) }}
      >
        {payload.cells.map((cell, i) => (
          <div key={i} className="min-w-0 prose prose-sm max-w-none text-black">
            {cell.content?.trim() ? <RichTextRenderer content={cell.content} /> : null}
          </div>
        ))}
      </div>
    )
  }

  if (t === 'heading') {
    const level = block.label ?? 'h2'
    const classes = level === 'h1'
      ? 'font-serif text-3xl text-navy-900'
      : level === 'h3'
      ? 'font-serif text-xl font-semibold text-navy-900'
      : 'font-serif text-2xl text-navy-900'
    return <p className={classes}>{block.content}</p>
  }

  if (t === 'text') return (
    <div className="prose prose-sm max-w-none text-black">
      <RichTextRenderer content={block.content} />
    </div>
  )

  if (t === 'image') {
    const src = asset ? resolveAssetUrl(asset.file_url) : block.embed_url
    if (!src) return null
    // Alt-text resolution — three-state semantics preserved:
    //   * ``label = null``  → legacy row; fall back to asset.title,
    //                          then '' if there's no asset title.
    //   * ``label = ''``    → decorative image; ``alt=""`` wins and
    //                          we do NOT fall back to the asset title.
    //   * ``label = '...'`` → writer's explicit alt text.
    // ``??`` is intentional — using ``||`` here would silently replace
    // an intentionally decorative image with the asset title.
    const alt = block.label ?? asset?.title ?? ''
    return (
      <figure>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={src} alt={alt} className="w-full rounded-xl object-cover" />
        {block.caption && (
          <figcaption className="mt-2 text-center text-[12px] text-black">{block.caption}</figcaption>
        )}
      </figure>
    )
  }

  if (t === 'video_embed') {
    const embed = block.embed_url ? getEmbedUrl(block.embed_url) : null
    if (embed) {
      return (
        <figure>
          <div className="overflow-hidden rounded-xl bg-black" style={{ aspectRatio: '16/9' }}>
            <iframe
              src={embed}
              className="h-full w-full"
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
              allowFullScreen
            />
          </div>
          {block.caption && (
            <figcaption className="mt-2 text-center text-[12px] text-black">{block.caption}</figcaption>
          )}
        </figure>
      )
    }
    if (block.embed_url) {
      return (
        <a
          href={block.embed_url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 rounded-xl border border-border bg-white px-4 py-3 text-[14px] font-medium text-teal-700 transition-colors hover:border-teal-200"
        >
          <span>▶</span>
          {block.caption || block.embed_url}
        </a>
      )
    }
    return null
  }

  if (t === 'audio') {
    if (!asset) return null
    return (
      <div className={wrapped ? '' : 'rounded-xl border border-border bg-white p-4'}>
        {block.caption && <p className="mb-2 text-[13px] font-medium text-navy-900">{block.caption}</p>}
        <audio controls className="w-full" src={resolveAssetUrl(asset.file_url)} />
      </div>
    )
  }

  if (t === 'file_download') {
    if (!asset) return null
    return (
      <a
        href={resolveAssetUrl(asset.file_url)}
        download
        className="flex items-center gap-3 rounded-xl border border-border bg-white px-5 py-3.5 transition-colors hover:border-teal-200"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-lg"
          style={{ background: 'rgba(56,160,158,0.08)' }}>
          ↓
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[14px] font-semibold text-navy-900">{block.label || asset.title}</p>
          <p className="text-[12px] text-black">{asset.original_filename}</p>
        </div>
      </a>
    )
  }

  if (t === 'link') {
    if (!block.embed_url) return null
    return (
      <a
        href={block.embed_url}
        target="_blank"
        rel="noopener noreferrer"
        className="flex items-center gap-3 rounded-xl border border-border bg-white px-5 py-3.5 transition-colors hover:border-teal-200"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-lg"
          style={{ background: 'rgba(56,160,158,0.08)' }}>
          🔗
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[14px] font-semibold text-navy-900">{block.label || block.embed_url}</p>
          {block.caption && <p className="text-[12px] text-black">{block.caption}</p>}
        </div>
        <span className="shrink-0 text-black">→</span>
      </a>
    )
  }

  if (t === 'reflection_prompt') return (
    <div
      className={wrapped ? '' : 'rounded-xl border-l-4 py-4 pl-5 pr-4'}
      style={wrapped ? undefined : {
        borderColor: 'var(--fc-accent-line, #5eead4)',
        background: 'var(--fc-accent-soft, rgba(240,253,250,0.60))',
      }}
    >
      <p
        className="mb-1.5 text-[10px] font-bold uppercase tracking-widest"
        style={{ color: 'var(--fc-accent, #0d9488)' }}
      >Reflection</p>
      <div className="text-[15px] italic leading-relaxed text-black">
        <RichTextRenderer content={block.content} />
      </div>
    </div>
  )

  if (t === 'exercise') {
    // Migrate legacy step-envelope rows to TipTap JSON so old exercise
    // blocks render as prose without loss.
    const body = exerciseContentToRichText(block.content)
    return (
      <div className={wrapped ? '' : 'rounded-xl border border-slate-200 bg-white px-5 py-4'}>
        <p className="mb-1 flex items-center gap-2 text-[10.5px] font-semibold uppercase tracking-[0.16em] text-slate-700">
          <span aria-hidden="true" className="text-[13px]">✏</span>
          Exercise
        </p>
        {block.label && (
          <p className="mt-0.5 mb-3 font-serif text-[19px] leading-tight text-navy-900">
            {block.label}
          </p>
        )}
        {body && (
          <div className="text-[14px] leading-relaxed text-black">
            <RichTextRenderer content={body} />
          </div>
        )}
      </div>
    )
  }

  if (t === 'callout') {
    const palette = resolveCalloutPalette(block.caption, block.label, undefined, collectivePalette)
    const icon = resolveCalloutPurposeIcon(block.label)
    const purposeLabel = resolveCalloutPurposeLabel(block.label)
    return (
      <div
        className="rounded-xl border px-5 py-4"
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
        <div className="text-[14px] leading-relaxed text-black">
          <RichTextRenderer content={block.content} />
        </div>
      </div>
    )
  }

  if (t === 'embed' && block.embed_url) {
    return (
      <figure>
        {block.label && (
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-black">
            {block.label}
          </p>
        )}
        <EmbedRenderer url={block.embed_url} title={block.label ?? undefined} />
        {block.caption && (
          <figcaption className="mt-2 text-center text-[12px] text-slate-400">
            {block.caption}
          </figcaption>
        )}
      </figure>
    )
  }

  if (t === 'button' && block.embed_url && block.label) {
    const newTab = block.content === 'new_tab' || block.content === 'same_tab' ? block.content : null
    return (
      <ButtonBlock
        href={block.embed_url}
        text={block.label}
        caption={block.caption ?? null}
        collectivePalette={collectivePalette}
        newTabPref={newTab}
      />
    )
  }

  if (t === 'resource') {
    // About pages are public sales/preview pages — anyone can view them, so
    // we apply the same "published-only" rule used everywhere else.
    const r = block.resource
    if (!r || r.status !== 'published') return null
    const title = block.label || r.title
    const description = block.caption || r.description
    const href = r.url ? (r.url.startsWith('http') ? r.url : `${API_BASE}${r.url.startsWith('/') ? r.url : `/api/uploads/${r.url}`}`) : null
    if (!href) return null
    const isFile = !!r.file_name || ['file', 'guide', 'template', 'replay', 'audio', 'video'].includes(r.resource_type)
    const ctaLabel = isFile ? 'Download resource' : 'Open resource'
    return (
      <a
        href={href}
        target={isFile ? undefined : '_blank'}
        rel={isFile ? undefined : 'noopener noreferrer'}
        download={isFile && r.file_name ? r.file_name : undefined}
        className="group flex items-start gap-4 rounded-xl border border-border bg-white px-5 py-4 transition-colors hover:border-teal-300"
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
      </a>
    )
  }

  return null
}

export default async function PathwayAboutPage({ params }: Props) {
  const { slug, 'pathway-slug': pathwaySlug } = await params

  const [pathway, aboutBlocks, space]: [
    PathwayWithSteps | null,
    PathwayAboutBlock[],
    { colour_palette?: CollectivePaletteMeta | null } | null,
  ] = await Promise.all([
    getPathwayOverview(slug, pathwaySlug),
    getPathwayAboutBlocks(slug, pathwaySlug),
    getSpace(slug),
  ])

  if (!pathway) notFound()

  // Palette-linked block colours (``palette:<role>``) resolve against
  // this space's active palette at render time. Custom hex and legacy
  // fixed keys ignore this and render their stored values verbatim.
  const collectivePalette: CollectivePaletteMeta | null = space?.colour_palette ?? null

  const cs = getPathwayCoverStyle(pathwaySlug)
  const coverImageUrl = resolveMediaUrl(pathway.cover_image_url)
  const isComingSoon = pathway.status === 'coming_soon'
  // Use server-computed user_has_access — covers free, included, paid+entitlement, admin/creator
  const locked = !isComingSoon && !pathway.user_has_access

  const publishedOptions: PaymentOptionSummary[] = pathway.payment_options ?? []
  const isPaymentOptionsMode = pathway.pricing_mode === 'payment_options'

  const lowestOptionPrice = publishedOptions.reduce((min, o) =>
    o.effective_price_cents != null && (min == null || o.effective_price_cents < min)
      ? o.effective_price_cents : min,
    null as number | null)

  const priceLabel = locked
    ? (isPaymentOptionsMode
        ? (lowestOptionPrice != null
            ? `From $${(lowestOptionPrice / 100).toFixed(0)} AUD`
            : publishedOptions.length > 0 ? `${publishedOptions.length} options available` : 'Multiple options')
        : formatPathwayPrice(pathway.price_cents, pathway.currency, pathway.billing_interval))
    : null
  const unlockLabel = locked
    ? (isPaymentOptionsMode ? 'Choose your option' : unlockCtaLabel(pathway.access_type, pathway.price_cents, pathway.currency, pathway.billing_interval))
    : null

  const nextIncomplete = pathway.steps.find(s => !s.is_completed)
  const continueHref = nextIncomplete
    ? `/spaces/${slug}/pathways/${pathwaySlug}/${nextIncomplete.slug}`
    : `/spaces/${slug}/pathways/${pathwaySlug}/${pathway.steps[0]?.slug}`

  const progressPct = pathway.step_count > 0
    ? Math.round((pathway.completed_count / pathway.step_count) * 100)
    : 0

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 md:px-6">

      {/* Back link */}
      <div className="mb-6">
        <Link
          href={`/spaces/${slug}/pathways`}
          className="text-sm text-black transition-colors hover:text-teal-600"
        >
          ← All Pathways
        </Link>
      </div>

      {/* ── Two-column layout on desktop ── */}
      <div className="grid gap-8 lg:grid-cols-[1fr_300px]">

        {/* ── Main content ── */}
        <div>
          {/* Hero banner */}
          <div
            className="relative mb-7 overflow-hidden rounded-2xl"
            style={{
              background: cs.background,
              backgroundSize: cs.backgroundSize ?? 'auto',
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
                  style={{ background: 'linear-gradient(135deg, rgba(7,24,36,0.75) 0%, rgba(7,56,58,0.58) 100%)' }}
                />
              </>
            )}
            <div className="relative px-7 py-10 md:px-9 md:py-12">
              <div
                className="mb-3 h-[2px] w-8 rounded-full"
                style={{ background: 'var(--fc-accent, #2dd4bf)' }}
              />
              <p
                className="mb-1 text-[9px] font-bold uppercase tracking-[0.20em]"
                style={{ color: coverImageUrl ? '#FFFFFF' : cs.labelColor }}
              >
                Pathway
              </p>
              <h1
                className="font-serif text-2xl md:text-3xl"
                style={{ color: coverImageUrl ? '#FFFFFF' : cs.titleColor }}
              >
                {pathway.title}
              </h1>
              {pathway.description && (
                <p
                  className="mt-2.5 max-w-md text-[14px] leading-relaxed"
                  style={{ color: (coverImageUrl || cs.isDark) ? '#FFFFFF' : '#000000' }}
                >
                  {pathway.description}
                </p>
              )}
            </div>
          </div>

          {/* About blocks */}
          {aboutBlocks.length > 0 ? (
            <div className="space-y-6">
              {aboutBlocks.map(block => (
                <BlockRenderer key={block.id} block={block} collectivePalette={collectivePalette} />
              ))}
            </div>
          ) : (
            /* Fallback when no about blocks exist */
            <div className="space-y-4">
              {pathway.description && (
                <p className="text-[16px] leading-relaxed text-black">{pathway.description}</p>
              )}
              {pathway.step_count > 0 && (
                <p className="text-[14px] text-black">
                  {pathway.step_count} step{pathway.step_count !== 1 ? 's' : ''} in this pathway.
                </p>
              )}
            </div>
          )}
        </div>

        {/* ── Right sidebar ── */}
        <div className="flex flex-col gap-4 lg:sticky lg:top-6 lg:self-start">

          {/* CTA card */}
          <div className="rounded-2xl border border-border bg-white p-6">
            <div className="mb-4 space-y-2">
              {/* Access badge */}
              {locked ? (
                <>
                  {priceLabel && (
                    <p className="font-serif text-2xl font-bold text-navy-900">{priceLabel}</p>
                  )}
                  <p className="text-[13px] text-black">
                    {isPaymentOptionsMode
                      ? (publishedOptions.length > 1
                          ? `${publishedOptions.length} pass options — pay in full`
                          : 'Select a pass at checkout')
                      : pathway.access_type === 'subscription' ? 'Monthly access required' : 'Pay in full'}
                  </p>
                </>
              ) : isComingSoon ? (
                <p className="text-[14px] font-semibold text-black">Coming soon</p>
              ) : locked && isPaymentOptionsMode && publishedOptions.length === 0 ? (
                <p className="text-[14px] text-black">Opening soon — options coming</p>
              ) : pathway.step_count > 0 ? (
                <>
                  <div className="mb-1 flex items-baseline justify-between text-xs text-black">
                    <span>{pathway.completed_count} of {pathway.step_count} complete</span>
                    <span>{progressPct}%</span>
                  </div>
                  <div
                    className="h-1.5 w-full overflow-hidden rounded-full"
                    style={{ background: 'var(--fc-accent-soft, rgba(56,160,158,0.10))' }}
                  >
                    <div
                      className="h-full rounded-full transition-all"
                      style={{ width: `${progressPct}%`, background: 'var(--fc-accent, #14b8a6)' }}
                    />
                  </div>
                </>
              ) : null}
            </div>

            {/* Step count */}
            {pathway.step_count > 0 && (
              <p className="mb-4 text-[13px] text-black">
                {pathway.step_count} step{pathway.step_count !== 1 ? 's' : ''}
              </p>
            )}

            {/* CTA button */}
            {isComingSoon ? (
              <div
                className="flex w-full items-center justify-center gap-2 rounded-full px-5 py-2.5 text-[14px] font-medium"
                style={{ background: 'rgba(56,160,158,0.08)', color: '#073B3A' }}
              >
                <svg className="h-3.5 w-3.5 text-teal-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Coming soon
              </div>
            ) : locked ? (
              <>
                <Link
                  href={`/spaces/${slug}/pathways/${pathwaySlug}/checkout`}
                  className="block w-full rounded-full px-5 py-2.5 text-center text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
                  style={{ background: 'linear-gradient(135deg, var(--fc-accent, #38A09E) 0%, var(--fc-accent-strong, #55B8B6) 100%)' }}
                >
                  {unlockLabel ?? 'Unlock'}
                </Link>
                <p className="mt-2 text-center text-[11px] text-black">Secure checkout via Stripe</p>
              </>
            ) : pathway.steps.length > 0 && continueHref ? (
              <Link
                href={continueHref}
                className="block w-full rounded-full px-5 py-2.5 text-center text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
                style={{ background: 'linear-gradient(135deg, var(--fc-accent, #38A09E) 0%, var(--fc-accent-strong, #55B8B6) 100%)' }}
              >
                {pathway.completed_count === 0 ? 'Begin pathway' : pathway.completed_count >= pathway.step_count ? 'Review' : 'Continue'}
              </Link>
            ) : (
              <Link
                href={`/spaces/${slug}/pathways/${pathwaySlug}`}
                className="block w-full rounded-full px-5 py-2.5 text-center text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
                style={{ background: 'linear-gradient(135deg, var(--fc-accent, #38A09E) 0%, var(--fc-accent-strong, #55B8B6) 100%)' }}
              >
                View pathway
              </Link>
            )}

            {/* Link to full pathway overview */}
            <Link
              href={`/spaces/${slug}/pathways/${pathwaySlug}`}
              className="mt-3 block text-center text-[12px] text-black transition-colors hover:text-teal-600"
            >
              View all steps →
            </Link>
          </div>

          {/* Access type label */}
          {!locked && !isComingSoon && (
            <div className="rounded-xl border border-border bg-white px-4 py-3 text-center">
              <span
                className="rounded-full px-3 py-1 text-[11px] font-semibold"
                style={
                  pathway.access_type === 'free'
                    ? { background: 'rgba(16,185,129,0.10)', color: '#065F46' }
                    : { background: 'rgba(56,160,158,0.10)', color: '#073B3A' }
                }
              >
                {pathway.access_type === 'free'
                  ? 'Free'
                  : pathway.access_type === 'included'
                  ? 'Included'
                  : 'Access granted'}
              </span>
            </div>
          )}
        </div>
      </div>

    </div>
  )
}
