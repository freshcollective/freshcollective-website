'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { apiUrl, resolveMediaUrl } from '@/lib/api'
import type { CreatorPathway, CreatorSpaceDetail, SpaceSummary } from '@/types/platform'
import PrimaryActionLink from '@/components/creator/PrimaryActionLink'
import { unitCountLabel } from '@/lib/pathwayTerminology'
import {
  ARCHIVE_CONFIRM_PARAGRAPHS,
  DELETE_CONFIRM_PARAGRAPHS,
  GENERIC_ARCHIVE_ERROR,
  GENERIC_DELETE_ERROR,
  GENERIC_RESTORE_ERROR,
  NOT_DELETABLE_PARAGRAPHS,
  RESTORED_STATUS,
  actionErrorMessage,
  isArchivableStatus,
  isDeletableStatus,
  isRestorableStatus,
} from '@/lib/pathwayLifecycle'

/**
 * Creator Studio → Pathways.
 *
 * A gallery of journeys, not a management list. Every pathway is
 * anchored by artwork (its own cover, the collective's Location, or a
 * quiet neutral fallback) and grouped by lifecycle state.
 *
 * The page shows the whole catalogue, grouped by lifecycle state:
 * Live, Coming soon, Building, and Archived.
 *
 * Archived used to be hidden here, on the reasoning that "deletion is
 * the way to remove a pathway from the collective". That left archived
 * pathways in a trap: the Settings status dropdown has always offered
 * Archived, and choosing it made the pathway vanish from this page
 * with no route back except typing its settings URL from memory. The
 * group below is that route, and it carries Restore.
 */

// ---------------------------------------------------------------------------
// Small display helpers
// ---------------------------------------------------------------------------

function statusLabel(status: string): string {
  if (status === 'active') return 'Live'
  if (status === 'coming_soon') return 'Coming soon'
  if (status === 'draft') return 'Building'
  if (status === 'archived') return 'Archived'
  return status
}

function accessLabel(p: CreatorPathway): string | null {
  if (p.access_type === 'free') return 'Free'
  if (p.access_type === 'included' || p.access_type === 'included_with_offer') return 'Included'
  if (p.pricing_mode === 'payment_options') return 'Payment options'
  if (p.access_type === 'one_time') {
    if (p.price_cents) return `$${formatPrice(p.price_cents)} ${p.currency ?? 'AUD'}`
    return 'Paid'
  }
  if (p.access_type === 'subscription') {
    if (p.price_cents) return `$${formatPrice(p.price_cents)} ${p.currency ?? 'AUD'}/mo`
    return 'Paid · monthly'
  }
  return null
}

function formatPrice(cents: number): string {
  const dollars = cents / 100
  return Number.isInteger(dollars) ? String(dollars) : dollars.toFixed(2)
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })
}

// Ordered so the page reads Live → Coming soon → Building →
// Archived: in front of members first, then in progress, then put
// away. New statuses can be added by extending this list; only groups
// with items render, so a collective with nothing archived looks
// exactly as it did before.
const STATUS_ORDER: {
  key: string
  label: string
  helper: string
  match: (p: CreatorPathway) => boolean
}[] = [
  { key: 'live',        label: 'Live',        helper: 'Available for members to begin.',                match: (p) => p.status === 'active' },
  { key: 'coming_soon', label: 'Coming soon', helper: 'Ready and waiting for release.',                 match: (p) => p.status === 'coming_soon' },
  { key: 'building',    label: 'Building',    helper: "Only visible to you while you're creating.",     match: (p) => p.status === 'draft' },
  { key: 'archived',    label: 'Archived',    helper: 'Not offered any more. Members who already have access keep it.', match: (p) => p.status === 'archived' },
]

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface Props {
  initialPathways: CreatorPathway[]
  activeSpace: SpaceSummary | null
  /** Collective identity used as the pathway-artwork fallback (Location
   *  hero / thumbnail / collective banner). Passed from the server so
   *  cards render immediately without a client fetch. */
  collectiveDetail: CreatorSpaceDetail | null
}

export default function PathwaysClient({ initialPathways, activeSpace, collectiveDetail }: Props) {
  const [pathways, setPathways] = useState<CreatorPathway[]>(initialPathways)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Which pathway is awaiting confirmation, and for which action.
  // Restore is absent on purpose: it is reversible and puts the
  // pathway back as a draft, so there is nothing to warn about.
  const [confirming, setConfirming] = useState<
    { pathway: CreatorPathway; action: 'delete' | 'archive' } | null
  >(null)

  // ── Collective-level artwork fallback (resolved once) ──────────────
  const collectiveFallback = resolveMediaUrl(
    collectiveDetail?.location?.hero_artwork_url
      ?? collectiveDetail?.location?.thumbnail_artwork_url
      ?? collectiveDetail?.cover_image_url
      ?? undefined,
  )

  // ── Actions ────────────────────────────────────────────────────────

  /**
   * Delete, and say what happened when it doesn't.
   *
   * This used to answer every failure with "Please try again", which
   * was the worst possible response to the one failure that actually
   * occurs: the API now refuses with a 409 and a sentence naming the
   * record it is protecting — a member's entitlement, a shared Payment
   * Option, a comment on a step. "Try again" invites the creator to
   * repeat an action that will never succeed, and tells them nothing
   * about what to do instead.
   *
   * The choice of message lives in ``lib/pathwayDelete`` so it can be
   * tested without a browser, and so the component cannot drift from
   * it.
   */
  async function performDelete(pathway: CreatorPathway) {
    if (!activeSpace) return
    setBusyId(pathway.id)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${activeSpace.slug}/pathways/${pathway.slug}`),
        { method: 'DELETE', credentials: 'include' },
      )
      if (!res.ok) {
        setError(actionErrorMessage(
          await res.json().catch(() => null), GENERIC_DELETE_ERROR,
        ))
        return
      }
      setPathways((prev) => prev.filter((p) => p.id !== pathway.id))
    } catch {
      // The network, not a refusal — nothing specific to report.
      setError(GENERIC_DELETE_ERROR)
    } finally {
      setBusyId(null)
      setConfirming(null)
    }
  }

  /**
   * Archive and Restore are the same request with a different status,
   * so they are one function.
   *
   * The row is updated in place rather than refetched: the list is
   * already grouped by status, so moving the status moves the card
   * into its new group on the next render. Nothing else about the
   * pathway changes — archiving is a status change and nothing more,
   * which is exactly why it is safe to offer here.
   */
  async function setStatus(pathway: CreatorPathway, status: string) {
    if (!activeSpace) return
    const fallback = status === RESTORED_STATUS
      ? GENERIC_RESTORE_ERROR
      : GENERIC_ARCHIVE_ERROR
    setBusyId(pathway.id)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${activeSpace.slug}/pathways/${pathway.slug}`),
        {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status }),
        },
      )
      if (!res.ok) {
        setError(actionErrorMessage(
          await res.json().catch(() => null), fallback,
        ))
        return
      }
      const updated = await res.json().catch(() => null)
      const nextStatus: string = (
        typeof updated?.status === 'string' ? updated.status : status
      )
      setPathways((prev) => prev.map(
        (p) => (p.id === pathway.id
          ? { ...p, status: nextStatus as CreatorPathway['status'] }
          : p),
      ))
    } catch {
      setError(fallback)
    } finally {
      setBusyId(null)
      setConfirming(null)
    }
  }

  // ── Empty / no-collective states ───────────────────────────────────

  if (!activeSpace) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-10 text-center">
        <p className="mb-2 text-[16px] font-semibold text-navy-900">No collective selected.</p>
        <p className="mb-6 text-[14px] leading-relaxed text-black">
          Choose a collective from My World to see the journeys inside it.
        </p>
        <PrimaryActionLink href="/creator-studio" showIcon={false}>
          Go to My World
        </PrimaryActionLink>
      </div>
    )
  }

  // Every status is shown now, archived included — see the Archived
  // group in STATUS_ORDER above and the trap it exists to close.
  const visiblePathways = pathways

  if (visiblePathways.length === 0) {
    return (
      <div
        className="rounded-3xl px-8 py-16 text-center"
        style={{ background: '#FBFAF6' }}
      >
        <p className="mb-2 font-serif text-[24px] leading-snug text-navy-900">
          Your first pathway begins here.
        </p>
        <p
          className="mx-auto mb-8 max-w-md text-[14.5px] leading-relaxed italic"
          style={{ color: 'rgba(12, 24, 38, 0.62)', fontFamily: 'Georgia, serif' }}
        >
          Create a guided journey for members to move through over time.
        </p>
        <PrimaryActionLink href="/creator-studio/pathways/new">
          Create pathway
        </PrimaryActionLink>
      </div>
    )
  }

  // ── Grouped gallery ─────────────────────────────────────────────────

  const groups = STATUS_ORDER
    .map((g) => ({
      ...g,
      items: visiblePathways
        .filter(g.match)
        .sort((a, b) => {
          const da = new Date(a.updated_at ?? a.created_at ?? 0).getTime()
          const db = new Date(b.updated_at ?? b.created_at ?? 0).getTime()
          return db - da
        }),
    }))
    .filter((g) => g.items.length > 0)

  return (
    <>
      {error && (
        <div className="mb-6 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700" role="alert">
          {error}
        </div>
      )}

      <div className="space-y-12">
        {groups.map((group) => {
          const count = group.items.length
          const countLabel = `${group.label} · ${count} ${count === 1 ? 'pathway' : 'pathways'}`
          return (
            <section key={group.key} aria-label={countLabel}>
              <div className="mb-1.5 flex items-baseline gap-2">
                {/*
                  Inline colour is required. globals.css has a bare
                  `h1, h2, h3, h4, h5, h6 { color: var(--color-navy-950) }`
                  rule that lives outside any @layer, so it beats the
                  Tailwind `text-teal-700` utility in the cascade. The
                  sidebar's teal eyebrows work because they use <p>, not
                  <h2>. We use the same CSS-variable token so any future
                  change to the teal palette flows through.
                */}
                <h2
                  className="font-serif text-[22px] leading-tight"
                  style={{ color: 'var(--color-teal-700)' }}
                >
                  {group.label}
                </h2>
                <span
                  className="text-[13px]"
                  style={{ color: 'rgba(12,24,38,0.55)' }}
                >
                  · {count} {count === 1 ? 'pathway' : 'pathways'}
                </span>
              </div>
              <p
                className="mb-5 text-[12.5px] italic"
                style={{ color: 'rgba(12,24,38,0.55)', fontFamily: 'Georgia, serif' }}
              >
                {group.helper}
              </p>

              <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
                {group.items.map((pathway) => (
                  <PathwayCard
                    key={pathway.id}
                    pathway={pathway}
                    collectiveFallback={collectiveFallback}
                    busy={busyId === pathway.id}
                    onDelete={() => setConfirming({ pathway, action: 'delete' })}
                    onArchive={() => setConfirming({ pathway, action: 'archive' })}
                    onRestore={() => setStatus(pathway, RESTORED_STATUS)}
                  />
                ))}
              </div>
            </section>
          )
        })}
      </div>

      {confirming && (
        <LifecycleConfirmDialog
          pathway={confirming.pathway}
          action={confirming.action}
          busy={busyId === confirming.pathway.id}
          onCancel={() => setConfirming(null)}
          onConfirm={() => (
            confirming.action === 'delete'
              ? performDelete(confirming.pathway)
              : setStatus(confirming.pathway, 'archived')
          )}
        />
      )}
    </>
  )
}


// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

function PathwayCard({
  pathway, collectiveFallback, busy, onDelete, onArchive, onRestore,
}: {
  pathway: CreatorPathway
  collectiveFallback: string | null
  busy: boolean
  onDelete: () => void
  onArchive: () => void
  onRestore: () => void
}) {
  const artwork = resolveMediaUrl(pathway.cover_image_url ?? undefined) ?? collectiveFallback

  const access = accessLabel(pathway)
  const dateStr = pathway.updated_at ?? pathway.created_at
  const previewHref = `/creator-studio/pathways/${pathway.slug}/preview`

  return (
    <article
      className="flex flex-col overflow-hidden rounded-2xl bg-white transition-shadow hover:shadow-md"
      style={{
        border: '1px solid rgba(12, 24, 38, 0.06)',
        boxShadow: '0 6px 20px rgba(12, 24, 38, 0.06)',
        opacity: busy ? 0.55 : 1,
      }}
    >
      {/* ── Artwork — slightly taller than 3:2 so the image leads the card ── */}
      <div
        className="relative w-full overflow-hidden"
        style={{ aspectRatio: '4 / 3', background: '#F4F7F6' }}
      >
        {artwork ? (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={artwork}
              alt={`Artwork for ${pathway.title}`}
              className="h-full w-full object-cover"
            />
            <div
              className="absolute inset-x-0 bottom-0 h-1/2 pointer-events-none"
              style={{ background: 'linear-gradient(180deg, transparent 0%, rgba(7,24,36,0.32) 100%)' }}
              aria-hidden="true"
            />
          </>
        ) : (
          <div
            className="h-full w-full"
            style={{ background: 'linear-gradient(135deg, rgba(56,160,158,0.16) 0%, rgba(85,184,182,0.08) 100%)' }}
            aria-hidden="true"
          />
        )}

        {/* Chips overlaid on the artwork, bottom-left. Reading order:
            status first, then access. */}
        <div className="absolute left-3 bottom-3 flex flex-wrap items-center gap-1.5">
          <StatusChip status={pathway.status} onArtwork={!!artwork} />
          {access && <AccessChip label={access} onArtwork={!!artwork} />}
        </div>
      </div>

      {/* ── Body ── */}
      <div className="flex flex-1 flex-col px-5 pt-4 pb-5">
        <h3
          className="font-serif text-[22px] leading-tight"
          style={{ color: '#0C1826' }}
        >
          {pathway.title}
        </h3>
        <p
          className="mt-2 line-clamp-3 text-[13.5px] leading-relaxed italic"
          style={{
            color: pathway.description ? 'rgba(12, 24, 38, 0.62)' : 'rgba(12, 24, 38, 0.42)',
            fontFamily: 'Georgia, serif',
          }}
        >
          {pathway.description ?? 'No description added yet.'}
        </p>

        {/* Metadata — quiet supporting line (reduced emphasis) */}
        <p className="mt-4 text-[11.5px]" style={{ color: 'rgba(12, 24, 38, 0.45)' }}>
          <span>{unitCountLabel(pathway, pathway.step_count)}</span>
          {dateStr && (
            <>
              <span aria-hidden="true"> • </span>
              <span>Updated {formatDate(dateStr)}</span>
            </>
          )}
        </p>

        {/* Footer: Continue editing → is the primary; overflow holds
            Preview and whichever lifecycle actions this status
            offers. */}
        <div className="mt-5 flex items-center justify-between gap-2 pt-4" style={{ borderTop: '1px solid rgba(12,24,38,0.06)' }}>
          <Link
            href={`/creator-studio/pathways/${pathway.slug}`}
            className="rounded-lg px-3 py-1.5 text-[13.5px] font-semibold text-teal-700 transition-colors hover:bg-teal-50"
            aria-label={`Continue editing ${pathway.title}`}
          >
            Continue editing →
          </Link>
          <OverflowMenu
            title={pathway.title}
            status={pathway.status}
            previewHref={previewHref}
            onDelete={onDelete}
            onArchive={onArchive}
            onRestore={onRestore}
            disabled={busy}
          />
        </div>
      </div>
    </article>
  )
}


// ---------------------------------------------------------------------------
// Chips
// ---------------------------------------------------------------------------

function StatusChip({ status, onArtwork }: { status: CreatorPathway['status']; onArtwork: boolean }) {
  const palette: Record<string, { bg: string; text: string }> = {
    active:      { bg: 'rgba(56,160,158,0.16)', text: '#0f766e' },
    coming_soon: { bg: 'rgba(212,176,72,0.18)', text: '#7A5A00' },
    draft:       { bg: 'rgba(148,163,184,0.24)', text: '#334155' },
    archived:    { bg: 'rgba(148,163,184,0.24)', text: '#475569' },
  }
  const chip = palette[status] ?? palette.draft
  // Over artwork, we sit on a white pill so any status colour reads
  // cleanly against variable image luminance.
  const style: React.CSSProperties = onArtwork
    ? { background: 'rgba(255,255,255,0.94)', color: chip.text, backdropFilter: 'blur(6px)' }
    : { background: chip.bg, color: chip.text }
  return (
    <span
      className="rounded-full px-2.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-[0.12em]"
      style={style}
    >
      {statusLabel(status)}
    </span>
  )
}

function AccessChip({ label, onArtwork }: { label: string; onArtwork: boolean }) {
  const style: React.CSSProperties = onArtwork
    ? { background: 'rgba(255,255,255,0.94)', color: 'rgba(12,24,38,0.72)', backdropFilter: 'blur(6px)' }
    : { background: 'rgba(12,24,38,0.06)', color: 'rgba(12,24,38,0.72)' }
  return (
    <span
      className="rounded-full px-2.5 py-0.5 text-[10.5px] font-medium"
      style={style}
    >
      {label}
    </span>
  )
}


// ---------------------------------------------------------------------------
// Overflow menu — keyboard-accessible, outside-click + Escape to close
// ---------------------------------------------------------------------------

function OverflowMenu({
  title, status, previewHref, onDelete, onArchive, onRestore, disabled,
}: {
  title: string
  status: string
  previewHref: string
  onDelete: () => void
  onArchive: () => void
  onRestore: () => void
  disabled: boolean
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    function onDown(e: MouseEvent) {
      if (!rootRef.current) return
      if (!rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`More actions for ${title}`}
        className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-50 hover:text-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 disabled:opacity-40"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <circle cx="3" cy="8" r="1.4" fill="currentColor" />
          <circle cx="8" cy="8" r="1.4" fill="currentColor" />
          <circle cx="13" cy="8" r="1.4" fill="currentColor" />
        </svg>
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 bottom-full z-20 mb-1 w-44 overflow-hidden rounded-xl bg-white text-left"
          style={{
            border: '1px solid rgba(12,24,38,0.08)',
            boxShadow: '0 10px 30px rgba(12, 24, 38, 0.10), 0 2px 6px rgba(12, 24, 38, 0.04)',
          }}
        >
          <a
            role="menuitem"
            href={previewHref}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => setOpen(false)}
            className="block w-full px-4 py-2 text-left text-[13px] text-slate-800 transition-colors hover:bg-slate-50"
          >
            Preview
          </a>
          {/*
            One action per lifecycle state, so the menu never offers a
            press the API will decline. ``isDeletableStatus`` and
            friends mirror the server's own rules — see
            ``lib/pathwayLifecycle``.
          */}
          {isRestorableStatus(status) && (
            <button
              type="button"
              role="menuitem"
              onClick={() => { setOpen(false); onRestore() }}
              className="block w-full px-4 py-2 text-left text-[13px] text-teal-700 transition-colors hover:bg-teal-50"
            >
              Restore
            </button>
          )}
          {isArchivableStatus(status) && (
            <button
              type="button"
              role="menuitem"
              onClick={() => { setOpen(false); onArchive() }}
              className="block w-full px-4 py-2 text-left text-[13px] text-slate-800 transition-colors hover:bg-slate-50"
            >
              Archive
            </button>
          )}
          {isDeletableStatus(status) && (
            <button
              type="button"
              role="menuitem"
              onClick={() => { setOpen(false); onDelete() }}
              className="block w-full px-4 py-2 text-left text-[13px] text-red-600 transition-colors hover:bg-red-50"
            >
              Delete
            </button>
          )}
        </div>
      )}
    </div>
  )
}


// ---------------------------------------------------------------------------
// Lifecycle confirmation dialog — one shell, two actions
// ---------------------------------------------------------------------------
//
// A custom modal rather than ``confirm()`` so the copy and the button
// labels can say what actually happens. One component for both Archive
// and Delete because they share the shell exactly, and a second copy
// of it would drift.
//
// Restore deliberately has no dialog: it returns the pathway to Draft,
// where nobody but the creator can see it, and it can be undone by
// archiving again.

/**
 * What each action tells the creator before they commit to it.
 *
 * The wording lives in ``lib/pathwayLifecycle`` so it can be asserted
 * directly rather than scraped out of this file — see the note there
 * about why a source scrape is the wrong test for copy.
 */
function dialogCopy(
  pathway: CreatorPathway, action: 'delete' | 'archive',
): {
  title: string
  paragraphs: readonly string[]
  confirm: string
  busy: string
  danger: boolean
} {
  if (action === 'archive') {
    return {
      title: `Archive \u201C${pathway.title}\u201D?`,
      paragraphs: ARCHIVE_CONFIRM_PARAGRAPHS,
      confirm: 'Archive pathway',
      busy: 'Archiving…',
      danger: false,
    }
  }
  if (isDeletableStatus(pathway.status)) {
    return {
      title: `Delete \u201C${pathway.title}\u201D?`,
      paragraphs: DELETE_CONFIRM_PARAGRAPHS,
      confirm: 'Delete pathway',
      busy: 'Deleting…',
      danger: true,
    }
  }
  // Reachable only if a status changes under an open menu.
  return {
    title: `\u201C${pathway.title}\u201D cannot be deleted`,
    paragraphs: NOT_DELETABLE_PARAGRAPHS,
    confirm: '',
    busy: '',
    danger: false,
  }
}


function LifecycleConfirmDialog({
  pathway, action, busy, onCancel, onConfirm,
}: {
  pathway: CreatorPathway
  action: 'delete' | 'archive'
  busy: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const copy = dialogCopy(pathway, action)
  const actionable = copy.confirm !== ''

  // Trap Escape to cancel.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onCancel()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onCancel])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="pathway-lifecycle-title"
    >
      <div
        className="absolute inset-0"
        style={{ background: 'rgba(12, 24, 38, 0.55)' }}
        onClick={onCancel}
        aria-hidden="true"
      />
      <div
        className="relative w-full max-w-md overflow-hidden rounded-2xl bg-white"
        style={{
          boxShadow: '0 20px 60px rgba(12, 24, 38, 0.28), 0 4px 12px rgba(12, 24, 38, 0.10)',
        }}
      >
        <div className="px-6 pt-6 pb-2">
          <h2
            id="pathway-lifecycle-title"
            className="font-serif text-[22px] leading-tight text-navy-900"
          >
            {copy.title}
          </h2>
        </div>
        <div className="space-y-3 px-6 pb-6 pt-3 text-[14px] leading-relaxed text-slate-700">
          {copy.paragraphs.map((text) => <p key={text}>{text}</p>)}
        </div>
        <div
          className="flex items-center justify-end gap-2 px-6 py-4"
          style={{ background: '#FBFAF6', borderTop: '1px solid rgba(12,24,38,0.06)' }}
        >
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            autoFocus={!actionable}
            className="rounded-lg px-4 py-2 text-[13.5px] font-medium text-slate-700 transition-colors hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 disabled:opacity-50"
          >
            {actionable ? 'Cancel' : 'Close'}
          </button>
          {/* No confirm button on an action the API would decline.
              Offering one and letting the server refuse is a worse
              experience than not offering it: the creator presses it,
              waits, and gets a sentence they could have read first. */}
          {actionable && (
            <button
              type="button"
              onClick={onConfirm}
              disabled={busy}
              autoFocus
              className={
                'rounded-lg px-4 py-2 text-[13.5px] font-semibold text-white '
                + 'transition-colors focus:outline-none focus-visible:ring-2 '
                + (copy.danger
                  ? 'hover:bg-red-700 focus-visible:ring-red-400 '
                  : 'hover:opacity-90 focus-visible:ring-teal-400 ')
                + 'disabled:opacity-60'
              }
              style={{ background: copy.danger ? '#dc2626' : 'var(--color-teal-700, #0f766e)' }}
            >
              {busy ? copy.busy : copy.confirm}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
