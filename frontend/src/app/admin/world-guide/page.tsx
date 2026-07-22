'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'
import {
  CATEGORY_LABEL,
  WG,
  type DocumentSummary,
  type WorldGuideOverview,
} from '@/lib/worldGuide'

/**
 * World Guide — admin dashboard.
 *
 * The single source of truth for governance documentation. Presents
 * counts (published, draft, archived), the most recently published
 * document, and a small list of recently-updated documents with the
 * standard quick-actions to create or manage documents.
 */

const SERIF_ITALIC: React.CSSProperties = {
  color: WG.inkMuted,
  fontFamily: 'Georgia, serif',
  fontStyle: 'italic',
}


export default function WorldGuideDashboard() {
  const [overview, setOverview] = useState<WorldGuideOverview | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(apiUrl('/api/admin/world-guide/overview'), { credentials: 'include' })
      .then(async (r) => {
        if (!r.ok) throw new Error(`Overview: ${r.status}`)
        return r.json() as Promise<WorldGuideOverview>
      })
      .then(setOverview)
      .catch((e: Error) => setError(e.message))
  }, [])

  const counts = overview ?? {
    published_count: 0,
    draft_count: 0,
    archived_count: 0,
    last_published: null,
    recently_updated: [],
  }

  return (
    <div style={{ background: WG.pageBg, minHeight: '100%' }}>
      <div className="mx-auto max-w-[1200px] px-6 py-10 md:px-10">
        {/* Hero */}
        <header className="mb-10 max-w-[720px]">
          <div
            className="mb-3 h-px w-10"
            style={{ background: WG.accent }}
          />
          <h1
            className="font-serif text-[32px] leading-tight md:text-[40px]"
            style={{ color: WG.inkStrong }}
          >
            World Guide
          </h1>
          <p className="mt-3 text-[15px] leading-relaxed" style={SERIF_ITALIC}>
            The single source of truth for governance, policies, and platform
            documentation. Every document here is versioned, editable while in
            draft, and published as a public web page.
          </p>
        </header>

        {error && (
          <div
            className="mb-6 rounded-2xl px-4 py-3 text-[13px]"
            style={{ background: 'rgba(214, 96, 87, 0.08)', border: '1px solid rgba(214, 96, 87, 0.28)', color: '#a63c30' }}
          >
            {error}
          </div>
        )}

        {/* Counts */}
        <section className="mb-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Published documents" value={counts.published_count} accent />
          <StatCard label="Draft documents"     value={counts.draft_count} />
          <StatCard label="Archived"            value={counts.archived_count} muted />
          <LastPublishedCard doc={counts.last_published} />
        </section>

        {/* Quick actions */}
        <section className="mb-10">
          <div className="mb-3">
            <h2 className="font-serif text-[22px] leading-tight" style={{ color: WG.inkStrong }}>
              Quick actions
            </h2>
          </div>
          <div className="flex flex-wrap gap-3">
            <QuickAction href="/admin/world-guide/documents/new" primary>
              Create document
            </QuickAction>
            <QuickAction href="/admin/world-guide/documents">
              Browse documents
            </QuickAction>
            <QuickAction href="/world-guide" external>
              View published World Guide
            </QuickAction>
          </div>
        </section>

        {/* Recently updated */}
        <section className="mb-16">
          <div className="mb-3">
            <h2 className="font-serif text-[22px] leading-tight" style={{ color: WG.inkStrong }}>
              Recently updated
            </h2>
          </div>
          {counts.recently_updated.length === 0 ? (
            <div
              className="rounded-2xl px-8 py-14 text-center"
              style={{ background: WG.cardBg, border: WG.divider, boxShadow: WG.cardShadow }}
            >
              <p className="mx-auto max-w-[520px] text-[14px] leading-relaxed" style={SERIF_ITALIC}>
                No documents yet. Start with the first one to build the foundation of
                Fresh Collective&rsquo;s World Guide.
              </p>
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {counts.recently_updated.map((d) => (
                <RecentDocRow key={d.id} doc={d} />
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}


function StatCard({
  label, value, accent, muted,
}: { label: string; value: number; accent?: boolean; muted?: boolean }) {
  return (
    <div
      className="rounded-2xl px-5 py-4"
      style={{ background: WG.cardBg, border: WG.divider, boxShadow: WG.cardShadow }}
    >
      <div className="text-[11.5px] font-semibold uppercase tracking-wide" style={{ color: WG.inkSofter }}>
        {label}
      </div>
      <div
        className="mt-1 font-serif text-[32px] leading-none"
        style={{ color: accent ? WG.teal : muted ? WG.inkMuted : WG.inkStrong }}
      >
        {value}
      </div>
    </div>
  )
}


function LastPublishedCard({ doc }: { doc: DocumentSummary | null }) {
  return (
    <div
      className="rounded-2xl px-5 py-4"
      style={{ background: WG.cardBg, border: WG.divider, boxShadow: WG.cardShadow }}
    >
      <div className="text-[11.5px] font-semibold uppercase tracking-wide" style={{ color: WG.inkSofter }}>
        Last published
      </div>
      {doc ? (
        <>
          <div className="mt-1 font-serif text-[18px] leading-tight" style={{ color: WG.ink }}>
            {doc.title}
          </div>
          <div className="mt-1 text-[12.5px]" style={{ color: WG.inkMuted }}>
            v{doc.current_version_number} · {CATEGORY_LABEL[doc.category] ?? doc.category}
          </div>
          <Link
            href={`/admin/world-guide/documents/${doc.id}`}
            className="mt-2 inline-block text-[12.5px] font-semibold"
            style={{ color: WG.accent }}
          >
            Open document →
          </Link>
        </>
      ) : (
        <div className="mt-1 text-[13px]" style={{ color: WG.inkMuted }}>
          Nothing published yet.
        </div>
      )}
    </div>
  )
}


function QuickAction({
  href, primary, external, children,
}: { href: string; primary?: boolean; external?: boolean; children: React.ReactNode }) {
  const style: React.CSSProperties = primary
    ? { background: WG.navy, color: '#FFFFFF' }
    : { background: WG.cardBg, color: WG.ink, border: WG.divider }
  return (
    <Link
      href={href}
      target={external ? '_blank' : undefined}
      rel={external ? 'noopener noreferrer' : undefined}
      className="rounded-full px-5 py-2 text-[13px] font-semibold transition-opacity hover:opacity-90"
      style={style}
    >
      {children}
    </Link>
  )
}


function RecentDocRow({ doc }: { doc: DocumentSummary }) {
  return (
    <Link
      href={`/admin/world-guide/documents/${doc.id}`}
      className="block rounded-2xl px-5 py-4 transition-shadow hover:shadow-md"
      style={{ background: WG.cardBg, border: WG.divider, boxShadow: WG.cardShadow }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-serif text-[16px] leading-tight" style={{ color: WG.ink }}>
            {doc.title}
          </div>
          <div className="mt-1 text-[12px]" style={{ color: WG.inkMuted }}>
            {CATEGORY_LABEL[doc.category] ?? doc.category}
            {doc.current_version_number ? ` · v${doc.current_version_number}` : ' · draft'}
          </div>
        </div>
        <StatusPill status={doc.status} />
      </div>
    </Link>
  )
}


function StatusPill({ status }: { status: 'draft' | 'published' | 'archived' }) {
  const style: Record<typeof status, React.CSSProperties> = {
    draft:     { background: 'rgba(27,26,23,0.06)', color: WG.inkMuted, border: WG.hairline },
    published: { background: WG.accentSoft, color: WG.accent, border: `1px solid ${WG.accent}22` },
    archived:  { background: 'rgba(214,96,87,0.06)', color: '#a63c30', border: '1px solid rgba(214,96,87,0.20)' },
  }
  const label = status === 'published' ? 'Published' : status === 'draft' ? 'Draft' : 'Archived'
  return (
    <span
      className="shrink-0 rounded-full px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide"
      style={style[status]}
    >
      {label}
    </span>
  )
}
