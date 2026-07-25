'use client'

import { useEffect, useMemo, useRef, useState, useTransition, useCallback } from 'react'
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
// Popover — a small anchor for the two properties that need real editors
// (reading time, release rule). Closes on outside-click and Escape.
// ---------------------------------------------------------------------------

function Popover({
  trigger, ariaLabel, children, width = 'w-72',
}: {
  trigger: (open: boolean) => React.ReactNode
  ariaLabel: string
  children: (close: () => void) => React.ReactNode
  width?: string
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    function onDown(e: MouseEvent) {
      if (!ref.current) return
      if (!ref.current.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        aria-label={ariaLabel}
        aria-expanded={open}
      >
        {trigger(open)}
      </button>
      {open && (
        <div
          className={`absolute left-0 top-full z-30 mt-2 ${width} rounded-xl border border-slate-200 bg-white p-4 shadow-lg`}
        >
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Short human summary of the current release rule — used as the pill label
// so the writer can read the setting without opening the popover.
// ---------------------------------------------------------------------------

function releaseSummary(value: ReleaseRuleValue): string {
  switch (value.release_type) {
    case 'immediate':
      return 'Releases immediately'
    case 'days_after_enrollment': {
      const days = value.release_offset_days ?? 0
      if (days === 0) return 'Releases immediately'
      return `Releases after ${days} day${days === 1 ? '' : 's'}`
    }
    case 'fixed_date': {
      if (!value.release_at) return 'Releases on a set date'
      try {
        const d = new Date(value.release_at)
        return `Releases on ${d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short' })}`
      } catch { return 'Releases on a set date' }
    }
    case 'after_previous':
      return 'Releases after previous step'
    case 'manual':
      return 'Released manually by the creator'
    default:
      return 'Set release rule'
  }
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

  // Dirty tracking — compares current local state to what came in from
  // the server. Resets naturally when router.refresh() re-runs the
  // server component after a successful save. Drives the Save button
  // between its "quiet Saved" state and its "primary Save changes"
  // state so the writer can see at a glance whether they have unsaved
  // work.
  const initialSettings = useMemo(() => ({
    title: step.title,
    minutes: step.estimated_minutes?.toString() ?? '',
    required: step.is_required,
    reflection: step.reflection_enabled,
    discussion: step.discussion_enabled,
    releaseKey: JSON.stringify(releaseRuleFromStep(step)),
  }), [step])
  const isDirty =
    stepTitle !== initialSettings.title ||
    stepMinutes !== initialSettings.minutes ||
    stepRequired !== initialSettings.required ||
    reflectionEnabled !== initialSettings.reflection ||
    discussionEnabled !== initialSettings.discussion ||
    JSON.stringify(releaseRule) !== initialSettings.releaseKey

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
    <form
      onSubmit={saveStepSettings}
      className="min-h-full w-full bg-white px-8 py-8 md:px-10 md:py-10"
    >

      {/* ────────────────────────────────────────────────────────────
          Compact header. Breadcrumb sits at the top; the step title
          becomes the document's editable H1; the metadata strip
          replaces the three former settings sections; the Save
          changes affordance sits inline so the writer sees whether
          there is unsaved work without a persistent commit button
          dominating the page.
          ──────────────────────────────────────────────────────────── */}
      <header className="mx-auto max-w-3xl">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <Link
            href={resolvedBackHref}
            className="text-[12px] font-medium text-slate-500 transition-colors hover:text-slate-700"
          >
            {resolvedBackLabel}
          </Link>
          <span className="text-slate-300" aria-hidden="true">·</span>
          <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
            {pathway.title}
          </span>
          {stepIndex !== null && totalSteps > 0 && (
            <>
              <span className="text-slate-300" aria-hidden="true">·</span>
              <span
                className="text-[12.5px] italic"
                style={{ color: 'rgba(12,24,38,0.55)', fontFamily: 'Georgia, serif' }}
              >
                Step {stepIndex + 1} of {totalSteps}
              </span>
            </>
          )}

          {/* Save affordance — quiet when clean, primary when dirty.
              Anchored top-right so the writer always knows where to
              commit without a persistent button dominating the page. */}
          <div className="ml-auto flex items-center gap-3">
            {settingsSaved && !isDirty && (
              <span
                className="text-[12px] italic"
                style={{ color: '#0f766e', fontFamily: 'Georgia, serif' }}
              >
                Saved
              </span>
            )}
            {isDirty ? (
              <button
                type="submit"
                disabled={settingsSaving}
                className="rounded-full px-4 py-1.5 text-[12.5px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
                style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
              >
                {settingsSaving ? 'Saving…' : 'Save changes'}
              </button>
            ) : (
              !settingsSaved && (
                <span className="text-[12px] italic text-slate-400" style={{ fontFamily: 'Georgia, serif' }}>
                  All changes saved
                </span>
              )
            )}
          </div>
        </div>

        {/* Editable inline step title — the document's H1. Borderless
            at rest, a whisper of a slate underline on focus. Enter or
            blur commits to local state; the Save affordance above
            commits to the backend. */}
        <input
          type="text"
          value={stepTitle}
          onChange={e => setStepTitle(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') { e.preventDefault(); (e.currentTarget as HTMLInputElement).blur() }
          }}
          placeholder="Untitled step"
          aria-label="Step title"
          className="mt-4 w-full border-b border-transparent bg-transparent py-1 font-serif text-[28px] leading-tight text-navy-900 outline-none transition-colors placeholder:text-slate-300 focus:border-slate-300 md:text-[34px]"
        />

        {/* Metadata strip — the six former settings condensed to one
            row of inline pills. Booleans toggle in place; the two
            fields that need a real editor (reading time, release
            rule) open a small popover anchored under the pill. */}
        <div className="mt-4 flex flex-wrap items-center gap-x-1 gap-y-2 text-[13px]">

          {/* Reading time */}
          <Popover
            ariaLabel="Set reading time"
            trigger={(open) => (
              <span
                className={`inline-flex items-center rounded-full px-2.5 py-1 transition-colors ${
                  open ? 'bg-teal-50 text-teal-800' : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                {stepMinutes
                  ? `${stepMinutes} min`
                  : <span className="italic text-slate-400">Add reading time</span>}
              </span>
            )}
          >
            {(close) => (
              <div>
                <label className="block text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500" htmlFor="rt-input">
                  Estimated reading time
                </label>
                <div className="mt-2 flex items-center gap-2">
                  <input
                    id="rt-input"
                    type="number" min={1} max={999}
                    value={stepMinutes}
                    onChange={e => setStepMinutes(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); close() } }}
                    placeholder="—"
                    className="w-24 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[14px] text-navy-900 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
                    autoFocus
                  />
                  <span className="text-[13px] text-slate-600">minutes</span>
                </div>
                {stepMinutes && (
                  <button
                    type="button"
                    onClick={() => { setStepMinutes(''); close() }}
                    className="mt-3 text-[12px] text-slate-500 hover:text-slate-700"
                  >
                    Clear
                  </button>
                )}
              </div>
            )}
          </Popover>

          <span className="text-slate-300" aria-hidden="true">·</span>

          {/* Required */}
          <button
            type="button"
            role="switch"
            aria-checked={stepRequired}
            onClick={() => setStepRequired(r => !r)}
            className={`rounded-full px-2.5 py-1 transition-colors ${
              stepRequired ? 'bg-teal-50 text-teal-800' : 'text-slate-500 hover:bg-slate-100'
            }`}
          >
            {stepRequired ? 'Required' : <span className="italic">Optional</span>}
          </button>

          <span className="text-slate-300" aria-hidden="true">·</span>

          {/* Private reflection */}
          <button
            type="button"
            role="switch"
            aria-checked={reflectionEnabled}
            onClick={() => setReflectionEnabled(v => !v)}
            title={reflectionEnabled
              ? 'Members can keep private notes as they work through this step.'
              : 'Private reflection is off for this step.'}
            className={`rounded-full px-2.5 py-1 transition-colors ${
              reflectionEnabled ? 'bg-teal-50 text-teal-800' : 'text-slate-500 hover:bg-slate-100'
            }`}
          >
            {reflectionEnabled ? 'Reflection' : <span className="italic">Reflection off</span>}
          </button>

          <span className="text-slate-300" aria-hidden="true">·</span>

          {/* Discussion */}
          <button
            type="button"
            role="switch"
            aria-checked={discussionEnabled}
            onClick={() => setDiscussionEnabled(v => !v)}
            title={discussionEnabled
              ? 'Members can ask questions and discuss this step with others.'
              : 'Discussion is off for this step.'}
            className={`rounded-full px-2.5 py-1 transition-colors ${
              discussionEnabled ? 'bg-teal-50 text-teal-800' : 'text-slate-500 hover:bg-slate-100'
            }`}
          >
            {discussionEnabled ? 'Discussion' : <span className="italic">Discussion off</span>}
          </button>

          <span className="text-slate-300" aria-hidden="true">·</span>

          {/* Release rule */}
          <Popover
            ariaLabel="Set release rule"
            width="w-96"
            trigger={(open) => (
              <span
                className={`inline-flex items-center rounded-full px-2.5 py-1 transition-colors ${
                  open ? 'bg-teal-50 text-teal-800' : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                {releaseSummary(releaseRule)}
              </span>
            )}
          >
            {(close) => (
              <div>
                <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">
                  Release
                </p>
                <ReleaseRuleEditor value={releaseRule} onChange={setReleaseRule} />
                <div className="mt-4 flex justify-end">
                  <button
                    type="button"
                    onClick={close}
                    className="rounded-full px-3 py-1 text-[12.5px] font-medium text-slate-600 hover:bg-slate-100"
                  >
                    Done
                  </button>
                </div>
              </div>
            )}
          </Popover>
        </div>
      </header>

      {/* ────────────────────────────────────────────────────────────
          Document. No card, no shadow, no "Content" heading, no
          subtitle. The writing sits directly on the page at
          editorial column width. Insertion affordances (the between-
          block +'s and the trailing "+ Add content") are the only
          editing chrome that lives inside the column.
          ──────────────────────────────────────────────────────────── */}
      <div className="mx-auto mt-16 max-w-3xl">

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
          <div
            className="rounded-2xl px-8 py-16 text-center"
            style={{ background: '#FBFAF6' }}
          >
            <p className="mb-2 font-serif text-[19px] leading-snug text-navy-900">
              A blank page awaits.
            </p>
            <p className="mx-auto mb-6 max-w-sm text-[13.5px] leading-relaxed text-slate-600">
              Start building this step by adding your first block.
            </p>
            <div className="flex justify-center">
              {adding ? (
                <p className="text-[13px] text-slate-600">Adding block…</p>
              ) : (
                <AddBlockPicker onSelect={addBlock} />
              )}
            </div>
            {addError && (
              <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-700">
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

      {/* ────────────────────────────────────────────────────────────
          Delete this step — the former Danger zone as a small text
          link tucked at the foot of the page. Same confirmation
          dialog, same destructive behaviour, zero page section.
          ──────────────────────────────────────────────────────────── */}
      <div className="mx-auto mt-28 flex max-w-3xl justify-center">
        {deleteStepError ? (
          <div className="flex flex-col items-center gap-2">
            <p className="text-[12.5px] text-red-600">{deleteStepError}</p>
            <button
              type="button"
              onClick={deleteStep}
              disabled={deletingStep}
              className="text-[12.5px] text-slate-400 transition-colors hover:text-red-500 disabled:opacity-40"
            >
              {deletingStep ? 'Deleting…' : 'Delete this step'}
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={deleteStep}
            disabled={deletingStep}
            className="text-[12.5px] text-slate-400 transition-colors hover:text-red-500 disabled:opacity-40"
          >
            {deletingStep ? 'Deleting…' : 'Delete this step'}
          </button>
        )}
      </div>

    </form>
  )
}
