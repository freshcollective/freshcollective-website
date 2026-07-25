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
  /** Zero-based ordinal of this step within the pathway. Used only for
   *  the "Step N of N" breadcrumb line; ``null`` hides the line. */
  stepIndex?: number | null
  totalSteps?: number
}

// ---------------------------------------------------------------------------
// Small local: section label used consistently in this editor
// ---------------------------------------------------------------------------

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p
      className="text-[11px] font-semibold uppercase tracking-[0.16em]"
      style={{ color: '#0f766e' }}
    >
      {children}
    </p>
  )
}

// ---------------------------------------------------------------------------
// Main Editor
// ---------------------------------------------------------------------------

export default function StepBlockEditor({
  spaceSlug, pathway, step, initialBlocks, mediaAssets, resources = [],
  backHref, backLabel, stepIndex = null, totalSteps = 0,
}: Props) {
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

      {/* ── Page context ── */}
      <div className="mb-8">
        <Link
          href={resolvedBackHref}
          className="text-[12px] font-medium text-black transition-colors hover:text-slate-600"
        >
          {resolvedBackLabel}
        </Link>
        <p
          className="mt-2 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}
        >
          {pathway.title}
        </p>
        {stepIndex !== null && totalSteps > 0 && (
          <p
            className="mt-0.5 text-[12px] italic"
            style={{ color: 'rgba(12,24,38,0.62)', fontFamily: 'Georgia, serif' }}
          >
            Step {stepIndex + 1} of {totalSteps}
          </p>
        )}
        <h1 className="mt-1.5 font-serif text-2xl text-navy-900 md:text-3xl">
          {stepTitle || step.title}
        </h1>
      </div>

      {/* ────────────────────────────────────────────────────────────
          Settings — Step / Member experience / Release
          These three sections carry the same visual language and a
          single Save changes action. Content, below, is the primary
          focus of the page and lives in its own document canvas.
          ──────────────────────────────────────────────────────────── */}
      <form onSubmit={saveStepSettings} className="space-y-6">

        {/* ── SECTION 1 — Step ── */}
        <section className="rounded-2xl border border-slate-100 bg-white p-6 md:p-7">
          <div className="mb-5">
            <SectionLabel>Step</SectionLabel>
          </div>
          <div className="space-y-5">
            <div>
              <label className="mb-1 block text-[12px] font-semibold text-black" htmlFor="step-title">
                Step title
              </label>
              <input
                id="step-title"
                value={stepTitle}
                onChange={e => setStepTitle(e.target.value)}
                required
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
              />
            </div>
            <div className="flex flex-wrap items-end gap-6">
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-black" htmlFor="step-minutes">
                  Estimated reading time
                </label>
                <div className="flex items-center gap-2">
                  <input
                    id="step-minutes"
                    type="number" min={1} max={999}
                    value={stepMinutes}
                    onChange={e => setStepMinutes(e.target.value)}
                    placeholder="—"
                    className="w-24 rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
                  />
                  <span className="text-[13px] text-black">minutes</span>
                </div>
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
                <span className="text-[13px] text-navy-900">Required step</span>
              </div>
            </div>
          </div>
        </section>

        {/* ── SECTION 2 — Members ── */}
        <section className="rounded-2xl border border-slate-100 bg-white p-6 md:p-7">
          <div className="mb-5">
            <SectionLabel>Members</SectionLabel>
          </div>

          <div className="space-y-5">
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
                <p className="text-[14px] font-semibold text-navy-900">Private reflection</p>
                <p className="mt-0.5 text-[13px] leading-relaxed text-black">
                  Members can keep private notes as they work through this step.
                </p>
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
                <p className="text-[14px] font-semibold text-navy-900">Continue the conversation</p>
                <p className="mt-0.5 text-[13px] leading-relaxed text-black">
                  Members can ask questions and discuss this step with others.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* ── SECTION 3 — Release ── */}
        <section className="rounded-2xl border border-slate-100 bg-white p-6 md:p-7">
          <div className="mb-5">
            <SectionLabel>Release</SectionLabel>
            <p
              className="mt-1.5 text-[13px] italic"
              style={{ color: 'rgba(12,24,38,0.62)', fontFamily: 'Georgia, serif' }}
            >
              Choose when this step becomes available to members.
            </p>
          </div>
          <ReleaseRuleEditor value={releaseRule} onChange={setReleaseRule} />
        </section>

        {/* Save changes — single action for the three settings sections. */}
        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={settingsSaving}
            className="rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            {settingsSaving ? 'Saving…' : 'Save changes'}
          </button>
          {settingsSaved && <span className="text-[12px] text-teal-600">Saved ✓</span>}
        </div>
      </form>

      {/* ────────────────────────────────────────────────────────────
          SECTION 4 — Content — the visual focus of the page.
          Setting sections above are the supporting configuration;
          this is where the writer actually builds the step.
          ──────────────────────────────────────────────────────────── */}
      <section className="mt-12">
        <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
          <div>
            <SectionLabel>Content</SectionLabel>
            <h2 className="mt-1.5 font-serif text-[22px] leading-snug text-navy-900">
              Content
            </h2>
            <p
              className="mt-1 text-[13.5px] italic"
              style={{ color: 'rgba(12,24,38,0.65)', fontFamily: 'Georgia, serif' }}
            >
              Build this step using text, images, videos, callouts and interactive blocks.
            </p>
          </div>
          {blocks.length > 0 && (
            <div className="shrink-0">
              {adding ? (
                <p className="text-[13px] text-black">Adding block…</p>
              ) : (
                <AddBlockPicker onSelect={addBlock} />
              )}
            </div>
          )}
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white px-4 py-6 md:px-10 md:py-8">
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
              <p className="mb-5 text-[13px] leading-relaxed text-black">
                Start building this step by adding your first block.
              </p>
              <div className="flex justify-center">
                {adding ? (
                  <p className="text-[13px] text-black">Adding block…</p>
                ) : (
                  <AddBlockPicker onSelect={addBlock} />
                )}
              </div>
              {addError && (
                <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-700">
                  {addError}
                </p>
              )}
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

          {blocks.length > 0 && addError && (
            <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-700">
              {addError}
            </p>
          )}
        </div>
      </section>

      {/* ── SECTION 5 — Danger zone ── extra top space separates it
          intentionally from the editor above. */}
      <section className="mt-16">
        <div className="rounded-2xl border border-red-100 bg-white p-5">
          <p className="mb-1 text-[12px] font-semibold uppercase tracking-[0.12em] text-red-400">
            Danger zone
          </p>
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
      </section>

    </div>
  )
}
