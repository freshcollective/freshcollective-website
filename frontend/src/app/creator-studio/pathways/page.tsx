import Link from 'next/link'
import { getActiveCreatorSpace, getCreatorPathways } from '@/lib/serverApi'
import type { CreatorPathway } from '@/types/platform'

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
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default async function PathwaysPage() {
  const activeSpace = await getActiveCreatorSpace()
  const pathways: CreatorPathway[] = activeSpace
    ? await getCreatorPathways(activeSpace.slug)
    : []

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">

      <div className="mb-8 flex items-start justify-between gap-4">
        <div>
          {activeSpace && (
            <p
              className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
              style={{ color: '#38A09E' }}
            >
              {activeSpace.name}
            </p>
          )}
          <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Pathways</h1>
          <p className="mt-2 text-[15px] leading-relaxed" style={{ color: '#334155' }}>
            Create guided journeys people can move through over time.
          </p>
        </div>
        {activeSpace && (
          <Link
            href="/creator-studio/pathways/new"
            className="mt-1 shrink-0 rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Create pathway
          </Link>
        )}
      </div>

      {/* No collective selected */}
      {!activeSpace && (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">No collective selected</p>
          <p className="mb-6 text-[14px] leading-relaxed text-slate-500">
            Choose a collective from the sidebar to manage its pathways.
          </p>
          <Link
            href="/creator-studio"
            className="inline-flex items-center rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Back to Studio Home
          </Link>
        </div>
      )}

      {/* No pathways yet */}
      {activeSpace && pathways.length === 0 && (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-10 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">No pathways yet.</p>
          <p className="mb-6 text-[14px] leading-relaxed text-slate-500">
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
      )}

      {/* Pathway list — grouped by status */}
      {pathways.length > 0 && (() => {
        const byStatus = (statuses: string[]) =>
          pathways
            .filter((p) => statuses.includes(p.status))
            .sort((a, b) => {
              const da = new Date(a.updated_at ?? a.created_at ?? 0).getTime()
              const db = new Date(b.updated_at ?? b.created_at ?? 0).getTime()
              return db - da
            })

        const published   = byStatus(['active'])
        const comingSoon  = byStatus(['coming_soon'])
        const drafts      = byStatus(['draft'])
        const archived    = byStatus(['archived'])

        const sections = [
          {
            key: 'published',
            label: 'Published',
            helper: 'Visible to members according to access settings.',
            items: published,
            muted: false,
          },
          {
            key: 'coming_soon',
            label: 'Coming soon',
            helper: 'Shown as coming soon, but not yet available.',
            items: comingSoon,
            muted: false,
          },
          {
            key: 'drafts',
            label: 'Drafts',
            helper: 'Only visible to you while you build.',
            items: drafts,
            muted: false,
          },
          {
            key: 'archived',
            label: 'Archived',
            helper: 'Hidden from members and kept for your records.',
            items: archived,
            muted: true,
          },
        ].filter((s) => s.items.length > 0)

        return (
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
                    style={
                      section.muted
                        ? { background: 'rgba(0,0,0,0.04)', color: '#94a3b8' }
                        : { background: 'rgba(56,160,158,0.09)', color: '#38A09E' }
                    }
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
                    return (
                      <div
                        key={pathway.id}
                        className="group rounded-2xl border bg-white p-5 transition-all hover:shadow-sm"
                        style={{
                          borderColor: section.muted ? 'rgba(0,0,0,0.06)' : undefined,
                          opacity: section.muted ? 0.72 : 1,
                        }}
                      >
                        <div className="flex items-start gap-4">
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <p
                                className="text-[15px] font-semibold"
                                style={{ color: section.muted ? '#64748b' : '#152236' }}
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
                              <p className="mt-1.5 line-clamp-2 text-[13px] leading-relaxed text-slate-500">
                                {pathway.description}
                              </p>
                            )}
                            <div className="mt-3 flex flex-wrap items-center gap-4 text-[12px] text-slate-400">
                              <span>{pathway.step_count} {pathway.step_count === 1 ? 'step' : 'steps'}</span>
                              {dateStr && <span>Updated {formatDate(dateStr)}</span>}
                            </div>
                          </div>
                          <Link
                            href={`/creator-studio/pathways/${pathway.slug}`}
                            className="shrink-0 rounded-lg border border-border px-3 py-1.5 text-[13px] font-medium text-slate-600 transition-colors hover:border-teal-200 hover:text-teal-700"
                          >
                            Edit →
                          </Link>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        )
      })()}

    </div>
  )
}
