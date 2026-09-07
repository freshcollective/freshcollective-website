import { notFound } from 'next/navigation'
import { headers } from 'next/headers'
import { resolveInternalApiBase } from '@/lib/api'
import CreatorBackLink from '@/components/creator/CreatorBackLink'
import AttendanceDashboardClient from './AttendanceDashboardClient'
import type { AttendanceDashboard } from './types'

/**
 * Creator Studio → Gathering → Attendance dashboard.
 *
 * Server component: fetches the dashboard payload via the server-side
 * BFF using the session cookie forwarded by the App Router. One
 * network hop into fc-api; the client component runs entirely against
 * ``/api/creator/…`` via the same-origin BFF proxy for mutations.
 *
 * Fresh data guarantee: the fetch is ``cache: 'no-store'`` so the
 * dashboard always renders authoritative counts.
 */

export const dynamic = 'force-dynamic'
export const revalidate = 0

async function fetchDashboard(
  slug: string, eventId: string,
): Promise<AttendanceDashboard | null> {
  const base = resolveInternalApiBase()
  const cookieHeader = (await headers()).get('cookie') ?? ''
  const url = `${base}/api/creator/spaces/${encodeURIComponent(slug)}/events/${encodeURIComponent(eventId)}/attendance`
  const res = await fetch(url, {
    cache: 'no-store',
    headers: { cookie: cookieHeader },
  })
  if (res.status === 404 || res.status === 403) return null
  if (!res.ok) throw new Error(`attendance fetch failed: ${res.status}`)
  return res.json()
}

export default async function AttendanceDashboardPage({
  params,
}: {
  params: Promise<{ slug: string; eventId: string }>
}) {
  const { slug, eventId } = await params
  const dashboard = await fetchDashboard(slug, eventId)
  if (!dashboard) notFound()

  return (
    <div className="mx-auto w-full max-w-[1180px] px-6 py-8 md:px-10 md:py-10">
      <CreatorBackLink
        href={`/creator/spaces/${slug}/events/${eventId}`}
        label="Back to Gathering"
      />
      <AttendanceDashboardClient
        spaceSlug={slug}
        eventId={eventId}
        initial={dashboard}
      />
    </div>
  )
}
