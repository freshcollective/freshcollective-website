'use client'

import React, { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { apiUrl, resolveMediaUrl } from '@/lib/api'
import type {
  CreatorOffering, CreatorSpaceDetail, OfferingStatus,
} from '@/types/platform'

interface ActiveSpace { slug: string; name: string }

interface Props {
  initialOfferings: CreatorOffering[]
  activeSpace: ActiveSpace | null
  collectiveDetail: CreatorSpaceDetail | null
}

/** Creator-facing status words. "Published" and "Retired" are the
 *  approved vocabulary; a draft is called Draft rather than Pathways'
 *  "Building" because an Offering is a thing you assemble, not a
 *  journey you build. */
const STATUS_LABEL: Record<OfferingStatus, string> = {
  published: 'Published',
  draft: 'Draft',
  retired: 'Retired',
}

/** Grouped the way a creator thinks about their shelf: what is live,
 *  what is still being prepared, what has been taken off sale.
 *  Retired comes last and is never hidden — purchasers still hold it,
 *  and a retired product that disappeared would look deleted. */
const GROUPS: {
  key: OfferingStatus
  label: string
  helper: string
}[] = [
  { key: 'published', label: 'Published', helper: 'Available to members now.' },
  { key: 'draft', label: 'Draft', helper: "Only visible to you while you're preparing it." },
  { key: 'retired', label: 'Retired', helper: 'No longer sold. People who bought it keep their files.' },
]

function priceLabel(o: CreatorOffering): string | null {
  if (o.pricing_kind === 'free') return 'Free'
  if (o.pricing_kind === 'one_time' && o.price_cents) {
    const dollars = o.price_cents / 100
    return `$${dollars % 1 === 0 ? dollars.toFixed(0) : dollars.toFixed(2)}`
  }
  return null
}

export default function OfferingsClient({
  initialOfferings, activeSpace, collectiveDetail,
}: Props) {
  const router = useRouter()
  const [offerings, setOfferings] = useState(initialOfferings)
  const [creating, setCreating] = useState(false)
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const collectiveFallback = resolveMediaUrl(
    collectiveDetail?.cover_image_url ?? undefined,
  )

  if (!activeSpace) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-10 text-center">
        <p className="mb-2 text-[16px] font-semibold text-navy-900">
          No collective selected.
        </p>
        <p className="text-[14px] text-black">
          Choose a collective to start adding Offerings.
        </p>
      </div>
    )
  }

  async function create(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = title.trim()
    if (!trimmed || busy) return
    setBusy(true)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${activeSpace!.slug}/offerings`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ title: trimmed }),
        },
      )
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        // The plan-quota refusal arrives as a 403 with a sentence the
        // creator can act on ("Your Community plan includes 5
        // Offerings…"). Show it rather than a generic failure.
        setError(
          typeof body.detail === 'string'
            ? body.detail
            : `Couldn't create that Offering (${res.status}).`,
        )
        return
      }
      const created: CreatorOffering = await res.json()
      router.push(`/creator-studio/offerings/${created.slug}`)
    } catch {
      setError("Couldn't create that Offering. Please try again.")
    } finally {
      setBusy(false)
    }
  }

  const groups = GROUPS
    .map((g) => ({ ...g, items: offerings.filter((o) => o.status === g.key) }))
    .filter((g) => g.items.length > 0)

  return (
    <div>
      {/* ── Create ─────────────────────────────────────────────────── */}
      <div className="mb-8">
        {creating ? (
          <form
            onSubmit={create}
            className="rounded-2xl border border-slate-200 bg-white p-5"
          >
            <label
              htmlFor="new-offering-title"
              className="block text-[14px] font-semibold text-navy-900"
            >
              What are you offering?
            </label>
            <p className="mt-1 text-[13px] text-black">
              Give it a title to start. You can change everything later.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <input
                id="new-offering-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                maxLength={200}
                autoFocus
                placeholder="Morning Pages Workbook"
                className="min-w-0 flex-1 rounded-xl border border-slate-200 px-4 py-2.5 text-[15px] text-navy-900 outline-none focus:border-teal-400"
              />
              <button
                type="submit"
                disabled={busy || !title.trim()}
                className="rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
                style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
              >
                {busy ? 'Creating…' : 'Create'}
              </button>
              <button
                type="button"
                onClick={() => { setCreating(false); setError(null) }}
                className="rounded-xl border border-slate-200 px-4 py-2.5 text-[14px] font-medium text-black hover:border-slate-300"
              >
                Cancel
              </button>
            </div>
            {error && (
              <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-700">
                {error}
              </p>
            )}
          </form>
        ) : (
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="inline-flex items-center rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Create Offering
          </button>
        )}
      </div>

      {/* ── Empty state ────────────────────────────────────────────── */}
      {offerings.length === 0 && !creating && (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-10 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">
            No Offerings yet
          </p>
          <p className="mx-auto max-w-[46ch] text-[14px] leading-relaxed text-black">
            An Offering is something people download and keep — a workbook, a
            recorded practice, a template. Add the files, choose a cover, and
            decide whether it&rsquo;s free or paid.
          </p>
        </div>
      )}

      {/* ── Grouped list ───────────────────────────────────────────── */}
      {groups.map((group) => (
        <section key={group.key} className="mb-10">
          <div className="mb-4">
            <h2 className="text-[15px] font-semibold text-navy-900">
              {group.label}
            </h2>
            <p className="mt-0.5 text-[13px] text-black">{group.helper}</p>
          </div>
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {group.items.map((offering) => (
              <OfferingCard
                key={offering.id}
                offering={offering}
                collectiveFallback={collectiveFallback}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

function OfferingCard({
  offering, collectiveFallback,
}: {
  offering: CreatorOffering
  collectiveFallback: string | null
}) {
  const artwork =
    resolveMediaUrl(offering.cover_image_url ?? undefined) ?? collectiveFallback
  const price = priceLabel(offering)
  const editHref = `/creator-studio/offerings/${offering.slug}`

  // "3 files · 2 ready" — the second half only when it differs, so a
  // fully-checked bundle reads as one clean fact rather than two.
  const fileMeta =
    offering.file_count === 0
      ? 'No files yet'
      : offering.files_passed === offering.file_count
        ? `${offering.file_count} file${offering.file_count === 1 ? '' : 's'}`
        : `${offering.file_count} file${offering.file_count === 1 ? '' : 's'} · ${offering.files_passed} ready`

  return (
    <article
      className="flex flex-col overflow-hidden rounded-2xl bg-white transition-shadow hover:shadow-md"
      style={{
        border: '1px solid rgba(12, 24, 38, 0.06)',
        boxShadow: '0 6px 20px rgba(12, 24, 38, 0.06)',
      }}
    >
      {/* Artwork. 3:2 because the curated covers are 3:2 — a 4:3 frame
          would crop them. */}
      <div
        className="relative w-full overflow-hidden"
        style={{ aspectRatio: '3 / 2', background: '#F4F7F6' }}
      >
        {artwork ? (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={artwork}
              alt=""
              className="h-full w-full object-cover"
            />
            <div
              className="pointer-events-none absolute inset-x-0 bottom-0 h-1/2"
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
        <div className="absolute bottom-3 left-3 flex flex-wrap items-center gap-1.5">
          <StatusChip status={offering.status} onArtwork={!!artwork} />
          {price && <Chip label={price} onArtwork={!!artwork} />}
        </div>
      </div>

      <div className="flex flex-1 flex-col px-5 pb-5 pt-4">
        <h3 className="font-serif text-[20px] leading-tight" style={{ color: '#0C1826' }}>
          {offering.title}
        </h3>
        <p
          className="mt-2 line-clamp-3 text-[13.5px] leading-relaxed italic"
          style={{
            color: offering.summary ? 'rgba(12, 24, 38, 0.62)' : 'rgba(12, 24, 38, 0.42)',
            fontFamily: 'Georgia, serif',
          }}
        >
          {offering.summary ?? 'No short description yet.'}
        </p>

        <p className="mt-4 text-[11.5px]" style={{ color: 'rgba(12, 24, 38, 0.45)' }}>
          {fileMeta}
        </p>

        <div className="mt-4 flex flex-wrap gap-2 pt-1">
          <Link
            href={editHref}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-[12.5px] font-medium text-black transition-colors hover:border-teal-200 hover:text-teal-700"
          >
            Edit
          </Link>
          <Link
            href={`${editHref}/preview`}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-[12.5px] font-medium text-black transition-colors hover:border-teal-200 hover:text-teal-700"
          >
            Preview ↗
          </Link>
        </div>
      </div>
    </article>
  )
}

function StatusChip({
  status, onArtwork,
}: { status: OfferingStatus; onArtwork: boolean }) {
  const palette: Record<OfferingStatus, { bg: string; text: string }> = {
    published: { bg: 'rgba(56,160,158,0.16)', text: '#0f766e' },
    draft: { bg: 'rgba(148,163,184,0.24)', text: '#334155' },
    retired: { bg: 'rgba(148,163,184,0.24)', text: '#475569' },
  }
  const chip = palette[status] ?? palette.draft
  const style: React.CSSProperties = onArtwork
    ? { background: 'rgba(255,255,255,0.94)', color: chip.text, backdropFilter: 'blur(6px)' }
    : { background: chip.bg, color: chip.text }
  return (
    <span
      className="rounded-full px-2.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-[0.12em]"
      style={style}
    >
      {STATUS_LABEL[status] ?? status}
    </span>
  )
}

function Chip({ label, onArtwork }: { label: string; onArtwork: boolean }) {
  const style: React.CSSProperties = onArtwork
    ? { background: 'rgba(255,255,255,0.94)', color: 'rgba(12,24,38,0.72)', backdropFilter: 'blur(6px)' }
    : { background: 'rgba(12,24,38,0.06)', color: 'rgba(12,24,38,0.72)' }
  return (
    <span
      className="rounded-full px-2.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-[0.12em]"
      style={style}
    >
      {label}
    </span>
  )
}
