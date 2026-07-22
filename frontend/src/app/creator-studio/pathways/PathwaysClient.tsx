'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import type { CreatorPathway, SpaceSummary } from '@/types/platform'

// ---------------------------------------------------------------------------
// Display helpers
// ---------------------------------------------------------------------------

const STATUS_STYLE: Record<string, { bg: string; text: string }> = {
  active:      { bg: 'rgba(56,160,158,0.10)', text: '#38A09E' },
  draft:       { bg: 'rgba(0,0,0,0.06)',       text: '#64748b' },
  coming_soon: { bg: 'rgba(212,176,72,0.12)',  text: '#b08d2a' },
  archived:    { bg: 'rgba(0,0,0,0.05)',       text: '#94a3b8' },
}

const ACCESS_STYLE: Record<string, { bg: string; text: string }> = {
  free:         { bg: 'rgba(56,160,158,0.09)',  text: '#38A09E' },
  included:     { bg: 'rgba(56,160,158,0.09)',  text: '#38A09E' },
  one_time:     { bg: 'rgba(214,177,63,0.14)',  text: '#7A5A00' },
  subscription: { bg: 'rgba(214,177,63,0.14)',  text: '#7A5A00' },
}

function statusLabel(status: string) {
  if (status === 'active') return 'Published'
  if (status === 'coming_soon') return 'Coming soon'
  return status.charAt(0).toUpperCase() + status.slice(1)
}

function accessLabel(p: CreatorPathway): string {
  if (p.access_type === 'included') return 'Included'
  if (p.pricing_mode === 'payment_options') return 'Payment options'
  if (p.access_type === 'one_time') {
    if (p.price_cents) {
      const dollars = p.price_cents / 100
      const formatted = Number.isInteger(dollars) ? `${dollars}` : dollars.toFixed(2)
      return `$${formatted} ${p.currency ?? 'AUD'}`
    }
    return 'Paid (one-off)'
  }
  if (p.access_type === 'subscription') {
    if (p.price_cents) {
      const dollars = p.price_cents / 100
      const formatted = Number.isInteger(dollars) ? `${dollars}` : dollars.toFixed(2)
      return `$${formatted} ${p.currency ?? 'AUD'}/mo`
    }
    return 'Paid (monthly)'
  }
  return 'Free'
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-AU', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

// ---------------------------------------------------------------------------
// Client component
// ---------------------------------------------------------------------------

interface Props {
  initialPathways: CreatorPathway[]
  activeSpace: SpaceSummary | null
}

export default function PathwaysClient({ initialPathways, activeSpace }: Props) {
  const router = useRouter()
  const [pathways, setPathways] = useState<CreatorPathway[]>(initialPathways)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  async function handleDeletePathway(pathway: CreatorPathway) {
    if (!confirm(
      `Are you sure you want to delete "${pathway.title}"? This will also remove its steps and content. This cannot be undone.`
    )) return
    setDeletingId(pathway.id)
    setDeleteError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${activeSpace!.slug}/pathways/${pathway.slug}`),
        { method: 'DELETE', credentials: 'include' },
      )
      if (res.ok) {
        setPathways((prev) => prev.filter((p) => p.id !== pathway.id))
      } else {
        setDeleteError('Failed to delete pathway. Please try again.')
      }
    } catch {
      setDeleteError('Failed to delete pathway. Please try again.')
    } finally {
      setDeletingId(null)
    }
  }

  if (!activeSpace) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
        <p className="mb-2 text-[16px] font-semibold text-navy-900">No collective selected</p>
        <p className="mb-6 text-[14px] leading-relaxed text-black">
          Choose a collective from the sidebar to manage its pathways.
        </p>
        <Link
          href="/creator-studio"
          className="inline-flex items-center rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          Back to Dashboard
        </Link>
      </div>
    )
  }

  if (pathways.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-10 text-center">
        <p className="mb-2 text-[16px] font-semibold text-navy-900">No pathways yet.</p>
        <p className="mb-6 text-[14px] leading-relaxed text-black">
          Create your first guided journey so people have a clear way through your work.
        </p>
        <Link
          href="/creator-studio/pathways/new"
          className="inline-flex items-center rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          Create pathway
        </Link>
      </div>
    )
  }

  const byStatus = (statuses: string[]) =>
    pathways
      .filter((p) => statuses.includes(p.status))
      .sort((a, b) => {
        const da = new Date(a.updated_at ?? a.created_at ?? 0).getTime()
        const db = new Date(b.updated_at ?? b.created_at ?? 0).getTime()
        return db - da
      })

  const sections = [
    {
      key: 'published',
      label: 'Published',
      helper: 'Visible to members according to access settings.',
      items: byStatus(['active']),
      muted: false,
      badgeStyle: { background: 'rgba(56,160,158,0.09)', color: '#38A09E' },
      cardStyle: {
        border: '1px solid rgba(56,160,158,0.18)',
        borderTop: '2px solid rgba(56,160,158,0.55)',
        background: '#ffffff',
      },
      titleColor: '#152236',
      opacity: 1,
    },
    {
      key: 'coming_soon',
      label: 'Coming soon',
      helper: 'Shown as coming soon, but not yet available.',
      items: byStatus(['coming_soon']),
      muted: false,
      badgeStyle: { background: 'rgba(212,176,72,0.13)', color: '#8a6a10' },
      cardStyle: {
        border: '1px solid rgba(212,176,72,0.22)',
        borderTop: '2px solid rgba(196,158,52,0.60)',
        background: '#ffffff',
      },
      titleColor: '#152236',
      opacity: 1,
    },
    {
      key: 'drafts',
      label: 'Drafts',
      helper: 'Only visible to you while you build.',
      items: byStatus(['draft']),
      muted: false,
      badgeStyle: { background: 'rgba(0,0,0,0.05)', color: '#64748b' },
      cardStyle: {
        border: '1px solid rgba(0,0,0,0.08)',
        borderTop: '2px solid rgba(148,163,184,0.45)',
        background: '#ffffff',
      },
      titleColor: '#152236',
      opacity: 1,
    },
    {
      key: 'archived',
      label: 'Archived',
      helper: 'Hidden from members and kept for your records.',
      items: byStatus(['archived']),
      muted: true,
      badgeStyle: { background: 'rgba(0,0,0,0.04)', color: '#94a3b8' },
      cardStyle: {
        border: '1px solid rgba(0,0,0,0.05)',
        background: 'rgba(0,0,0,0.018)',
      },
      titleColor: '#94a3b8',
      opacity: 0.70,
    },
  ].filter((s) => s.items.length > 0)

  return (
    <>
      {deleteError && (
        <div className="mb-6 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700">
          {deleteError}
        </div>
      )}

      <div className="space-y-8">
        {sections.map((section) => (
          <div key={section.key}>
            {/* Section heading */}
            <div className="mb-3 flex items-baseline gap-2.5">
              <h2
                className="text-[15px] font-semibold"
                style={{ color: section.muted ? '#94a3b8' : '#152236' }}
              >
                {section.label}
              </h2>
              <span
                className="rounded-full px-2 py-0.5 text-[11px] font-medium"
                style={section.badgeStyle}
              >
                {section.items.length}
              </span>
              <span
                className="text-[12px]"
                style={{ color: section.muted ? '#cbd5e1' : '#94a3b8' }}
              >
                {section.helper}
              </span>
            </div>

            {/* Cards */}
            <div className="space-y-3">
              {section.items.map((pathway) => {
                const statusStyle = STATUS_STYLE[pathway.status] ?? STATUS_STYLE.draft
                const accessStyle = ACCESS_STYLE[pathway.access_type] ?? ACCESS_STYLE.free
                const dateStr = pathway.updated_at ?? pathway.created_at
                const isDeleting = deletingId === pathway.id
                return (
                  <div
                    key={pathway.id}
                    className="group overflow-hidden rounded-2xl p-5 transition-all hover:shadow-sm"
                    style={{ ...section.cardStyle, opacity: isDeleting ? 0.5 : section.opacity }}
                  >
                    <div className="flex items-start gap-4">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <p
                            className="text-[15px] font-semibold"
                            style={{ color: section.titleColor }}
                          >
                            {pathway.title}
                          </p>
                          <span
                            className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
                            style={{ background: statusStyle.bg, color: statusStyle.text }}
                          >
                            {statusLabel(pathway.status)}
                          </span>
                          <span
                            className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
                            style={{ background: accessStyle.bg, color: accessStyle.text }}
                          >
                            {accessLabel(pathway)}
                          </span>
                        </div>
                        {pathway.description && (
                          <p className="mt-1.5 line-clamp-2 text-[13px] leading-relaxed text-black">
                            {pathway.description}
                          </p>
                        )}
                        <div className="mt-3 flex flex-wrap items-center gap-4 text-[12px] text-black">
                          <span>{pathway.step_count} {pathway.step_count === 1 ? 'step' : 'steps'}</span>
                          {dateStr && <span>Updated {formatDate(dateStr)}</span>}
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <Link
                          href={`/creator-studio/pathways/${pathway.slug}`}
                          className="rounded-lg border border-slate-200 px-3 py-1.5 text-[13px] font-medium text-black transition-colors hover:border-teal-200 hover:text-teal-700"
                        >
                          Edit →
                        </Link>
                        <button
                          type="button"
                          onClick={() => handleDeletePathway(pathway)}
                          disabled={isDeleting}
                          className="rounded-lg border border-slate-200 px-3 py-1.5 text-[13px] font-medium text-black transition-colors hover:border-red-200 hover:text-red-500 disabled:opacity-40"
                        >
                          {isDeleting ? 'Deleting…' : 'Delete'}
                        </button>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </>
  )
}
