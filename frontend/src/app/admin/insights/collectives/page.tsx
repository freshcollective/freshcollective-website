'use client'

import { InsightsShell } from '@/components/admin/insights/InsightsShell'

/**
 * Collectives — not built yet, and saying so.
 *
 * The tab exists because the six sections were agreed together and a
 * missing tab reads as a broken link. An empty page that explains what
 * is coming is more honest than a page of zeroes that looks like an
 * answer.
 */
export default function CollectivesPage() {
  return (
    <InsightsShell
      title="Collectives"
      intro="How each community is faring, and which themes are finding people."
    >
      <div
        className="rounded-2xl p-6"
        style={{ background: '#FFFFFF', border: '1px solid #E7EEF0' }}
      >
        <p className="text-[13.5px]" style={{ color: 'rgba(12, 24, 38, 0.78)' }}>
          This section is still being built. It will cover: Side-by-side comparisons, theme popularity, size and growth bands, and Collectives that have gone quiet.
        </p>
        <p
          className="mt-2 text-[12.5px]"
          style={{
            color: 'rgba(12, 24, 38, 0.60)',
            fontFamily: 'Georgia, serif',
            fontStyle: 'italic',
          }}
        >
          The figures behind it already exist — only the page is missing.
        </p>
      </div>
    </InsightsShell>
  )
}
