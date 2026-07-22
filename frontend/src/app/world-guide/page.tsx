import Link from 'next/link'
import { apiUrl } from '@/lib/api'
import { CATEGORY_LABEL, WG, type PublicDocumentCard } from '@/lib/worldGuide'

/**
 * /world-guide — public landing.
 *
 * Explains what the World Guide is, then lists every published
 * governance document grouped by category. The design is
 * intentionally not corporate — parchment tones, serif headings,
 * generous spacing.
 */

export const dynamic = 'force-dynamic'


const SERIF_ITALIC: React.CSSProperties = {
  color: WG.inkMuted,
  fontFamily: 'Georgia, serif',
  fontStyle: 'italic',
}


async function loadDocuments(): Promise<PublicDocumentCard[]> {
  try {
    const res = await fetch(apiUrl('/api/world-guide'), { cache: 'no-store' })
    if (!res.ok) return []
    return await res.json()
  } catch {
    return []
  }
}


export default async function WorldGuideLandingPage() {
  const cards = await loadDocuments()
  const grouped: Record<string, PublicDocumentCard[]> = {}
  for (const c of cards) {
    if (!grouped[c.category]) grouped[c.category] = []
    grouped[c.category].push(c)
  }
  // Preferred display order — governance first, then members, creators, platform, other.
  const order = ['governance', 'members', 'creators', 'platform', 'other']
  const groups = order
    .filter((k) => grouped[k]?.length)
    .map((k) => [k, grouped[k]] as const)

  return (
    <main style={{ background: WG.pageBg, minHeight: '100vh' }}>
      <div className="mx-auto max-w-[960px] px-6 py-16 md:px-10 md:py-24">

        {/* Hero */}
        <header className="mb-16 text-center">
          <div
            className="mx-auto mb-4 h-px w-10"
            style={{ background: WG.teal }}
          />
          <h1
            className="font-serif text-[40px] leading-tight md:text-[56px]"
            style={{ color: WG.inkStrong }}
          >
            World Guide
          </h1>
          <p
            className="mx-auto mt-5 max-w-[640px] text-[16px] leading-relaxed md:text-[17px]"
            style={SERIF_ITALIC}
          >
            Everything you need to know about how Fresh Collective works. The World Guide
            explains the responsibilities of Members, Creators and the Platform Owner, along
            with the policies that help keep Fresh Collective welcoming, fair and trustworthy.
          </p>
        </header>

        {cards.length === 0 ? (
          <section
            className="rounded-2xl px-10 py-16 text-center"
            style={{ background: WG.cardBg, border: WG.divider, boxShadow: WG.cardShadow }}
          >
            <p className="mx-auto max-w-[520px] text-[15px] leading-relaxed" style={SERIF_ITALIC}>
              The World Guide is being written. Come back soon.
            </p>
          </section>
        ) : (
          <div className="space-y-14">
            {groups.map(([category, items]) => (
              <section key={category}>
                <div className="mb-6 flex items-baseline gap-3">
                  <h2
                    className="font-serif text-[24px] leading-tight md:text-[28px]"
                    style={{ color: WG.inkStrong }}
                  >
                    {CATEGORY_LABEL[category] ?? category}
                  </h2>
                  <div className="h-px flex-1" style={{ background: 'rgba(15,23,42,0.10)' }} />
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  {items.map((doc) => <DocCard key={doc.slug} doc={doc} />)}
                </div>
              </section>
            ))}
          </div>
        )}

      </div>
    </main>
  )
}


function DocCard({ doc }: { doc: PublicDocumentCard }) {
  return (
    <Link
      href={`/world-guide/${doc.slug}`}
      className="block rounded-2xl px-6 py-6 transition-shadow hover:shadow-md"
      style={{ background: WG.cardBg, border: WG.divider, boxShadow: WG.cardShadow }}
    >
      <h3 className="font-serif text-[20px] leading-tight" style={{ color: WG.inkStrong }}>
        {doc.title}
      </h3>
      {doc.summary && (
        <p className="mt-2 text-[14px] leading-relaxed" style={{ color: WG.inkMuted }}>
          {doc.summary}
        </p>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-3 text-[12px]" style={{ color: WG.inkSofter }}>
        <span>v{doc.version_number}</span>
        {doc.effective_date && <span>· Effective {formatDate(doc.effective_date)}</span>}
        {doc.reading_time_minutes && <span>· ~{doc.reading_time_minutes} min read</span>}
      </div>
    </Link>
  )
}


function formatDate(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString('en-AU', { day: 'numeric', month: 'long', year: 'numeric' })
}
