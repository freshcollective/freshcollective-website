import { notFound } from 'next/navigation'

import GuideEditor, { type GuideDetail } from './GuideEditor'
import { serverFetch } from '@/lib/serverApi'

/**
 * /admin/guides/[id] — the editor shell.
 *
 * Loaded server-side so the form opens populated rather than empty
 * and then filling in. The admin layout already enforces the
 * administrator check for the whole section; the API enforces it
 * again on every call, which is the one that matters.
 */

export const dynamic = 'force-dynamic'

export default async function AdminGuidePage(
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params
  const res = await serverFetch(`/api/admin/guides/${id}`)
  if (!res.ok) notFound()
  const guide = (await res.json()) as GuideDetail
  return <GuideEditor initial={guide} />
}
