'use client'

import { InsightsShell } from '@/components/admin/insights/InsightsShell'

/**
 * Participation — not built yet, and saying so.
 *
 * The tab exists because the six sections were agreed together and a
 * missing tab reads as a broken link. An empty page that explains what
 * is coming is more honest than a page of zeroes that looks like an
 * answer.
 */
export default function ParticipationPage() {
  return (
    <InsightsShell
      title="Participation"
      intro="What people are actually doing, not just whether they joined."
    >
      <div
        className="rounded-2xl p-6"
        style={{ background: '#FFFFFF', border: '1px solid #E7EEF0' }}
      >
        <p className="text-[13.5px]" style={{ color: 'rgba(12, 24, 38, 0.78)' }}>
          This section is still being built. It will cover: Active members and creators, Conversations, Gathering attendance against bookings, and Pathway progress.
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
