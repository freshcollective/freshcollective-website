'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import type {
  CreatorEvent,
  CreatorGatheringSeriesSummary,
  CreatorOfferPage,
  CreatorOfferPageSummary,
  CreatorPathway,
  OfferPageStatus,
  OfferPageTargetKind,
} from '@/types/platform'
import {
  Button,
  FormField,
  Input,
  Modal,
  useToast,
} from '@/components/platform'

/**
 * Offer Pages index — list rows + "New Offer Page" wizard.
 *
 * The list is intentionally spare: the creator's mental model is
 * "which pages exist, what each one invites people into, what state
 * is each in". Everything else lives inside the editor.
 *
 * "New Offer Page" is a two-step wizard:
 *   1. Which experience type is this Offer Page for?
 *      → Pathway / Gathering Series / Gathering
 *   2. Choose the specific target + type the title.
 * On submit we POST, get a slug back, then push into the editor.
 *
 * The wizard also opens automatically when the page is visited with
 * ``?new=1&target_kind=…&target_id=…`` — this is what the shortcut
 * cards on the Pathway / Series / Gathering editors deep-link to.
 */

interface Props {
  spaceSlug: string
  initialOffers: CreatorOfferPageSummary[]
  pathways: CreatorPathway[]
  series: CreatorGatheringSeriesSummary[]
  gatherings: CreatorEvent[]
}

const STATUS_LABEL: Record<OfferPageStatus, string> = {
  draft: 'Draft',
  published: 'Published',
  archived: 'Archived',
}

/** UI-facing label — never expose `event_series` to the Creator. */
const KIND_LABEL: Record<OfferPageTargetKind, string> = {
  pathway: 'Pathway',
  event_series: 'Gathering Series',
  gathering: 'Gathering',
}

const KIND_HELPER: Record<OfferPageTargetKind, string> = {
  pathway: 'A structured journey with steps, sections and resources.',
  event_series: 'A defined term or cohort of live Gatherings sold together.',
  gathering: 'A single live session — call, workshop, or in-person event.',
}

function statusChipStyle(status: OfferPageStatus): React.CSSProperties {
  if (status === 'published') {
    return { background: 'rgba(56,160,158,0.10)', color: '#0f766e' }
  }
  if (status === 'archived') {
    return { background: 'rgba(12,24,38,0.06)', color: 'rgba(12,24,38,0.55)' }
  }
  return { background: 'rgba(214,177,63,0.14)', color: '#8a6a1f' }
}

function formatRelative(iso: string): string {
  const d = new Date(iso)
  const diffMs = Date.now() - d.getTime()
  const diffMin = Math.round(diffMs / 60000)
  if (diffMin < 60) return `${diffMin} min ago`
  const diffHr = Math.round(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDay = Math.round(diffHr / 24)
  if (diffDay < 7) return `${diffDay}d ago`
  return d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })
}

function fmtGatheringDate(iso: string): string {
  return new Date(iso).toLocaleString('en-AU', {
    weekday: 'short', day: 'numeric', month: 'short', year: 'numeric',
    hour: 'numeric', minute: '2-digit',
  }).replace(', ', ' \u00b7 ')
}

export default function OffersIndexClient({
  spaceSlug, initialOffers, pathways, series, gatherings,
}: Props) {
  const [offers] = useState<CreatorOfferPageSummary[]>(initialOffers)

  const searchParams = useSearchParams()
  const router = useRouter()

  // Preselection carried from the shortcut deep-links (Pathway /
  // Series / Gathering editors). Read from the URL exactly once, at
  // mount, via lazy ``useState`` initialisers so React never triggers
  // a cascading render for the preset values. The Creator can still
  // change their mind before submitting — the state is mutable via
  // the modal's onClose reset.
  const [presetKind, setPresetKind] = useState<OfferPageTargetKind | null>(() => {
    const k = searchParams.get('target_kind')
    return k === 'pathway' || k === 'event_series' || k === 'gathering'
      ? (k as OfferPageTargetKind)
      : null
  })
  const [presetId, setPresetId] = useState<string | null>(
    () => searchParams.get('target_id'),
  )
  const [newOpen, setNewOpen] = useState<boolean>(
    () => searchParams.get('new') === '1',
  )

  // Effect job is external-system only — strip the query string so a
  // refresh doesn't reopen the modal. No setState here.
  useEffect(() => {
    if (searchParams.get('new') === '1') {
      router.replace('/creator-studio/offers')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const hasAnyTarget =
    pathways.length > 0 || series.length > 0 || gatherings.length > 0

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <p className="text-[13.5px] leading-relaxed text-black max-w-xl">
          Create beautiful public pages for your Pathways, Gathering
          Series and individual Gatherings, and share them wherever
          you invite people into your work.
        </p>
        <Button
          variant="primary"
          onClick={() => setNewOpen(true)}
          disabled={!hasAnyTarget}
          title={
            !hasAnyTarget
              ? 'Create a Pathway, Gathering Series or Gathering first — Offer Pages invite people into an existing experience.'
              : undefined
          }
        >
          New Offer Page
        </Button>
      </div>

      {offers.length === 0 ? (
        <EmptyState
          anyTargetsExist={hasAnyTarget}
          onNew={() => setNewOpen(true)}
        />
      ) : (
        <ul className="grid gap-2">
          {offers.map((offer) => (
            <li key={offer.id}>
              <Link
                href={`/creator-studio/offers/${offer.slug}`}
                className="flex items-start gap-4 rounded-xl border border-slate-200 bg-white px-4 py-3 transition-colors hover:border-teal-300"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="truncate text-[15px] font-semibold text-navy-900">
                      {offer.title}
                    </p>
                    <span
                      className="shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider"
                      style={statusChipStyle(offer.status)}
                    >
                      {STATUS_LABEL[offer.status]}
                    </span>
                  </div>
                  <p className="mt-1 text-[12.5px]" style={{ color: 'rgba(12,24,38,0.65)' }}>
                    {KIND_LABEL[offer.target_kind]} ·{' '}
                    <span className="font-medium" style={{ color: 'rgba(12,24,38,0.85)' }}>
                      {offer.target_title ?? '(target no longer available)'}
                    </span>
                  </p>
                  <p className="mt-1 text-[11.5px]" style={{ color: 'rgba(12,24,38,0.50)' }}>
                    Updated {formatRelative(offer.updated_at)}
                  </p>
                </div>
                <span
                  aria-hidden="true"
                  className="mt-1 text-[13px]"
                  style={{ color: 'rgba(12,24,38,0.35)' }}
                >
                  →
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}

      {newOpen && (
        <NewOfferPageModal
          spaceSlug={spaceSlug}
          pathways={pathways}
          series={series}
          gatherings={gatherings}
          presetKind={presetKind}
          presetId={presetId}
          onClose={() => {
            setNewOpen(false)
            setPresetKind(null)
            setPresetId(null)
          }}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------

function EmptyState({
  anyTargetsExist, onNew,
}: {
  anyTargetsExist: boolean
  onNew: () => void
}) {
  if (!anyTargetsExist) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-8 py-12 text-center">
        <p className="font-serif text-[17px]" style={{ color: '#0C1826' }}>
          Nothing to invite people into yet
        </p>
        <p
          className="mx-auto mt-2 max-w-md text-[13.5px] italic leading-relaxed"
          style={{ color: 'rgba(12,24,38,0.60)', fontFamily: 'Georgia, serif' }}
        >
          Offer Pages bring a Pathway, Gathering Series or single
          Gathering to life as a public invitation. Create one of
          those first, then come back here to shape how you invite
          people into it.
        </p>
        <div className="mt-5 flex flex-wrap justify-center gap-2">
          <Link
            href="/creator-studio/pathways"
            className="inline-flex items-center rounded-xl border border-slate-200 px-4 py-2 text-[13px] font-medium text-slate-700 transition-colors hover:border-teal-300 hover:text-teal-700"
          >
            Go to Pathways
          </Link>
          <Link
            href="/creator-studio/gatherings"
            className="inline-flex items-center rounded-xl border border-slate-200 px-4 py-2 text-[13px] font-medium text-slate-700 transition-colors hover:border-teal-300 hover:text-teal-700"
          >
            Go to Gatherings
          </Link>
        </div>
      </div>
    )
  }
  return (
    <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-8 py-12 text-center">
      <p className="font-serif text-[17px]" style={{ color: '#0C1826' }}>
        Create your first Offer Page
      </p>
      <p
        className="mx-auto mt-2 max-w-md text-[13.5px] italic leading-relaxed"
        style={{ color: 'rgba(12,24,38,0.60)', fontFamily: 'Georgia, serif' }}
      >
        Turn one of your Pathways, Gathering Series or single
        Gatherings into a beautiful page you can share anywhere.
      </p>
      <div className="mt-5">
        <Button variant="primary" onClick={onNew}>
          Create Offer Page
        </Button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// New Offer Page wizard — two steps: (1) experience type, then (2)
// specific target + title. On submit, POST + route to editor.
// Deliberately spare — everything else belongs in the editor.

function NewOfferPageModal({
  spaceSlug, pathways, series, gatherings,
  presetKind, presetId, onClose,
}: {
  spaceSlug: string
  pathways: CreatorPathway[]
  series: CreatorGatheringSeriesSummary[]
  gatherings: CreatorEvent[]
  presetKind: OfferPageTargetKind | null
  presetId: string | null
  onClose: () => void
}) {
  const router = useRouter()
  const { show } = useToast()

  // Available kinds — hide the ones the Creator has nothing to
  // attach to yet, so the wizard never dead-ends on step 2.
  const availableKinds = useMemo<OfferPageTargetKind[]>(() => {
    const out: OfferPageTargetKind[] = []
    if (pathways.length > 0) out.push('pathway')
    if (series.length > 0) out.push('event_series')
    if (gatherings.length > 0) out.push('gathering')
    return out
  }, [pathways, series, gatherings])

  // If we were preselected, jump past step 1. Otherwise start on
  // step 1 unless there's only one available kind — one-choice
  // pickers are pointless.
  const initialKind: OfferPageTargetKind | null =
    presetKind && availableKinds.includes(presetKind)
      ? presetKind
      : availableKinds.length === 1
        ? availableKinds[0]
        : null

  const [kind, setKind] = useState<OfferPageTargetKind | null>(initialKind)
  const [step, setStep] = useState<'kind' | 'details'>(
    initialKind ? 'details' : 'kind',
  )

  // Look up the display title for a given (kind, id) so the modal
  // can prefill the Offer Page title from the preselected target —
  // saves the Creator retyping "EMBODY Term 3 2026" when they land
  // here from a shortcut. Empty string when the target can't be
  // found (deleted between refreshes, cache mismatch, etc).
  const targetTitleOf = (k: OfferPageTargetKind, id: string): string => {
    if (!id) return ''
    if (k === 'pathway') return pathways.find((p) => p.id === id)?.title ?? ''
    if (k === 'event_series') return series.find((s) => s.id === id)?.title ?? ''
    return gatherings.find((g) => g.id === id)?.title ?? ''
  }

  // Target IDs per kind, preseeded from the preset when it matches
  // and otherwise from the first available option.
  const initialTargetId = (k: OfferPageTargetKind): string => {
    if (presetKind === k && presetId) return presetId
    if (k === 'pathway') return pathways[0]?.id ?? ''
    if (k === 'event_series') return series[0]?.id ?? ''
    return gatherings[0]?.id ?? ''
  }
  const [targetId, setTargetId] = useState<string>(
    kind ? initialTargetId(kind) : '',
  )

  // Prefill the Offer Page title from the preselected target's title
  // when we were deep-linked from a shortcut. The Creator can edit
  // before submitting; the field is intentionally not clamped once
  // they've started typing. When the modal was opened with no
  // preselection, the title starts blank.
  const [title, setTitle] = useState<string>(
    presetKind && kind === presetKind && targetId
      ? targetTitleOf(presetKind, targetId)
      : '',
  )
  const [saving, setSaving] = useState(false)

  function selectKind(k: OfferPageTargetKind) {
    setKind(k)
    setTargetId(initialTargetId(k))
    setStep('details')
  }

  function backToKind() {
    // Never let the Creator go back to the kind picker for a
    // preselected shortcut deep-link — the shortcut has already
    // told us what the Offer Page is for.
    if (presetKind) return
    setStep('kind')
  }

  async function create() {
    if (!kind || !title.trim() || !targetId) return
    setSaving(true)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/offers`),
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: title.trim(),
            target_kind: kind,
            target_id: targetId,
          }),
        },
      )
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        show(
          typeof body.detail === 'string' ? body.detail : 'Could not create Offer Page.',
          { tone: 'error' },
        )
        return
      }
      const created: CreatorOfferPage = await res.json()
      router.push(`/creator-studio/offers/${created.slug}`)
    } finally {
      setSaving(false)
    }
  }

  // ── Step 1 — Which experience type? ────────────────────────────────
  if (step === 'kind') {
    return (
      <Modal open onClose={onClose} title="What are you inviting people into?">
        <div className="space-y-3">
          {availableKinds.map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => selectKind(k)}
              className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-left transition-colors hover:border-teal-300"
            >
              <p className="text-[14px] font-semibold text-navy-900">
                {KIND_LABEL[k]}
              </p>
              <p className="mt-0.5 text-[12.5px] text-black">
                {KIND_HELPER[k]}
              </p>
            </button>
          ))}
          <div className="flex justify-end pt-2">
            <Button variant="tertiary" onClick={onClose}>Cancel</Button>
          </div>
        </div>
      </Modal>
    )
  }

  // ── Step 2 — Specific target + title ───────────────────────────────
  const targetLabel = kind ? KIND_LABEL[kind] : ''
  return (
    <Modal open onClose={onClose} title={`New Offer Page · ${targetLabel}`}>
      <div className="space-y-4">
        {!presetKind && (
          <button
            type="button"
            onClick={backToKind}
            className="text-[12.5px] font-medium text-teal-700 hover:underline"
          >
            ← Change type
          </button>
        )}
        <FormField label={`${targetLabel} to invite people into`}>
          <select
            value={targetId}
            onChange={(e) => setTargetId(e.target.value)}
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400"
          >
            {kind === 'pathway' && pathways.map((p) => (
              <option key={p.id} value={p.id}>{p.title}</option>
            ))}
            {kind === 'event_series' && series.map((s) => (
              <option key={s.id} value={s.id}>{s.title}</option>
            ))}
            {kind === 'gathering' && gatherings.map((g) => (
              <option key={g.id} value={g.id}>
                {g.title} · {fmtGatheringDate(g.starts_at)}
              </option>
            ))}
          </select>
        </FormField>
        <FormField label="Offer Page title">
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Join the winter cohort"
            autoFocus
            maxLength={200}
          />
        </FormField>
        <div className="flex justify-end gap-2">
          <Button variant="tertiary" onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            onClick={() => void create()}
            disabled={!kind || !title.trim() || !targetId || saving}
          >
            {saving ? 'Creating…' : 'Create draft'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
