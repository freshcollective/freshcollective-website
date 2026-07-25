import { notFound } from 'next/navigation'
import {
  getActiveCreatorSpace,
  getCreatorPathway,
  getCreatorSteps,
  serverFetch,
} from '@/lib/serverApi'
import type { CreatorPathway, CreatorStep, SpaceSummary } from '@/types/platform'
import CreatorPageContainer from '@/components/creator/CreatorPageContainer'
import ManualReleasesClient from './ManualReleasesClient'
import PathwayHeader from '../PathwayHeader'

/**
 * Manual releases page — one small caretaker workflow tool.
 *
 * Lists every step in the pathway whose release rule is `manual` and,
 * for each, the members currently waiting to be released. Deliberately
 * minimal: no analytics, no time-since-enrolment scoreboard.
 */

interface Props {
  params: Promise<{ pathwaySlug: string }>
}

interface ManualStepEntry {
  step_id: string
  step_slug: string
  step_title: string
  pathway_slug: string
  pathway_title: string
  waiting: { user_id: string; display_name: string; email: string | null }[]
}

export default async function ManualReleasesPage({ params }: Props) {
  const { pathwaySlug } = await params
  const space: SpaceSummary | null = await getActiveCreatorSpace()
  if (!space) {
    return (
      <CreatorPageContainer>
        <p className="text-[14px] text-black">
          Select a collective to view manual releases.
        </p>
      </CreatorPageContainer>
    )
  }

  const [pathway, steps, releasesRes]: [
    CreatorPathway | null, CreatorStep[], Response,
  ] = await Promise.all([
    getCreatorPathway(space.slug, pathwaySlug),
    getCreatorSteps(space.slug, pathwaySlug),
    serverFetch(`/api/creator/spaces/${space.slug}/pathways/${pathwaySlug}/manual-releases`),
  ])

  if (!pathway) notFound()

  const entries: ManualStepEntry[] = releasesRes.ok ? await releasesRes.json() : []
  const hasManualStep = steps.some((s) => s.release_type === 'manual')

  return (
    <CreatorPageContainer>
      <PathwayHeader
        active="manual-releases"
        spaceSlug={space.slug}
        spaceName={space.name}
        pathway={pathway}
        showManualReleases={hasManualStep}
      />

      <div className="mb-6">
        <h2 className="text-[18px] font-semibold text-navy-900">Manual releases</h2>
        <p className="mt-1 text-[14px] leading-relaxed text-black">
          Members waiting to be released into the next step. Only steps with a manual
          release rule appear here.
        </p>
      </div>

      {entries.length === 0 ? (
        <div
          className="rounded-2xl bg-white px-6 py-8 text-center"
          style={{ border: '1px dashed rgba(12,24,38,0.14)' }}
        >
          <p className="font-serif text-lg text-navy-800">
            No steps in this pathway use manual release.
          </p>
          <p className="mx-auto mt-1 max-w-md text-[13px] leading-relaxed text-black">
            Edit any step and change its release rule to &ldquo;Manual release&rdquo; to see waiting members here.
          </p>
        </div>
      ) : (
        <ManualReleasesClient spaceSlug={space.slug} initialEntries={entries} />
      )}
    </CreatorPageContainer>
  )
}
