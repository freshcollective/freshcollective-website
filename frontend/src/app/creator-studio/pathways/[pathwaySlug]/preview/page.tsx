import { notFound, redirect } from 'next/navigation'
import { getActiveCreatorSpace, getCreatorPathway } from '@/lib/serverApi'

interface Props {
  params: Promise<{ pathwaySlug: string }>
}

/**
 * Preview entry point for a pathway.
 *
 * Verifies the current user manages the active creator collective (the
 * ``/api/creator/*`` endpoints already enforce owner/creator/moderator
 * access), then redirects into the public pathway URL. The public route
 * permits managers to see non-active collectives via ``_get_space_visible_to``
 * on the backend, so an owner previewing a Draft collective's pathway sees
 * the full member view. Public visitors hitting the same URL still 404.
 */
export default async function PathwayPreviewPage({ params }: Props) {
  const { pathwaySlug } = await params
  const activeSpace = await getActiveCreatorSpace()
  if (!activeSpace) notFound()

  const pathway = await getCreatorPathway(activeSpace.slug, pathwaySlug)
  if (!pathway) notFound()

  redirect(`/spaces/${activeSpace.slug}/pathways/${pathway.slug}`)
}
