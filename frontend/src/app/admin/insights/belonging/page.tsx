'use client'

import { InsightsShell } from '@/components/admin/insights/InsightsShell'

/**
 * Belonging — not built yet, and saying so.
 *
 * The tab exists because the six sections were agreed together and a
 * missing tab reads as a broken link. An empty page that explains what
 * is coming is more honest than a page of zeroes that looks like an
 * answer.
 */
export default function BelongingPage() {
  return (
    <InsightsShell
      title="Belonging"
      intro="Who stays, who comes back, and how long people remain."
    >
      <div
        className="rounded-2xl p-6"
        style={{ background: '#FFFFFF', border: '1px solid #E7EEF0' }}
      >
        <p className="text-[13.5px]" style={{ color: 'rgba(12, 24, 38, 0.78)' }}>
          This section is still being built. It will cover: Retention cohorts, returning participation, and the relationship between belonging to several Collectives and taking part.
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
