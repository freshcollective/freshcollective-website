import Link from 'next/link'
import { notFound } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import WorldGuideProse from '@/components/world-guide/WorldGuideProse'
import {
  AUDIENCE_LABEL,
  CATEGORY_LABEL,
  WG,
  type PublicDocumentDetail,
} from '@/lib/worldGuide'

/**
 * /world-guide/[slug] — public document page.
 *
 * Uses the same WorldGuideProse component as the editor preview so
 * the reader sees exactly what the author saw while writing.
 */

export const dynamic = 'force-dynamic'


const SERIF_ITALIC: React.CSSProperties = {
  color: WG.inkMuted,
  fontFamily: 'Georgia, serif',
  fontStyle: 'italic',
}


interface Props {
  params: Promise<{ slug: string }>
}


async function loadDocument(slug: string): Promise<PublicDocumentDetail | null> {
  try {
    const res = await fetch(apiUrl(`/api/world-guide/${slug}`), { cache: 'no-store' })
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}


export default async function WorldGuideDocumentPage({ params }: Props) {
  const { slug } = await params
  const doc = await loadDocument(slug)
  if (!doc) notFound()

  return (
    <main style={{ background: WG.pageBg, minHeight: '100vh' }}>
      <div className="mx-auto max-w-[760px] px-6 py-16 md:px-10 md:py-24">

        {/* Breadcrumb */}
        <Link href="/world-guide" className="text-[13px]" style={{ color: WG.inkMuted }}>
          ← World Guide
        </Link>

        {/* Header */}
        <header className="mt-4 mb-10">
          <div
            className="mb-4 h-px w-10"
            style={{ background: WG.teal }}
          />
          <div className="mb-2 flex flex-wrap items-center gap-3 text-[12.5px]" style={{ color: WG.inkSofter }}>
            <span>{CATEGORY_LABEL[doc.category] ?? doc.category}</span>
            <span>·</span>
            <span>For {AUDIENCE_LABEL[doc.audience] ?? doc.audience}</span>
          </div>
          <h1
            className="font-serif text-[36px] leading-tight md:text-[48px]"
            style={{ color: WG.inkStrong }}
          >
            {doc.title}
          </h1>
          {doc.summary && (
            <p className="mt-4 text-[16px] leading-relaxed" style={SERIF_ITALIC}>
              {doc.summary}
            </p>
          )}
          <div className="mt-5 flex flex-wrap items-center gap-4 text-[12.5px]" style={{ color: WG.inkSofter }}>
            <span>Version {doc.version_number}</span>
            {doc.effective_date && <span>· Effective {formatDate(doc.effective_date)}</span>}
            {doc.updated_at && <span>· Updated {formatDate(doc.updated_at)}</span>}
            {doc.reading_time_minutes && <span>· ~{doc.reading_time_minutes} min read</span>}
          </div>
        </header>

        {/* Sections */}
        <ContentSection title="Why this exists" content={doc.why_this_exists} />
        <ContentSection title="What this covers" content={doc.what_this_covers} />
        <ContentSection title="" content={doc.main_content} />
        <ContentSection title="What’s changed" content={doc.whats_changed} muted />

        {/* Related */}
        {doc.related.length > 0 && (
          <section className="mt-16">
            <div className="mb-6 flex items-baseline gap-3">
              <h2 className="font-serif text-[22px] leading-tight" style={{ color: WG.inkStrong }}>
                Related documents
              </h2>
              <div className="h-px flex-1" style={{ background: 'rgba(15,23,42,0.10)' }} />
            </div>
            <ul className="space-y-2">
              {doc.related.map((r) => (
                <li key={r.slug}>
                  <Link
                    href={`/world-guide/${r.slug}`}
                    className="inline-block text-[14px] font-medium hover:underline"
                    style={{ color: WG.teal }}
                  >
                    → {r.title}
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}
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
          <h2
            className="font-serif text-[24px] leading-tight"
            style={{ color: muted ? WG.inkMuted : WG.inkStrong }}
          >
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
