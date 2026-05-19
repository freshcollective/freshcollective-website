'use client'

import { useState, useTransition, useCallback } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import { AddBlockPicker, BlockRow } from '@/components/creator/BlockEditorShared'
import type { PathwayAboutBlock, StepBlockType, CreatorMediaAsset } from '@/types/platform'

interface CreatorPathwayMin {
  id: string
  slug: string
  title: string
}

interface Props {
  spaceSlug: string
  pathway: CreatorPathwayMin
  initialBlocks: PathwayAboutBlock[]
  mediaAssets: CreatorMediaAsset[]
}

export default function AboutPageEditor({ spaceSlug, pathway, initialBlocks, mediaAssets }: Props) {
  const router = useRouter()
  const [, startTransition] = useTransition()
  const [blocks, setBlocks] = useState<PathwayAboutBlock[]>(initialBlocks)
  const [adding, setAdding] = useState(false)
  const [newBlockId, setNewBlockId] = useState<string | null>(null)

  const blocksUrl = apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}/about-blocks`)

  async function addBlock(type: StepBlockType) {
    setAdding(true)
    try {
      const res = await fetch(blocksUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ block_type: type }),
      })
      if (!res.ok) return
      const block: PathwayAboutBlock = await res.json()
      setBlocks(prev => [...prev, block])
      setNewBlockId(block.id)
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
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">

      {/* Breadcrumb */}
      <div className="mb-6">
        <Link
          href={`/creator-studio/pathways/${pathway.slug}`}
          className="text-[12px] font-medium text-slate-400 transition-colors hover:text-slate-600"
        >
          ← Back to pathway
        </Link>
        <p className="mt-1 text-[11px] font-semibold uppercase tracking-[0.16em]" style={{ color: '#38A09E' }}>
          {pathway.title}
        </p>
        <h1 className="mt-0.5 text-2xl text-navy-900 md:text-3xl">Edit about page</h1>
        <p className="mt-1.5 text-[14px] text-slate-500">
          Build the page people see before they start or unlock this pathway.
        </p>
      </div>

      {/* Member preview link */}
      <div className="mb-6">
        <Link
          href={`/spaces/${spaceSlug}/pathways/${pathway.slug}/about`}
          target="_blank"
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-[12px] font-medium text-slate-600 transition-colors hover:border-teal-200 hover:text-teal-700"
        >
          Preview member view →
        </Link>
      </div>

      {/* Content blocks card */}
      <div className="rounded-2xl border border-slate-200 bg-slate-50 p-6">
        <p className="mb-4 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
          About page content
        </p>

        <div className="space-y-3">
          {blocks.length === 0 && (
            <div className="rounded-xl border border-dashed border-slate-200 bg-white p-8 text-center">
              <p className="mb-1 text-[15px] font-semibold text-navy-900">No about page content yet</p>
              <p className="text-[13px] text-slate-400">
                Add your first block to explain what this pathway is about, who it is for, and what people will experience.
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
            <p className="text-[13px] text-slate-400">Adding block…</p>
          ) : (
            <AddBlockPicker onSelect={addBlock} />
          )}
        </div>
      </div>

    </div>
  )
}
