'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import type {
  CreatorOfferPage,
  CreatorOfferPageSummary,
  CreatorPathway,
  OfferPageStatus,
} from '@/types/platform'
import {
  Button,
  FormField,
  Input,
  Modal,
  useToast,
} from '@/components/platform'

/**
 * Offer Pages index — list rows + "New Offer Page" modal.
 *
 * The list is intentionally spare: the creator's mental model is
 * "which pages exist, which pathway does each point at, what state
 * is each in". Everything else lives inside the editor.
 *
 * "New Offer Page" is a lightweight modal: title + target pathway
 * only. On submit we POST to the backend, get a slug back, then
 * push to the editor for that slug. No secondary fields — the
 * editor is the place to fill them in.
 */

interface Props {
  spaceSlug: string
  initialOffers: CreatorOfferPageSummary[]
  pathways: CreatorPathway[]
}

const STATUS_LABEL: Record<OfferPageStatus, string> = {
  draft: 'Draft',
  published: 'Published',
  archived: 'Archived',
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

export default function OffersIndexClient({ spaceSlug, initialOffers, pathways }: Props) {
  const [offers] = useState<CreatorOfferPageSummary[]>(initialOffers)
  const [newOpen, setNewOpen] = useState(false)

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <p className="text-[13.5px] leading-relaxed text-black max-w-xl">
          Create beautiful public pages for your Pathways and share them
          wherever you invite people into your work.
        </p>
        <Button
          variant="primary"
          onClick={() => setNewOpen(true)}
          disabled={pathways.length === 0}
          title={
            pathways.length === 0
              ? 'Create a pathway first — Offer Pages point at an existing pathway.'
              : undefined
          }
        >
          New Offer Page
        </Button>
      </div>

      {offers.length === 0 ? (
        <EmptyState
          pathwaysExist={pathways.length > 0}
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
                    Pathway ·{' '}
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
          onClose={() => setNewOpen(false)}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------

function EmptyState({
  pathwaysExist, onNew,
}: {
  pathwaysExist: boolean
  onNew: () => void
}) {
  if (!pathwaysExist) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-8 py-12 text-center">
        <p className="font-serif text-[17px]" style={{ color: '#0C1826' }}>
          Start with a Pathway
        </p>
        <p
          className="mx-auto mt-2 max-w-md text-[13.5px] italic leading-relaxed"
          style={{ color: 'rgba(12,24,38,0.60)', fontFamily: 'Georgia, serif' }}
        >
          Offer Pages bring a Pathway to life as a beautiful public
          invitation. Create and publish a Pathway first, then come back
          here to shape how you invite people into it.
        </p>
        <div className="mt-5">
          <Link
            href="/creator-studio/pathways"
            className="inline-flex items-center rounded-xl px-5 py-2.5 text-[13.5px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Go to Pathways
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
        Turn one of your Pathways into a beautiful page you can share
        anywhere.
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
// New Offer Page modal — title + target pathway. On submit, POST +
// route to editor. Deliberately spare — everything else belongs in
// the editor.

function NewOfferPageModal({
  spaceSlug, pathways, onClose,
}: {
  spaceSlug: string
  pathways: CreatorPathway[]
  onClose: () => void
}) {
  const router = useRouter()
  const { show } = useToast()
  const [title, setTitle] = useState('')
  const [targetId, setTargetId] = useState<string>(pathways[0]?.id ?? '')
  const [saving, setSaving] = useState(false)

  async function create() {
    if (!title.trim() || !targetId) return
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
            target_kind: 'pathway',
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
      // Go straight into the editor for the new draft.
      router.push(`/creator-studio/offers/${created.slug}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open onClose={onClose} title="New Offer Page">
      <div className="space-y-4">
        <FormField label="Offer Page title">
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Join the winter cohort"
            autoFocus
            maxLength={200}
          />
        </FormField>
        <FormField
          label="Pathway"
          helper="You can change the pathway later while the page is a draft."
        >
          <select
            value={targetId}
            onChange={(e) => setTargetId(e.target.value)}
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400"
          >
            {pathways.map((p) => (
              <option key={p.id} value={p.id}>
                {p.title}
              </option>
            ))}
          </select>
        </FormField>
        <div className="flex justify-end gap-2">
          <Button variant="tertiary" onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            onClick={() => void create()}
            disabled={!title.trim() || !targetId || saving}
          >
            {saving ? 'Creating…' : 'Create draft'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
