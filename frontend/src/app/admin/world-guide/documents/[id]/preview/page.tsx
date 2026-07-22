'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import WorldGuideProse from '@/components/world-guide/WorldGuideProse'
import {
  AUDIENCE_LABEL,
  CATEGORY_LABEL,
  WG,
  type DocumentDetail,
} from '@/lib/worldGuide'

/**
 * Admin draft preview — a private, admin-authenticated view of a
 * document that reads exactly like the public World Guide page but
 * is served under `/admin/...` so unpublished drafts are never
 * exposed to the world.
 *
 * The preview reads through the same admin GET endpoint the editor
 * uses; nothing on the public API knows this route exists. If a
 * document has a draft, the draft is shown; otherwise the current
 * published version is rendered instead (so a "Preview" click on a
 * published document with no open draft still works predictably).
 *
 * Rendering is via ``WorldGuideProse`` — the same component the
 * public World Guide page uses. Preview and published cannot drift.
 */


const SERIF_ITALIC: React.CSSProperties = {
  color: WG.inkMuted,
  fontFamily: 'Georgia, serif',
  fontStyle: 'italic',
}


export default function DraftPreviewPage() {
  const params = useParams()
  const id = String(params.id)
  const [doc, setDoc] = useState<DocumentDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(apiUrl(`/api/admin/world-guide/documents/${id}`), { credentials: 'include' })
      .then(async (r) => {
        if (!r.ok) throw new Error(`Load: ${r.status}`)
        return r.json() as Promise<DocumentDetail>
      })
      .then(setDoc)
      .catch((e: Error) => setError(e.message))
  }, [id])

  if (error) {
    return (
      <main style={{ background: WG.pageBg, minHeight: '100vh' }}>
        <div className="mx-auto max-w-[760px] px-6 py-16 text-[13px]" style={{ color: WG.danger }}>
          {error}
        </div>
      </main>
    )
  }
  if (!doc) {
    return (
      <main style={{ background: WG.pageBg, minHeight: '100vh' }}>
        <div className="mx-auto max-w-[760px] px-6 py-16 text-[13px]" style={{ color: WG.inkMuted }}>
          Loading preview…
        </div>
      </main>
    )
  }

  // Choose which version to render.
  const version = doc.current_draft ?? doc.current_published
  const isDraft = !!doc.current_draft

  return (
    <main style={{ background: WG.pageBg, minHeight: '100vh' }}>
      {/* Preview banner — always visible so a reader can never mistake
          a draft for the published document. */}
      <div
        className="sticky top-0 z-10 border-b"
        style={{
          background: isDraft ? WG.tealSoft : WG.navySoft,
          borderColor: isDraft ? `${WG.teal}22` : `${WG.navy}22`,
        }}
      >
        <div className="mx-auto flex max-w-[760px] flex-wrap items-center justify-between gap-3 px-6 py-2.5 text-[12.5px]">
          <div style={{ color: isDraft ? WG.teal : WG.navy }}>
            <strong>{isDraft ? 'Draft preview' : 'Published preview'}</strong>
            <span className="ml-2" style={{ color: WG.inkMuted }}>
              v{version?.version_number ?? '—'} · private, not visible to the public
            </span>
          </div>
          <Link
            href={`/admin/world-guide/documents/${id}`}
            className="rounded-full px-3 py-1 text-[12px]"
            style={{ background: '#FFFFFF', border: WG.divider, color: WG.ink }}
          >
            Back to editor
          </Link>
        </div>
      </div>

      <div className="mx-auto max-w-[760px] px-6 py-14 md:px-10 md:py-20">
        {/* Header — matches the public page layout so preview parity is real. */}
        <header className="mb-10">
          <div className="mb-4 h-px w-10" style={{ background: WG.teal }} />
          <div className="mb-2 flex flex-wrap items-center gap-3 text-[12.5px]" style={{ color: WG.inkSofter }}>
            <span>{CATEGORY_LABEL[doc.category] ?? doc.category}</span>
            <span>·</span>
            <span>For {AUDIENCE_LABEL[doc.audience] ?? doc.audience}</span>
          </div>
          <h1 className="font-serif text-[36px] leading-tight md:text-[48px]" style={{ color: WG.inkStrong }}>
            {doc.title}
          </h1>
          {doc.summary && (
            <p className="mt-4 text-[16px] leading-relaxed" style={SERIF_ITALIC}>
              {doc.summary}
            </p>
          )}
          <div className="mt-5 flex flex-wrap items-center gap-4 text-[12.5px]" style={{ color: WG.inkSofter }}>
            <span>Version {version?.version_number}</span>
            {version?.effective_date && <span>· Effective {formatDate(version.effective_date)}</span>}
            {doc.updated_at && <span>· Updated {formatDate(doc.updated_at)}</span>}
            {doc.reading_time_minutes && <span>· ~{doc.reading_time_minutes} min read</span>}
          </div>
        </header>

        <ContentSection title="Why this exists" content={version?.why_this_exists ?? null} />
        <ContentSection title="What this covers" content={version?.what_this_covers ?? null} />
        <ContentSection title="" content={version?.main_content ?? null} />
        <ContentSection title="What’s changed" content={version?.whats_changed ?? null} muted />
      </div>
    </main>
  )
}


function ContentSection({
  title, content, muted,
}: {
  title: string
  content: string | null
  muted?: boolean
}) {
  if (!content || !content.trim()) return null
  return (
    <section className="mt-10">
      {title && (
        <div className="mb-4">
          <h2 className="font-serif text-[24px] leading-tight" style={{ color: muted ? WG.inkMuted : WG.inkStrong }}>
            {title}
          </h2>
        </div>
      )}
      <WorldGuideProse content={content} />
    </section>
  )
}


function formatDate(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString('en-AU', { day: 'numeric', month: 'long', year: 'numeric' })
}
