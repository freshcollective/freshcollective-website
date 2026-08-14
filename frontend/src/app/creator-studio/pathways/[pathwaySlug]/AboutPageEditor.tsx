'use client'

import { useState, useTransition, useCallback } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import { AddBlockPicker, BlockRow } from '@/components/creator/BlockEditorShared'
import type { PathwayAboutBlock, StepBlockType, CreatorMediaAsset, CreatorResource } from '@/types/platform'

interface CreatorPathwayMin {
  id: string
  slug: string
  title: string
}

interface Props {
  spaceSlug: string
  pathway?: CreatorPathwayMin
  initialBlocks: PathwayAboutBlock[]
  mediaAssets: CreatorMediaAsset[]
  resources?: CreatorResource[]
  /** Override the About-blocks endpoint base. Defaults to the
   *  Pathway endpoint for backwards compatibility. Series callers
   *  pass their own base URL to write against
   *  ``/gathering-series/{slug}/about-blocks`` — the same block
   *  primitives (``BlockRow``, ``AddBlockPicker``) are reused
   *  transparently because they only work with the block payload,
   *  not the URL. */
  blocksApiUrl?: string
  /** Override the "Preview member view" link target. Optional. */
  previewHref?: string
  /** Section heading + subheading — overridable so a Series
   *  caller can label it "Series About" without the "pathway"
   *  wording. */
  headingTitle?: string
  headingBody?: string
  /** Empty-state copy — overridable so a Series doesn't say
   *  "this pathway" when it has no blocks. */
  emptyStateHeading?: string
  emptyStateBody?: string
}

export default function AboutPageEditor({
  spaceSlug, pathway, initialBlocks, mediaAssets, resources = [],
  blocksApiUrl, previewHref, headingTitle, headingBody,
  emptyStateHeading, emptyStateBody,
}: Props) {
  const router = useRouter()
  const [, startTransition] = useTransition()
  const [blocks, setBlocks] = useState<PathwayAboutBlock[]>(initialBlocks)
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)
  const [newBlockId, setNewBlockId] = useState<string | null>(null)

  const blocksUrl = blocksApiUrl ?? apiUrl(
    `/api/creator/spaces/${spaceSlug}/pathways/${pathway!.slug}/about-blocks`,
  )
  const memberPreviewHref = previewHref ?? (pathway
    ? `/spaces/${spaceSlug}/pathways/${pathway.slug}/about`
    : null
  )

  async function addBlock(type: StepBlockType) {
    setAdding(true)
    setAddError(null)
    try {
      const res = await fetch(blocksUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ block_type: type }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        const detail = typeof body.detail === 'string' ? body.detail : null
        setAddError(detail ?? `Couldn't add ${type} block (${res.status}).`)
        return
      }
      const block: PathwayAboutBlock = await res.json()
      setBlocks(prev => [...prev, block])
      setNewBlockId(block.id)
    } catch {
      setAddError(`Couldn't add ${type} block. Please try again.`)
    } finally {
      setAdding(false)
    }
  }

  const updateBlock = useCallback(async (blockId: string, patch: Record<string, unknown>) => {
    const res = await fetch(`${blocksUrl}/${blockId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(patch),
    })
    if (!res.ok) return
    const updated: PathwayAboutBlock = await res.json()
    setBlocks(prev => prev.map(b => b.id === blockId ? updated : b))
    if (newBlockId === blockId) setNewBlockId(null)
  }, [blocksUrl, newBlockId])

  async function deleteBlock(blockId: string) {
    if (!confirm('Delete this block?')) return
    await fetch(`${blocksUrl}/${blockId}`, { method: 'DELETE', credentials: 'include' })
    setBlocks(prev => prev.filter(b => b.id !== blockId))
    if (newBlockId === blockId) setNewBlockId(null)
  }

  async function moveBlock(index: number, direction: 'up' | 'down') {
    const newBlocks = [...blocks]
    const swapIdx = direction === 'up' ? index - 1 : index + 1
    if (swapIdx < 0 || swapIdx >= newBlocks.length) return
    ;[newBlocks[index], newBlocks[swapIdx]] = [newBlocks[swapIdx], newBlocks[index]]
    setBlocks(newBlocks)
    await fetch(`${blocksUrl}/reorder`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ ids: newBlocks.map(b => b.id) }),
    })
    startTransition(() => router.refresh())
  }

  return (
    <div>

      {/* Section heading — the shared PathwayHeader above already carries
          the back link, pathway title, and tab bar. */}
      <div className="mb-6">
        <h2 className="text-[18px] font-semibold text-navy-900">
          {headingTitle ?? 'Edit about page'}
        </h2>
        <p className="mt-1 text-[14px] text-black">
          {headingBody ?? 'Build the page people see before they start or unlock this pathway.'}
        </p>
      </div>

      {/* Member preview link (when a preview target exists) */}
      {memberPreviewHref && (
        <div className="mb-6">
          <Link
            href={memberPreviewHref}
            target="_blank"
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-[12px] font-medium text-black transition-colors hover:border-teal-200 hover:text-teal-700"
          >
            Preview member view →
          </Link>
        </div>
      )}

      {/* Content blocks card */}
      <div className="rounded-2xl border border-slate-200 bg-slate-50 p-6">
        <p className="mb-4 text-[11px] font-semibold uppercase tracking-[0.14em] text-black">
          About page content
        </p>

        <div className="space-y-3">
          {blocks.length === 0 && (
            <div className="rounded-xl border border-dashed border-slate-200 bg-white p-8 text-center">
              <p className="mb-1 text-[15px] font-semibold text-navy-900">
                {emptyStateHeading ?? 'No about page content yet'}
              </p>
              <p className="text-[13px] text-black">
                {emptyStateBody ?? 'Add your first block to explain what this pathway is about, who it is for, and what people will experience.'}
              </p>
            </div>
          )}

          {blocks.map((block, i) => (
            <BlockRow
              key={block.id}
              block={block}
              index={i}
              total={blocks.length}
              assets={mediaAssets}
              resources={resources}
              initialEditing={block.id === newBlockId}
              onMoveUp={() => moveBlock(i, 'up')}
              onMoveDown={() => moveBlock(i, 'down')}
              onDelete={() => deleteBlock(block.id)}
              onUpdate={(patch) => updateBlock(block.id, patch)}
            />
          ))}
        </div>

        <div className="mt-4">
          {adding ? (
            <p className="text-[13px] text-black">Adding block…</p>
          ) : (
            <AddBlockPicker onSelect={addBlock} />
          )}
          {addError && (
            <p className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-700">
              {addError}
            </p>
          )}
        </div>
      </div>

    </div>
  )
}
