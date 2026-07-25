'use client'

import { useState, useTransition } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import type { CreatorMediaAsset, CreatorPathway, CreatorSection, CreatorStep } from '@/types/platform'
import ImagePickerField from '@/components/creator/ImagePickerField'
import { apiUrl } from '@/lib/api'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CONTENT_TYPE_LABEL: Record<string, string> = {
  text: 'Text', video: 'Video', audio: 'Audio', reflection: 'Reflection', exercise: 'Exercise',
}

// ---------------------------------------------------------------------------
// AddStepForm — supports section selection and default section
// ---------------------------------------------------------------------------

function AddStepForm({
  spaceSlug, pathwaySlug, sections, defaultSectionId, onAdded, onCancel,
}: {
  spaceSlug: string
  pathwaySlug: string
  sections: CreatorSection[]
  defaultSectionId: string | null
  onAdded: () => void
  onCancel: () => void
}) {
  const [title, setTitle] = useState('')
  const [contentType, setContentType] = useState('text')
  const [sectionId, setSectionId] = useState<string>(defaultSectionId ?? '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleAdd() {
    if (!title.trim()) { setError('Step title is required.'); return }
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/steps`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            title: title.trim(),
            content_type: contentType,
            section_id: sectionId || null,
          }),
        },
      )
      if (!res.ok) {
        let detail: string | null = null
        try { const b = await res.json(); if (typeof b.detail === 'string') detail = b.detail } catch { /* ignore */ }
        setError(detail ?? 'Could not add step. Please try again.')
        return
      }
      onAdded()
    } catch {
      setError('Could not add step. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="rounded-xl border border-teal-200 bg-teal-50/40 p-4">
      <p className="mb-3 text-[13px] font-semibold text-navy-900">New step</p>
      <div className="mb-3">
        <input
          type="text"
          value={title}
          autoFocus
          onChange={(e) => { setTitle(e.target.value); setError(null) }}
          onKeyDown={(e) => { if (e.key === 'Enter') handleAdd() }}
          placeholder="Step title"
          className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400"
        />
      </div>
      <div className="flex flex-wrap gap-3">
        <select
          value={contentType} onChange={(e) => setContentType(e.target.value)}
          className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-navy-900 outline-none focus:border-teal-400"
        >
          <option value="text">Text</option>
          <option value="video">Video</option>
          <option value="audio">Audio</option>
          <option value="reflection">Reflection</option>
          <option value="exercise">Exercise</option>
        </select>
        {sections.length > 0 && (
          <select
            value={sectionId} onChange={(e) => setSectionId(e.target.value)}
            className="flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-navy-900 outline-none focus:border-teal-400"
          >
            <option value="">No section</option>
            {sections.map((sec) => (
              <option key={sec.id} value={sec.id}>{sec.title}</option>
            ))}
          </select>
        )}
      </div>
      {error && <p className="mt-2 text-[12px] text-red-600">{error}</p>}
      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          disabled={loading || !title.trim()}
          onClick={handleAdd}
          className="rounded-lg px-4 py-1.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          {loading ? 'Adding…' : 'Add step'}
        </button>
        <button type="button" onClick={onCancel} className="text-[13px] text-black transition-colors hover:text-navy-900">
          Cancel
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// StepRow — single step within the structure card
// ---------------------------------------------------------------------------

function StepRow({
  step, num, sections, pathwaySlug, onSectionChange, onMoveUp, onMoveDown, isFirst, isLast, onDelete, deleting,
}: {
  step: CreatorStep
  num: number
  sections: CreatorSection[]
  pathwaySlug: string
  onSectionChange: (step: CreatorStep, sectionId: string | null) => void
  onMoveUp?: () => void
  onMoveDown?: () => void
  isFirst?: boolean
  isLast?: boolean
  onDelete?: () => void
  deleting?: boolean
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 px-4 py-3">
      {/* Up/down reorder controls */}
      <div className="flex shrink-0 flex-col gap-px">
        <button
          type="button"
          onClick={onMoveUp}
          disabled={isFirst}
          className="flex h-4 w-5 items-center justify-center text-slate-300 transition-colors hover:text-slate-600 disabled:opacity-20"
          aria-label="Move step up"
        >
          <svg width="10" height="6" viewBox="0 0 10 6" fill="none">
            <path d="M1 5l4-4 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </button>
        <button
          type="button"
          onClick={onMoveDown}
          disabled={isLast}
          className="flex h-4 w-5 items-center justify-center text-slate-300 transition-colors hover:text-slate-600 disabled:opacity-20"
          aria-label="Move step down"
        >
          <svg width="10" height="6" viewBox="0 0 10 6" fill="none">
            <path d="M1 1l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </button>
      </div>

      <span
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold"
        style={{ background: 'rgba(12,24,38,0.05)', color: '#475569' }}
      >
        {num}
      </span>
      <span className="min-w-0 flex-1 truncate text-[14px] font-medium text-navy-900">
        {step.title}
      </span>
      <span
        className="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium"
        style={{ background: 'rgba(0,0,0,0.04)', color: '#64748b' }}
      >
        {CONTENT_TYPE_LABEL[step.content_type] ?? step.content_type}
      </span>
      {sections.length > 0 && (
        <select
          value={step.section_id ?? ''}
          onChange={(e) => onSectionChange(step, e.target.value || null)}
          className="shrink-0 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[12px] text-black outline-none focus:border-teal-400"
        >
          <option value="">No section</option>
          {sections.map((sec) => (
            <option key={sec.id} value={sec.id}>{sec.title}</option>
          ))}
        </select>
      )}
      <Link
        href={`/creator-studio/pathways/${pathwaySlug}/steps/${step.slug}`}
        className="shrink-0 text-[12px] font-medium text-teal-700 transition-opacity hover:opacity-70"
      >
        Edit →
      </Link>
      {onDelete && (
        <button
          type="button"
          onClick={onDelete}
          disabled={deleting}
          className="shrink-0 text-[12px] text-black transition-colors hover:text-red-500 disabled:opacity-40"
        >
          {deleting ? '…' : 'Delete'}
        </button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// PathwayStructure — unified sections + steps card
// ---------------------------------------------------------------------------

function PathwayStructure({
  pathway, steps, sections, spaceSlug, setSteps, setSections, mediaAssets,
}: {
  pathway: CreatorPathway
  steps: CreatorStep[]
  sections: CreatorSection[]
  spaceSlug: string
  setSteps: (s: CreatorStep[]) => void
  setSections: (s: CreatorSection[]) => void
  mediaAssets: CreatorMediaAsset[]
}) {
  const router = useRouter()
  const [, startTransition] = useTransition()

  const [editingSectionId, setEditingSectionId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [bannerEditSectionId, setBannerEditSectionId] = useState<string | null>(null)
  const [addingSection, setAddingSection] = useState(false)
  const [newSectionTitle, setNewSectionTitle] = useState('')
  const [savingSection, setSavingSection] = useState(false)
  // addingToContext: null=closed, 'global'=unsectioned form, or a section id
  const [addingToContext, setAddingToContext] = useState<string | null>(null)
  const [deletingStepId, setDeletingStepId] = useState<string | null>(null)
  const [stepDeleteError, setStepDeleteError] = useState<string | null>(null)

  function stepsForSection(sectionId: string): CreatorStep[] {
    return steps
      .filter((s) => s.section_id === sectionId)
      .sort((a, b) => (a.section_position ?? 0) - (b.section_position ?? 0))
  }

  const unsectionedSteps = steps
    .filter((s) => !s.section_id)
    .sort((a, b) => a.position - b.position)

  const sortedFlatSteps = [...steps].sort((a, b) => a.position - b.position)

  // Display-order numbering: sections first (in section order), unsectioned last
  function globalNum(stepId: string): number {
    const ordered: CreatorStep[] = []
    sections.forEach((sec) => ordered.push(...stepsForSection(sec.id)))
    ordered.push(...unsectionedSteps)
    return ordered.findIndex((s) => s.id === stepId) + 1
  }

  function globalNumFlat(stepId: string): number {
    return sortedFlatSteps.findIndex((s) => s.id === stepId) + 1
  }

  async function handleStepSectionChange(step: CreatorStep, newSectionId: string | null) {
    const res = await fetch(
      apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}/steps/${step.slug}`),
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ section_id: newSectionId }),
      },
    )
    if (res.ok) {
      const updated: CreatorStep = await res.json()
      setSteps(steps.map((s) => (s.id === step.id ? updated : s)))
    }
  }

  async function handleSectionStepMove(step: CreatorStep, dir: -1 | 1, sectionId: string) {
    const contextSteps = stepsForSection(sectionId)
    const idx = contextSteps.findIndex((s) => s.id === step.id)
    const swapIdx = idx + dir
    if (swapIdx < 0 || swapIdx >= contextSteps.length) return
    const next = [...contextSteps]
    ;[next[idx], next[swapIdx]] = [next[swapIdx], next[idx]]
    setSteps(steps.map((s) => {
      const ni = next.findIndex((n) => n.id === s.id)
      return ni >= 0 ? { ...s, section_position: ni } : s
    }))
    await fetch(
      apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}/sections/${sectionId}/steps/reorder`),
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ ids: next.map((s) => s.id) }),
      },
    )
  }

  async function handleUnsectionedStepMove(step: CreatorStep, dir: -1 | 1) {
    const contextSteps = [...unsectionedSteps]
    const idx = contextSteps.findIndex((s) => s.id === step.id)
    const swapIdx = idx + dir
    if (swapIdx < 0 || swapIdx >= contextSteps.length) return
    ;[contextSteps[idx], contextSteps[swapIdx]] = [contextSteps[swapIdx], contextSteps[idx]]
    setSteps(steps.map((s) => {
      const ni = contextSteps.findIndex((n) => n.id === s.id)
      return ni >= 0 ? { ...s, position: ni } : s
    }))
    await fetch(
      apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}/steps/unsectioned/reorder`),
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ ids: contextSteps.map((s) => s.id) }),
      },
    )
  }

  async function handleFlatStepMove(step: CreatorStep, dir: -1 | 1) {
    const sorted = [...sortedFlatSteps]
    const idx = sorted.findIndex((s) => s.id === step.id)
    const swapIdx = idx + dir
    if (swapIdx < 0 || swapIdx >= sorted.length) return
    ;[sorted[idx], sorted[swapIdx]] = [sorted[swapIdx], sorted[idx]]
    setSteps(steps.map((s) => {
      const ni = sorted.findIndex((n) => n.id === s.id)
      return ni >= 0 ? { ...s, position: ni } : s
    }))
    await fetch(
      apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}/steps/reorder`),
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ ids: sorted.map((s) => s.id) }),
      },
    )
  }

  async function handleSectionMove(idx: number, dir: -1 | 1) {
    const swapIdx = idx + dir
    if (swapIdx < 0 || swapIdx >= sections.length) return
    const next = [...sections]
    ;[next[idx], next[swapIdx]] = [next[swapIdx], next[idx]]
    setSections(next)
    await fetch(
      apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}/sections/reorder`),
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ ids: next.map((s) => s.id) }),
      },
    )
  }

  async function handleSectionRename(id: string) {
    if (!editTitle.trim()) return
    const res = await fetch(
      apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}/sections/${id}`),
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ title: editTitle.trim() }),
      },
    )
    if (!res.ok) return
    const updated: CreatorSection = await res.json()
    setSections(sections.map((s) => (s.id === id ? updated : s)))
    setEditingSectionId(null)
  }

  async function handleSectionBannerChange(id: string, next: string | null) {
    const res = await fetch(
      apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}/sections/${id}`),
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ banner_image_url: next }),
      },
    )
    if (!res.ok) return
    const updated: CreatorSection = await res.json()
    setSections(sections.map((s) => (s.id === id ? updated : s)))
  }

  async function handleSectionDelete(id: string) {
    const res = await fetch(
      apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}/sections/${id}`),
      { method: 'DELETE', credentials: 'include' },
    )
    if (res.ok) {
      setSections(sections.filter((s) => s.id !== id))
      setSteps(steps.map((s) => (s.section_id === id ? { ...s, section_id: null } : s)))
    }
  }

  async function handleSectionAdd() {
    if (!newSectionTitle.trim()) return
    setSavingSection(true)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}/sections`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ title: newSectionTitle.trim() }),
        },
      )
      if (res.ok) {
        const created: CreatorSection = await res.json()
        setSections([...sections, created])
        setNewSectionTitle('')
        setAddingSection(false)
      }
    } finally {
      setSavingSection(false)
    }
  }

  function handleStepAdded() {
    setAddingToContext(null)
    startTransition(() => { router.refresh() })
    fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}/steps`), { credentials: 'include' })
      .then((r) => r.json())
      .then((data: CreatorStep[]) => setSteps(data))
      .catch(() => { /* router.refresh() covers it */ })
  }

  async function handleStepDelete(step: CreatorStep) {
    if (!confirm('Are you sure you want to delete this step? This cannot be undone.')) return
    setDeletingStepId(step.id)
    setStepDeleteError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}/steps/${step.slug}`),
        { method: 'DELETE', credentials: 'include' },
      )
      if (res.ok) {
        setSteps(steps.filter((s) => s.id !== step.id))
      } else {
        setStepDeleteError('Failed to delete step. Please try again.')
      }
    } catch {
      setStepDeleteError('Failed to delete step. Please try again.')
    } finally {
      setDeletingStepId(null)
    }
  }

  const isEmpty = steps.length === 0 && sections.length === 0 && !addingSection && !addingToContext

  return (
    <div className="rounded-2xl border border-border bg-white p-6">

      {/* ── Header ── */}
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-[17px] font-semibold tracking-tight text-navy-900">Pathway structure</h2>
          <p className="mt-0.5 text-[13px] text-black">
            {isEmpty
              ? 'Add steps to shape the journey, or create sections to organise them into modules.'
              : `${steps.length} ${steps.length === 1 ? 'step' : 'steps'}${sections.length > 0 ? ` · ${sections.length} ${sections.length === 1 ? 'section' : 'sections'}` : ''}`
            }
          </p>
        </div>
        {!addingSection && (
          <button
            type="button"
            onClick={() => setAddingSection(true)}
            className="shrink-0 rounded-lg border border-dashed border-slate-300 px-3 py-1.5 text-[12px] font-medium text-black transition-colors hover:border-teal-300 hover:text-teal-700"
          >
            + Add section
          </button>
        )}
      </div>

      {/* ── New section form ── */}
      {addingSection && (
        <div className="mb-5 rounded-xl border border-teal-200 bg-teal-50/40 p-4">
          <p className="mb-2.5 text-[13px] font-semibold text-navy-900">New section</p>
          <input
            autoFocus
            type="text"
            value={newSectionTitle}
            onChange={(e) => setNewSectionTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSectionAdd()
              if (e.key === 'Escape') { setAddingSection(false); setNewSectionTitle('') }
            }}
            placeholder="e.g. Week 1 — Foundation"
            className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none focus:border-teal-400"
          />
          <div className="mt-3 flex items-center gap-2">
            <button
              type="button"
              disabled={savingSection || !newSectionTitle.trim()}
              onClick={handleSectionAdd}
              className="rounded-lg px-4 py-1.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
            >
              {savingSection ? 'Adding…' : 'Add section'}
            </button>
            <button
              type="button"
              onClick={() => { setAddingSection(false); setNewSectionTitle('') }}
              className="text-[13px] text-black transition-colors hover:text-navy-900"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* ── Step delete error ── */}
      {stepDeleteError && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-[13px] text-red-700">
          {stepDeleteError}
        </div>
      )}

      {/* ── Sectioned view ── */}
      {sections.length > 0 && (
        <div className="space-y-3">
          {sections.map((section, sectionIdx) => {
            const sectionSteps = stepsForSection(section.id)
            const isEditing = editingSectionId === section.id
            const isAddingHere = addingToContext === section.id

            return (
              <div
                key={section.id}
                className="overflow-hidden rounded-xl"
                style={{
                  border: '1px solid rgba(12,24,38,0.08)',
                  borderLeft: '3px solid #38A09E',
                }}
              >

                {/* Section header — teal-tinted anchor row */}
                <div
                  className="flex items-center gap-2.5 px-4 py-2.5"
                  style={{
                    background:
                      'linear-gradient(90deg, rgba(56,160,158,0.08) 0%, rgba(56,160,158,0.02) 60%, rgba(255,255,255,0) 100%)',
                    borderBottom: '1px solid rgba(56,160,158,0.16)',
                  }}
                >
                  {/* Reorder buttons */}
                  <div className="flex shrink-0 flex-col gap-px">
                    <button
                      type="button"
                      onClick={() => handleSectionMove(sectionIdx, -1)}
                      disabled={sectionIdx === 0}
                      className="flex h-4 w-5 items-center justify-center text-slate-300 transition-colors hover:text-slate-600 disabled:opacity-30"
                      aria-label="Move section up"
                    >
                      <svg width="10" height="6" viewBox="0 0 10 6" fill="none">
                        <path d="M1 5l4-4 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                      </svg>
                    </button>
                    <button
                      type="button"
                      onClick={() => handleSectionMove(sectionIdx, 1)}
                      disabled={sectionIdx === sections.length - 1}
                      className="flex h-4 w-5 items-center justify-center text-slate-300 transition-colors hover:text-slate-600 disabled:opacity-30"
                      aria-label="Move section down"
                    >
                      <svg width="10" height="6" viewBox="0 0 10 6" fill="none">
                        <path d="M1 1l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                      </svg>
                    </button>
                  </div>

                  {/* Section ordinal chip — the primary teal anchor */}
                  <span
                    className="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.10em]"
                    style={{
                      background: 'rgba(56,160,158,0.14)',
                      color: '#0f766e',
                      border: '1px solid rgba(56,160,158,0.22)',
                    }}
                  >
                    Section {sectionIdx + 1}
                  </span>

                  {/* Title / edit input */}
                  {isEditing ? (
                    <input
                      autoFocus
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleSectionRename(section.id)
                        if (e.key === 'Escape') setEditingSectionId(null)
                      }}
                      className="flex-1 rounded-lg border border-teal-300 bg-white px-2.5 py-1 text-[15px] font-semibold tracking-tight text-navy-900 outline-none"
                    />
                  ) : (
                    <span className="flex-1 text-[15px] font-semibold tracking-tight text-navy-900">
                      {section.title}
                    </span>
                  )}

                  <span className="shrink-0 text-[11px] text-black">
                    {sectionSteps.length} {sectionSteps.length === 1 ? 'step' : 'steps'}
                  </span>

                  {isEditing ? (
                    <>
                      <button
                        type="button"
                        onClick={() => handleSectionRename(section.id)}
                        className="shrink-0 text-[12px] font-semibold text-teal-700 hover:opacity-70"
                      >Save</button>
                      <button
                        type="button"
                        onClick={() => setEditingSectionId(null)}
                        className="shrink-0 text-[12px] text-black hover:text-navy-900"
                      >Cancel</button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={() => { setEditingSectionId(section.id); setEditTitle(section.title) }}
                        className="shrink-0 text-[12px] text-black transition-colors hover:text-teal-700"
                      >Rename</button>
                      <button
                        type="button"
                        onClick={() => setBannerEditSectionId(bannerEditSectionId === section.id ? null : section.id)}
                        className={`shrink-0 text-[12px] transition-colors hover:text-teal-700 ${
                          section.banner_image_url ? 'text-teal-700' : 'text-slate-400'
                        }`}
                      >
                        {section.banner_image_url ? 'Banner ✓' : 'Banner'}
                      </button>
                      <button
                        type="button"
                        onClick={() => handleSectionDelete(section.id)}
                        className="shrink-0 text-[12px] text-black transition-colors hover:text-red-500"
                      >Delete</button>
                    </>
                  )}
                </div>

                {/* Inline banner editor */}
                {bannerEditSectionId === section.id && (
                  <div className="border-b border-slate-100 bg-white p-4">
                    <p className="mb-2 text-[12px] font-semibold uppercase tracking-[0.12em] text-black">
                      Section banner image
                    </p>
                    <ImagePickerField
                      value={section.banner_image_url ?? null}
                      onChange={(next) => handleSectionBannerChange(section.id, next)}
                      spaceSlug={spaceSlug}
                      initialAssets={mediaAssets}
                      helperText="Shown above the section title on the pathway page. Optional — leave empty for the current text-only look."
                    />
                    <div className="mt-3 flex justify-end">
                      <button
                        type="button"
                        onClick={() => setBannerEditSectionId(null)}
                        className="rounded-lg border border-slate-200 px-4 py-2 text-[13px] font-medium text-black hover:bg-slate-50"
                      >
                        Done
                      </button>
                    </div>
                  </div>
                )}

                {/* Steps in this section */}
                {sectionSteps.length > 0 && (
                  <div className="divide-y divide-slate-100">
                    {sectionSteps.map((step, stepIdx) => (
                      <StepRow
                        key={step.id}
                        step={step}
                        num={globalNum(step.id)}
                        sections={sections}
                        pathwaySlug={pathway.slug}
                        onSectionChange={handleStepSectionChange}
                        onMoveUp={() => handleSectionStepMove(step, -1, section.id)}
                        onMoveDown={() => handleSectionStepMove(step, 1, section.id)}
                        isFirst={stepIdx === 0}
                        isLast={stepIdx === sectionSteps.length - 1}
                        onDelete={() => handleStepDelete(step)}
                        deleting={deletingStepId === step.id}
                      />
                    ))}
                  </div>
                )}

                {sectionSteps.length === 0 && !isAddingHere && (
                  <p className="px-4 py-3 text-[13px] italic text-black">No steps in this section yet.</p>
                )}

                {/* Per-section add step */}
                <div className="border-t border-slate-50 px-4 py-3">
                  {isAddingHere ? (
                    <AddStepForm
                      spaceSlug={spaceSlug}
                      pathwaySlug={pathway.slug}
                      sections={sections}
                      defaultSectionId={section.id}
                      onAdded={handleStepAdded}
                      onCancel={() => setAddingToContext(null)}
                    />
                  ) : (
                    !addingToContext && (
                      <button
                        type="button"
                        onClick={() => setAddingToContext(section.id)}
                        className="text-[12px] font-medium text-black transition-colors hover:text-teal-700"
                      >
                        + Add step here
                      </button>
                    )
                  )}
                </div>
              </div>
            )
          })}

          {/* Unsectioned group — shown after sections. Kept visually
              quieter than sectioned rows so genuine sections read as the
              primary anchors. */}
          {unsectionedSteps.length > 0 && (
            <div
              className="overflow-hidden rounded-xl"
              style={{ border: '1px dashed rgba(12,24,38,0.18)' }}
            >
              <div
                className="px-4 py-2.5"
                style={{
                  background: 'rgba(12,24,38,0.02)',
                  borderBottom: '1px solid rgba(12,24,38,0.06)',
                }}
              >
                <span className="text-[12px] font-medium uppercase tracking-[0.08em] text-slate-500">
                  Unsectioned · {unsectionedSteps.length} {unsectionedSteps.length === 1 ? 'step' : 'steps'}
                </span>
              </div>
              <div className="divide-y divide-slate-100">
                {unsectionedSteps.map((step, stepIdx) => (
                  <StepRow
                    key={step.id}
                    step={step}
                    num={globalNum(step.id)}
                    sections={sections}
                    pathwaySlug={pathway.slug}
                    onSectionChange={handleStepSectionChange}
                    onMoveUp={() => handleUnsectionedStepMove(step, -1)}
                    onMoveDown={() => handleUnsectionedStepMove(step, 1)}
                    isFirst={stepIdx === 0}
                    isLast={stepIdx === unsectionedSteps.length - 1}
                    onDelete={() => handleStepDelete(step)}
                    deleting={deletingStepId === step.id}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Flat view (no sections) ── */}
      {sections.length === 0 && sortedFlatSteps.length > 0 && (
        <div className="mb-4 overflow-hidden rounded-xl border border-slate-200">
          <div className="divide-y divide-slate-100">
            {sortedFlatSteps.map((step, i) => (
              <StepRow
                key={step.id}
                step={step}
                num={i + 1}
                sections={sections}
                pathwaySlug={pathway.slug}
                onSectionChange={handleStepSectionChange}
                onMoveUp={() => handleFlatStepMove(step, -1)}
                onMoveDown={() => handleFlatStepMove(step, 1)}
                onDelete={() => handleStepDelete(step)}
                deleting={deletingStepId === step.id}
                isFirst={i === 0}
                isLast={i === sortedFlatSteps.length - 1}
              />
            ))}
          </div>
        </div>
      )}

      {/* ── Global add step ── */}
      <div className={sections.length > 0 || steps.length > 0 ? 'mt-4' : ''}>
        {addingToContext === 'global' ? (
          <AddStepForm
            spaceSlug={spaceSlug}
            pathwaySlug={pathway.slug}
            sections={sections}
            defaultSectionId={null}
            onAdded={handleStepAdded}
            onCancel={() => setAddingToContext(null)}
          />
        ) : (
          !addingToContext && (
            <button
              type="button"
              onClick={() => setAddingToContext('global')}
              className="rounded-lg border border-dashed border-slate-300 px-4 py-2 text-[13px] font-medium text-black transition-colors hover:border-teal-300 hover:text-teal-700"
            >
              {sections.length > 0 ? '+ Add step without section' : '+ Add step'}
            </button>
          )
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Default export — Content page wrapper
// ---------------------------------------------------------------------------

interface Props {
  pathway: CreatorPathway
  steps: CreatorStep[]
  sections: CreatorSection[]
  spaceSlug: string
  mediaAssets: CreatorMediaAsset[]
}

/**
 * Pathway Content page — sections + steps working area.
 * Owns only structure state; settings live in ``PathwaySettingsClient``.
 */
export default function PathwayContentClient({
  pathway, steps: initialSteps, sections: initialSections, spaceSlug, mediaAssets,
}: Props) {
  const [steps, setSteps]         = useState<CreatorStep[]>(initialSteps)
  const [sections, setSections]   = useState<CreatorSection[]>(initialSections)

  return (
    <PathwayStructure
      pathway={pathway}
      steps={steps}
      sections={sections}
      spaceSlug={spaceSlug}
      setSteps={setSteps}
      setSections={setSections}
      mediaAssets={mediaAssets}
    />
  )
}
