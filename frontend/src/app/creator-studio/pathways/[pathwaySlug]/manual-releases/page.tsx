import Link from 'next/link'
import { getActiveCreatorSpace, serverFetch } from '@/lib/serverApi'
import ManualReleasesClient from './ManualReleasesClient'
import type { SpaceSummary } from '@/types/platform'

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
      <div className="w-full max-w-[860px] px-8 py-8 md:px-10 md:py-10">
        <p className="text-[14px] text-black">
          Select a collective to view manual releases.
        </p>
      </div>
    )
  }

  const res = await serverFetch(
    `/api/creator/spaces/${space.slug}/pathways/${pathwaySlug}/manual-releases`,
  )
  const entries: ManualStepEntry[] = res.ok ? await res.json() : []

  return (
    <div className="w-full max-w-[860px] px-8 py-8 md:px-10 md:py-10">
      <div className="mb-6">
        <Link
          href={`/creator-studio/pathways/${pathwaySlug}`}
          className="text-[12px] font-medium text-black hover:text-slate-600"
        >
          ← Back to pathway
        </Link>
        <p
          className="mt-1 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}
        >
          Care
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Manual releases</h1>
        <p className="mt-2 text-[14px] leading-relaxed text-black">
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
    </div>
  )
}
