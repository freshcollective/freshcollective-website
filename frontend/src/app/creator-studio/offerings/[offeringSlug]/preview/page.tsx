import { notFound, redirect } from 'next/navigation'
import { getActiveCreatorSpace, getCreatorOffering } from '@/lib/serverApi'

interface Props {
  params: Promise<{ offeringSlug: string }>
}

/**
 * Preview entry point for an Offering.
 *
 * Identical in approach to the Pathway preview: confirm the caller
 * manages the active Collective, then **redirect into the real member
 * URL**. There is deliberately no preview-only renderer.
 *
 * That matters more here than anywhere else in Creator Studio. A
 * creator is about to put a product on sale, and the thing they approve
 * has to be the thing a buyer sees — not a near-copy that drifts. The
 * member route already permits managers to read a draft Offering (and
 * a draft Collective) via ``_get_space_visible_to``, while a public
 * visitor hitting the same URL gets a 404.
 */
export default async function OfferingPreviewPage({ params }: Props) {
  const { offeringSlug } = await params
  const activeSpace = await getActiveCreatorSpace()
  if (!activeSpace) notFound()

  const offering = await getCreatorOffering(activeSpace.slug, offeringSlug)
  if (!offering) notFound()

  redirect(`/spaces/${activeSpace.slug}/offerings/${offering.slug}`)
}
