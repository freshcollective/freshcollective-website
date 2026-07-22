'use client'

import { useState, useTransition, useCallback } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import { AddBlockPicker } from '@/components/creator/BlockEditorShared'
import DraggableBlockList from '@/components/creator/DraggableBlockList'
import ReleaseRuleEditor, {
  type ReleaseRuleValue,
  releaseRuleFromStep,
  releaseRulePayload,
} from '@/components/creator/ReleaseRuleEditor'
import type { StepBlock, StepBlockType, CreatorMediaAsset, CreatorResource } from '@/types/platform'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CreatorPathwayMin { id: string; slug: string; title: string }
interface CreatorStepMin {
  id: string; slug: string; title: string; content_type: string
  content_body: string | null; estimated_minutes: number | null; is_required: boolean
  reflection_enabled: boolean; discussion_enabled: boolean
  banner_image_url?: string | null
  // Drip scheduling — populated by StepResponse. Legacy responses omit
  // these, so every field is optional; ReleaseRuleEditor defaults them.
  release_type?: string
  release_offset_days?: number | null
  release_at?: string | null
  release_timezone?: string | null
  release_previous_state?: string
}

interface Props {
  spaceSlug: string
  pathway: CreatorPathwayMin
  step: CreatorStepMin
  initialBlocks: StepBlock[]
  mediaAssets: CreatorMediaAsset[]
  resources?: CreatorResource[]
  backHref?: string
  backLabel?: string
}

// ---------------------------------------------------------------------------
// Main Editor
// ---------------------------------------------------------------------------

export default function StepBlockEditor({ spaceSlug, pathway, step, initialBlocks, mediaAssets, resources = [], backHref, backLabel }: Props) {
  const router = useRouter()
  const [, startTransition] = useTransition()
  const [blocks, setBlocks] = useState<StepBlock[]>(initialBlocks)
  const [assets, setAssets] = useState<CreatorMediaAsset[]>(mediaAssets)
  /** Single-active-editor: only one block is open for editing at a
   *  time. When a writer clicks another block, its autosave is
   *  already in-flight and the newly-clicked block replaces it as
   *  the active one. */
  const [activeBlockId, setActiveBlockId] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)
  const [newBlockId, setNewBlockId] = useState<string | null>(null)
  const [converting, setConverting] = useState(false)
  const [convertError, setConvertError] = useState<string | null>(null)
  const [deletingStep, setDeletingStep] = useState(false)
  const [deleteStepError, setDeleteStepError] = useState<string | null>(null)

  // Step settings
  const [stepTitle, setStepTitle] = useState(step.title)
  const [stepMinutes, setStepMinutes] = useState(step.estimated_minutes?.toString() ?? '')
  const [stepRequired, setStepRequired] = useState(step.is_required)
  const [reflectionEnabled, setReflectionEnabled] = useState(step.reflection_enabled)
  const [discussionEnabled, setDiscussionEnabled] = useState(step.discussion_enabled)
  const [releaseRule, setReleaseRule] = useState<ReleaseRuleValue>(() => releaseRuleFromStep(step))
  const [settingsSaving, setSettingsSaving] = useState(false)
  const [settingsSaved, setSettingsSaved] = useState(false)

  const stepUrl = apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}/steps/${step.slug}`)
  const blocksUrl = apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}/steps/${step.slug}/blocks`)

  const resolvedBackHref = backHref ?? `/creator-studio/pathways/${pathway.slug}`
  const resolvedBackLabel = backLabel ?? '← Back to pathway'

  async function saveStepSettings(e: React.FormEvent) {
    e.preventDefault()
    setSettingsSaving(true)
    setSettingsSaved(false)
    try {
      const res = await fetch(stepUrl, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          title: stepTitle.trim() || step.title,
          estimated_minutes: stepMinutes ? parseInt(stepMinutes) : null,
          is_required: stepRequired,
          reflection_enabled: reflectionEnabled,
          discussion_enabled: discussionEnabled,
          ...releaseRulePayload(releaseRule),
        }),
      })
      if (res.ok) {
        setSettingsSaved(true)
        startTransition(() => router.refresh())
      }
    } finally {
      setSettingsSaving(false)
    }
  }

  async function addBlock(type: StepBlockType) {
    return insertBlockAt(blocks.length, type)
  }

  /** Insert a block at a specific position. The backend shifts every
   *  block at or after that position up by one so the sequence stays
   *  gap-free without a follow-up reorder round-trip. */
  async function insertBlockAt(position: number, type: StepBlockType) {
    setAdding(true)
    setAddError(null)
    try {
      const res = await fetch(blocksUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ block_type: type, position }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        const detail = typeof body.detail === 'string' ? body.detail : null
        setAddError(detail ?? `Couldn't add ${type} block (${res.status}).`)
        return
      }
      const block: StepBlock = await res.json()
      setBlocks(prev => {
        const next = prev.slice()
        // Shift local positions to match what the backend just did.
        for (const b of next) if (b.position >= position) b.position = b.position + 1
        next.splice(position, 0, block)
        return next
      })
      setNewBlockId(block.id)
      setActiveBlockId(block.id)
    } catch {
      setAddError(`Couldn't add ${type} block. Please try again.`)
    } finally {
      setAdding(false)
    }
  }

  async function convertLegacy() {
    setConverting(true)
    setConvertError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}/steps/${step.slug}/convert-legacy`),
        { method: 'POST', credentials: 'include' },
      )
      if (!res.ok) {
        setConvertError('Conversion failed. Please try again.')
        return
      }
      const newBlocks: StepBlock[] = await res.json()
      setBlocks(newBlocks)
      startTransition(() => router.refresh())
    } catch {
      setConvertError('Conversion failed. Please try again.')
    } finally {
      setConverting(false)
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
    const updated: StepBlock = await res.json()
    setBlocks(prev => prev.map(b => b.id === blockId ? updated : b))
    if (newBlockId === blockId) setNewBlockId(null)
  }, [blocksUrl, newBlockId])

  async function deleteStep() {
    if (!confirm('Are you sure you want to delete this step? This cannot be undone.')) return
    setDeletingStep(true)
    setDeleteStepError(null)
    try {
      const res = await fetch(stepUrl, { method: 'DELETE', credentials: 'include' })
      if (res.ok) {
        router.push(resolvedBackHref)
      } else {
        setDeleteStepError('Failed to delete step. Please try again.')
      }
    } catch {
      setDeleteStepError('Failed to delete step. Please try again.')
    } finally {
      setDeletingStep(false)
    }
  }

  async function deleteBlock(blockId: string) {
    if (!confirm('Delete this block?')) return
    await fetch(`${blocksUrl}/${blockId}`, { method: 'DELETE', credentials: 'include' })
    setBlocks(prev => prev.filter(b => b.id !== blockId))
    if (newBlockId === blockId) setNewBlockId(null)
  }

  /** Apply the caller's new order optimistically and PATCH the reorder
   *  endpoint. Rolls back on failure. */
  async function reorderBlocks(nextIds: string[]) {
    const byId = new Map(blocks.map((b) => [b.id, b] as const))
    const next = nextIds.map((id, i) => {
      const b = byId.get(id)
      return b ? { ...b, position: i } : null
    }).filter(Boolean) as StepBlock[]
    if (next.length !== blocks.length) return
    const previous = blocks
    setBlocks(next)
    try {
      const res = await fetch(`${blocksUrl}/reorder`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ ids: nextIds }),
      })
      if (!res.ok) throw new Error(String(res.status))
      startTransition(() => router.refresh())
    } catch {
      setBlocks(previous)
    }
  }

  return (
    <div className="w-full px-8 py-8 md:px-10 md:py-10">

      {/* Breadcrumb / back */}
      <div className="mb-5">
        <Link href={resolvedBackHref} className="text-[12px] font-medium text-black transition-colors hover:text-slate-600">
          {resolvedBackLabel}
        </Link>
        <p className="mt-1 text-[11px] font-semibold uppercase tracking-[0.16em]" style={{ color: '#38A09E' }}>
          {pathway.title}
        </p>
        <h1 className="mt-0.5 text-2xl text-navy-900 md:text-3xl">{stepTitle || step.title}</h1>
      </div>

      {/* Step settings card */}
      <div className="mb-6 rounded-2xl border border-slate-200 bg-white p-6">
        <p className="mb-4 text-[11px] font-semibold uppercase tracking-[0.14em] text-black">Step settings</p>
        <form onSubmit={saveStepSettings} className="flex flex-col gap-5">
          <div>
            <label className="field-label">Step title</label>
            <input
              value={stepTitle}
              onChange={e => setStepTitle(e.target.value)}
              required
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 focus:outline-none focus:ring-1 focus:ring-teal-300"
            />
          </div>
          <div className="flex flex-wrap items-end gap-6">
            <div>
              <label className="field-label">Estimated minutes</label>
              <input
                type="number" min={1} max={999}
                value={stepMinutes}
                onChange={e => setStepMinutes(e.target.value)}
                placeholder="—"
                className="w-24 rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 focus:outline-none focus:ring-1 focus:ring-teal-300"
              />
            </div>
            <div className="flex items-center gap-3 pb-0.5">
              <button
                type="button"
                role="switch"
                aria-checked={stepRequired}
                onClick={() => setStepRequired(r => !r)}
                className={`relative h-5 w-9 rounded-full transition-colors ${stepRequired ? 'bg-teal-500' : 'bg-slate-200'}`}
              >
                <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${stepRequired ? 'translate-x-4' : 'translate-x-0.5'}`} />
              </button>
              <span className="text-[13px] text-black">Required</span>
            </div>
          </div>

          {/* Member feature toggles */}
          <div className="space-y-3 rounded-xl border border-slate-100 bg-slate-50 p-4">
            <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-black">Member features</p>
            <div className="flex items-start gap-3">
              <button
                type="button"
                role="switch"
                aria-checked={reflectionEnabled}
                onClick={() => setReflectionEnabled(v => !v)}
                className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors ${reflectionEnabled ? 'bg-teal-500' : 'bg-slate-200'}`}
              >
                <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${reflectionEnabled ? 'translate-x-4' : 'translate-x-0.5'}`} />
              </button>
              <div>
                <p className="text-[13px] font-medium text-navy-900">Enable member reflection</p>
                <p className="text-[12px] text-black">Allow members to write private reflections on this step.</p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <button
                type="button"
                role="switch"
                aria-checked={discussionEnabled}
                onClick={() => setDiscussionEnabled(v => !v)}
                className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors ${discussionEnabled ? 'bg-teal-500' : 'bg-slate-200'}`}
              >
                <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${discussionEnabled ? 'translate-x-4' : 'translate-x-0.5'}`} />
              </button>
              <div>
                <p className="text-[13px] font-medium text-navy-900">Enable discussion</p>
                <p className="text-[12px] text-black">Allow members to ask questions and discuss this step.</p>
              </div>
            </div>
          </div>

          {/* Release rule — when this step becomes available to members. */}
          <ReleaseRuleEditor value={releaseRule} onChange={setReleaseRule} />

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={settingsSaving}
              className="rounded-lg px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
              style={{ background: '#073B3A' }}
            >
              {settingsSaving ? 'Saving…' : 'Save settings'}
            </button>
            {settingsSaved && <span className="text-[12px] text-teal-600">Saved ✓</span>}
          </div>
        </form>
      </div>

      {/* Content — one continuous white document canvas. No admin
          card wrapper; the blocks flow inside it as document content. */}
      <div className="rounded-2xl border border-slate-200 bg-white px-4 py-6 md:px-10 md:py-8">
        <p className="mb-4 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">Content</p>

        <div>
          {blocks.length === 0 && step.content_body && (
            <div
              className="rounded-xl border p-5"
              style={{ borderColor: 'rgba(234,179,8,0.35)', background: 'rgba(254,252,232,0.6)' }}
            >
              <p className="mb-1 text-[14px] font-semibold text-amber-800">Legacy content found</p>
              <p className="mb-3 text-[13px] text-amber-700">
                This step has existing content that was created before the block editor. Convert it into an
                editable block so it appears here and members continue to see the same content.
              </p>
              {convertError && <p className="mb-2 text-[12px] text-red-600">{convertError}</p>}
              <button
                type="button"
                disabled={converting}
                onClick={convertLegacy}
                className="rounded-lg px-4 py-1.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
                style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
              >
                {converting ? 'Converting…' : 'Convert to blocks'}
              </button>
            </div>
          )}

          {blocks.length === 0 && !step.content_body && (
            <div className="rounded-xl border border-dashed border-slate-200 bg-white p-8 text-center">
              <p className="mb-1 text-[15px] font-semibold text-navy-900">No content blocks yet</p>
              <p className="text-[13px] text-black">
                Start building this step by adding your first content block below.
              </p>
            </div>
          )}

          {blocks.length > 0 && (
            <DraggableBlockList
              blocks={blocks}
              assets={assets}
              resources={resources}
              activeBlockId={activeBlockId}
              onActivateBlock={setActiveBlockId}
              onUpdate={updateBlock}
              onDelete={deleteBlock}
              onReorder={reorderBlocks}
              onInsertAt={insertBlockAt}
              spaceSlug={spaceSlug}
              onAssetUploaded={(asset) => setAssets((prev) => [asset, ...prev])}
            />
          )}
        </div>

        {blocks.length === 0 && (
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
        )}
      </div>

      {/* Danger zone */}
      <div className="mt-6 rounded-2xl border border-red-100 bg-white p-5">
        <p className="mb-1 text-[12px] font-semibold uppercase tracking-[0.12em] text-red-400">Danger zone</p>
        <p className="mb-4 text-[13px] text-black">
          Permanently delete this step and all its content blocks. This cannot be undone.
        </p>
        {deleteStepError && (
          <p className="mb-3 text-[13px] text-red-600">{deleteStepError}</p>
        )}
        <button
          type="button"
          onClick={deleteStep}
          disabled={deletingStep}
          className="rounded-lg border border-red-200 px-4 py-2 text-[13px] font-medium text-red-500 transition-colors hover:border-red-400 hover:bg-red-50 disabled:opacity-40"
        >
          {deletingStep ? 'Deleting…' : 'Delete this step'}
        </button>
      </div>

    </div>
  )
}
