'use client'

import { useEffect, useState, useTransition } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import type { CreatorPathway, CreatorSection, CreatorStep } from '@/types/platform'
import { apiUrl, resolveMediaUrl } from '@/lib/api'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ACCESS_OPTIONS = [
  { value: 'free', label: 'Free', description: 'Anyone with access to the collective can begin this pathway.' },
  { value: 'included', label: 'Included in collective access', description: 'Available to members who already have access to this collective.' },
  { value: 'one_time', label: 'One-off payment — single price', description: 'People pay a single fixed price to access this pathway.' },
  { value: 'subscription', label: 'Monthly subscription', description: 'People pay monthly for ongoing access to this pathway.' },
]

const PRICING_MODE_PAYMENT_OPTIONS_VALUE = 'payment_options'

const CONTENT_TYPE_LABEL: Record<string, string> = {
  text: 'Text', video: 'Video', audio: 'Audio', reflection: 'Reflection', exercise: 'Exercise',
}

// ---------------------------------------------------------------------------
// AccessPricingSection
// ---------------------------------------------------------------------------

function AccessPricingSection({
  accessType, setAccessType, pricingMode, setPricingMode,
  priceDollars, setPriceDollars, currency, setCurrency, priceError,
}: {
  accessType: string
  setAccessType: (v: string) => void
  pricingMode: string
  setPricingMode: (v: string) => void
  priceDollars: string
  setPriceDollars: (v: string) => void
  currency: string
  setCurrency: (v: string) => void
  priceError: string | null
}) {
  const isPaymentOptions = pricingMode === PRICING_MODE_PAYMENT_OPTIONS_VALUE
  const showSinglePrice = (accessType === 'one_time' || accessType === 'subscription') && !isPaymentOptions

  const ALL_CHOICES: { value: string; label: string; description: string; isPaymentOptions?: boolean }[] = [
    { value: 'free', label: 'Free', description: 'Anyone with access to the collective can begin this pathway.' },
    { value: 'included', label: 'Included in collective access', description: 'Available to members who already have access to this collective.' },
    { value: 'one_time', label: 'One-off payment — single price', description: 'People pay a single fixed price to access this pathway.' },
    { value: 'subscription', label: 'Monthly subscription', description: 'People pay monthly for ongoing access to this pathway.' },
    {
      value: PRICING_MODE_PAYMENT_OPTIONS_VALUE,
      label: 'Multiple payment options',
      description: 'Members choose from tiered or term-based options (e.g. Awaken / Activate / Empower). Manage options in the Payment Options section below.',
      isPaymentOptions: true,
    },
  ]

  function handleChoiceClick(value: string) {
    if (value === PRICING_MODE_PAYMENT_OPTIONS_VALUE) {
      setPricingMode('payment_options')
      setAccessType('one_time') // entitlement access type stays one_time
    } else {
      setPricingMode('legacy')
      setAccessType(value)
    }
  }

  const selectedChoiceValue = isPaymentOptions ? PRICING_MODE_PAYMENT_OPTIONS_VALUE : accessType

  return (
    <div>
      <label className="mb-2 block text-[12px] font-semibold text-slate-600">Access and pricing</label>
      <div className="space-y-2">
        {ALL_CHOICES.map((opt) => {
          const selected = selectedChoiceValue === opt.value
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => handleChoiceClick(opt.value)}
              className="w-full rounded-xl border px-4 py-3 text-left transition-colors"
              style={
                selected
                  ? { borderColor: 'rgba(56,160,158,0.6)', background: 'rgba(56,160,158,0.05)' }
                  : { borderColor: '#e2e8f0', background: 'white' }
              }
            >
              <div className="flex items-center gap-3">
                <div
                  className="mt-0.5 h-4 w-4 shrink-0 rounded-full border-2 transition-colors"
                  style={selected ? { borderColor: '#38A09E', background: '#38A09E' } : { borderColor: '#cbd5e1', background: 'white' }}
                />
                <div>
                  <p className="text-[14px] font-semibold text-navy-900">{opt.label}</p>
                  <p className="mt-0.5 text-[12px] leading-relaxed text-slate-500">{opt.description}</p>
                </div>
              </div>
            </button>
          )
        })}
      </div>

      {isPaymentOptions && (
        <div className="mt-3 rounded-xl border border-teal-200 bg-teal-50/40 px-4 py-3 text-[12px] text-teal-800">
          Pricing is controlled by the Payment Options section below. The single-price field is not used.
        </div>
      )}

      {showSinglePrice && (
        <div className="mt-3 flex gap-3">
          <div className="flex-1">
            <label className="mb-1 block text-[12px] font-semibold text-slate-600">
              {accessType === 'subscription' ? 'Monthly price' : 'Price'}
            </label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[14px] text-slate-400">$</span>
              <input
                type="number" min="0" step="0.01" value={priceDollars}
                onChange={(e) => setPriceDollars(e.target.value)} placeholder="0.00"
                className={`w-full rounded-lg border py-2 pl-7 pr-3 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400 ${priceError ? 'border-red-300' : 'border-slate-200'}`}
              />
            </div>
            {priceError && <p className="mt-1 text-[12px] text-red-600">{priceError}</p>}
          </div>
          <div className="w-28">
            <label className="mb-1 block text-[12px] font-semibold text-slate-600">Currency</label>
            <select
              value={currency} onChange={(e) => setCurrency(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] text-navy-900 outline-none focus:border-teal-400"
            >
              <option value="AUD">AUD</option>
              <option value="USD">USD</option>
              <option value="GBP">GBP</option>
              <option value="EUR">EUR</option>
              <option value="NZD">NZD</option>
            </select>
          </div>
        </div>
      )}

      {showSinglePrice && (
        <p className="mt-2 text-[11px] text-slate-400">
          Pricing is saved for configuration. Payment processing will be connected when Stripe is set up.
        </p>
      )}
    </div>
  )
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
        <button type="button" onClick={onCancel} className="text-[13px] text-slate-500 transition-colors hover:text-navy-900">
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
  step, num, sections, pathwaySlug, onSectionChange, onMoveUp, onMoveDown, isFirst, isLast,
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
        style={{ background: 'rgba(56,160,158,0.10)', color: '#38A09E' }}
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
          className="shrink-0 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[12px] text-slate-500 outline-none focus:border-teal-400"
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
    </div>
  )
}

// ---------------------------------------------------------------------------
// PathwayStructure — unified sections + steps card
// ---------------------------------------------------------------------------

function PathwayStructure({
  pathway, steps, sections, spaceSlug, setSteps, setSections,
}: {
  pathway: CreatorPathway
  steps: CreatorStep[]
  sections: CreatorSection[]
  spaceSlug: string
  setSteps: (s: CreatorStep[]) => void
  setSections: (s: CreatorSection[]) => void
}) {
  const router = useRouter()
  const [, startTransition] = useTransition()

  const [editingSectionId, setEditingSectionId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [addingSection, setAddingSection] = useState(false)
  const [newSectionTitle, setNewSectionTitle] = useState('')
  const [savingSection, setSavingSection] = useState(false)
  // addingToContext: null=closed, 'global'=unsectioned form, or a section id
  const [addingToContext, setAddingToContext] = useState<string | null>(null)

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

  const isEmpty = steps.length === 0 && sections.length === 0 && !addingSection && !addingToContext

  return (
    <div className="rounded-2xl border border-border bg-white p-6">

      {/* ── Header ── */}
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-[16px] font-semibold text-navy-900">Pathway structure</h2>
          <p className="mt-0.5 text-[13px] text-slate-500">
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
            className="shrink-0 rounded-lg border border-dashed border-slate-300 px-3 py-1.5 text-[12px] font-medium text-slate-500 transition-colors hover:border-teal-300 hover:text-teal-700"
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
              className="text-[13px] text-slate-500 transition-colors hover:text-navy-900"
            >
              Cancel
            </button>
          </div>
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
              <div key={section.id} className="overflow-hidden rounded-xl border border-slate-200">

                {/* Section header */}
                <div className="flex items-center gap-2 border-b border-slate-100 bg-slate-50 px-3 py-2.5">
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
                      className="flex-1 rounded-lg border border-teal-300 bg-white px-2.5 py-1 text-[13px] text-navy-900 outline-none"
                    />
                  ) : (
                    <span className="flex-1 text-[13px] font-semibold text-navy-900">
                      {section.title}
                    </span>
                  )}

                  <span className="shrink-0 text-[11px] text-slate-400">
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
                        className="shrink-0 text-[12px] text-slate-400 hover:text-navy-900"
                      >Cancel</button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={() => { setEditingSectionId(section.id); setEditTitle(section.title) }}
                        className="shrink-0 text-[12px] text-slate-400 transition-colors hover:text-teal-700"
                      >Rename</button>
                      <button
                        type="button"
                        onClick={() => handleSectionDelete(section.id)}
                        className="shrink-0 text-[12px] text-slate-400 transition-colors hover:text-red-500"
                      >Delete</button>
                    </>
                  )}
                </div>

                {/* Steps in this section */}
                {sectionSteps.length > 0 && (
                  <div className="divide-y divide-slate-50">
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
                      />
                    ))}
                  </div>
                )}

                {sectionSteps.length === 0 && !isAddingHere && (
                  <p className="px-4 py-3 text-[13px] italic text-slate-400">No steps in this section yet.</p>
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
                        className="text-[12px] font-medium text-slate-400 transition-colors hover:text-teal-700"
                      >
                        + Add step here
                      </button>
                    )
                  )}
                </div>
              </div>
            )
          })}

          {/* Unsectioned group — shown after sections */}
          {unsectionedSteps.length > 0 && (
            <div className="overflow-hidden rounded-xl border border-dashed border-slate-200">
              <div className="border-b border-slate-100 bg-slate-50/60 px-4 py-2.5">
                <span className="text-[12px] font-medium text-slate-500">
                  Unsectioned · {unsectionedSteps.length} {unsectionedSteps.length === 1 ? 'step' : 'steps'}
                </span>
              </div>
              <div className="divide-y divide-slate-50">
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
          <div className="divide-y divide-slate-50">
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
              className="rounded-lg border border-dashed border-slate-300 px-4 py-2 text-[13px] font-medium text-slate-500 transition-colors hover:border-teal-300 hover:text-teal-700"
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
// Main export
// ---------------------------------------------------------------------------

interface Props {
  pathway: CreatorPathway
  steps: CreatorStep[]
  sections: CreatorSection[]
  spaceSlug: string
}

function centsToDisplay(cents: number | null): string {
  if (cents == null) return ''
  const dollars = cents / 100
  return Number.isInteger(dollars) ? `${dollars}` : dollars.toFixed(2)
}

// ---------------------------------------------------------------------------
// PaymentOptionsSection
// ---------------------------------------------------------------------------

interface PaymentOption {
  id: string
  name: string
  description: string | null
  payment_type: string
  status: string
  term_start_date: string | null
  term_end_date: string | null
  sessions_per_week: number | null
  total_sessions: number | null
  price_per_session_cents: number | null
  calculated_total_cents: number | null
  override_total_cents: number | null
  effective_price_cents: number | null
  currency: string
  buyer_note: string | null
  internal_note: string | null
  position: number
}

function fmtOptionPrice(cents: number | null, currency: string): string {
  if (cents == null) return '—'
  const amount = cents / 100
  return `$${Number.isInteger(amount) ? amount.toFixed(0) : amount.toFixed(2)} ${currency}`
}

interface PaymentSchedule {
  id: string
  payment_option_id: string
  name: string
  description: string | null
  schedule_type: string
  status: string
  total_amount_cents: number | null
  upfront_amount_cents: number | null
  installment_amount_cents: number | null
  installment_count: number | null
  interval: string | null
  stripe_interval: string | null
  stripe_interval_count: number | null
  currency: string
  buyer_note: string | null
  internal_note: string | null
  position: number
}

function scheduleTypeLabel(t: string): string {
  if (t === 'pay_in_full') return 'Pay in full'
  if (t === 'recurring_installments') return 'Recurring instalments'
  if (t === 'manual') return 'Manual'
  return t
}

function PaymentSchedulesSection({
  spaceSlug,
  pathwaySlug,
  optionId,
  effectivePrice,
  currency: optCurrency,
}: {
  spaceSlug: string
  pathwaySlug: string
  optionId: string
  effectivePrice: number | null
  currency: string
}) {
  const [schedules, setSchedules] = useState<PaymentSchedule[]>([])
  const [loaded, setLoaded] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  // null = list view; 'new' = adding; <id> = editing
  const [formMode, setFormMode] = useState<'new' | string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)

  // Form fields
  const [sName, setSName] = useState('')
  const [sDesc, setSDesc] = useState('')
  const [sType, setSType] = useState('pay_in_full')
  const [sTotalAmount, setSTotalAmount] = useState('')
  const [sInstAmount, setSInstAmount] = useState('')
  const [sInstCount, setSInstCount] = useState('')
  const [sInterval, setSInterval] = useState('week')
  const [sCurrency, setSCurrency] = useState(optCurrency)
  const [sBuyerNote, setSBuyerNote] = useState('')
  const [sInternalNote, setSInternalNote] = useState('')

  async function loadSchedules() {
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/payment-options/${optionId}/schedules`),
        { credentials: 'include' },
      )
      if (!res.ok) { setLoadError('Could not load schedules.'); return }
      setSchedules(await res.json())
      setLoaded(true)
    } catch { setLoadError('Could not load schedules.') }
  }

  function toggleExpand() {
    if (!expanded && !loaded) loadSchedules()
    setExpanded(v => !v)
    setFormMode(null)
  }

  function resetSchedForm(s?: PaymentSchedule) {
    setSName(s?.name ?? '')
    setSDesc(s?.description ?? '')
    setSType(s?.schedule_type ?? 'pay_in_full')
    setSTotalAmount(s?.total_amount_cents != null ? String(s.total_amount_cents / 100) : (effectivePrice != null ? String(effectivePrice / 100) : ''))
    setSInstAmount(s?.installment_amount_cents != null ? String(s.installment_amount_cents / 100) : '')
    setSInstCount(s?.installment_count != null ? String(s.installment_count) : '')
    setSInterval(s?.interval ?? 'week')
    setSCurrency(s?.currency ?? optCurrency)
    setSBuyerNote(s?.buyer_note ?? '')
    setSInternalNote(s?.internal_note ?? '')
  }

  function openNew() { resetSchedForm(); setFormMode('new'); setSaveError(null) }
  function openEdit(s: PaymentSchedule) { resetSchedForm(s); setFormMode(s.id); setSaveError(null) }
  function closeForm() { setFormMode(null); setSaveError(null) }

  function buildSchedPayload() {
    return {
      name: sName.trim(),
      description: sDesc.trim() || null,
      schedule_type: sType,
      total_amount_cents: sTotalAmount ? Math.round(parseFloat(sTotalAmount) * 100) : null,
      installment_amount_cents: sInstAmount ? Math.round(parseFloat(sInstAmount) * 100) : null,
      installment_count: sInstCount ? parseInt(sInstCount) : null,
      interval: sType === 'recurring_installments' ? sInterval : null,
      stripe_interval: sType === 'recurring_installments' ? (sInterval === 'fortnight' ? 'week' : sInterval) : null,
      stripe_interval_count: sType === 'recurring_installments' ? (sInterval === 'fortnight' ? 2 : 1) : null,
      currency: sCurrency,
      buyer_note: sBuyerNote.trim() || null,
      internal_note: sInternalNote.trim() || null,
    }
  }

  async function handleCreate() {
    if (!sName.trim()) { setSaveError('Name is required.'); return }
    setSaving(true); setSaveError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/payment-options/${optionId}/schedules`),
        { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...buildSchedPayload(), status: 'draft' }) },
      )
      if (!res.ok) { const b = await res.json().catch(() => ({})); setSaveError((b as {detail?: string}).detail ?? 'Could not create schedule.'); return }
      await loadSchedules(); closeForm()
    } catch { setSaveError('Could not create schedule.') }
    finally { setSaving(false) }
  }

  async function handleUpdate(schedId: string) {
    if (!sName.trim()) { setSaveError('Name is required.'); return }
    setSaving(true); setSaveError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/payment-options/${optionId}/schedules/${schedId}`),
        { method: 'PATCH', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(buildSchedPayload()) },
      )
      if (!res.ok) { const b = await res.json().catch(() => ({})); setSaveError((b as {detail?: string}).detail ?? 'Could not save changes.'); return }
      await loadSchedules(); closeForm()
    } catch { setSaveError('Could not save changes.') }
    finally { setSaving(false) }
  }

  async function handleStatusChange(schedId: string, newStatus: string) {
    try {
      await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/payment-options/${optionId}/schedules/${schedId}`),
        { method: 'PATCH', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: newStatus }) },
      )
      await loadSchedules()
    } catch { /* ignore */ }
  }

  async function handleArchive(schedId: string) {
    if (!confirm('Archive this schedule? It will no longer appear to members.')) return
    try {
      await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/payment-options/${optionId}/schedules/${schedId}`),
        { method: 'DELETE', credentials: 'include' },
      )
      await loadSchedules()
    } catch { /* ignore */ }
  }

  async function handleGenerate() {
    if (!effectivePrice || effectivePrice <= 0) { alert('This option needs a valid effective price before generating schedules.'); return }
    setGenerating(true)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/payment-options/${optionId}/schedules/generate`),
        { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ weekly_installment_count: 10, fortnightly_installment_count: 5 }) },
      )
      if (!res.ok) { const b = await res.json().catch(() => ({})); alert((b as {detail?: string}).detail ?? 'Could not generate schedules.'); return }
      await loadSchedules()
    } catch { alert('Could not generate schedules.') }
    finally { setGenerating(false) }
  }

  const isEditing = formMode !== null && formMode !== 'new'
  const editingSchedId = isEditing ? formMode : null

  function SchedForm({ schedId }: { schedId: string | null }) {
    return (
      <div className="rounded-lg border border-teal-200 bg-teal-50/30 p-3 space-y-3 mt-2">
        <p className="text-[12px] font-semibold text-navy-900">{schedId ? 'Edit schedule' : 'New schedule'}</p>
        {schedId && <p className="text-[11px] text-slate-400">Changes affect future checkouts only.</p>}

        <div className="grid gap-2 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className="mb-1 block text-[11px] font-semibold text-slate-600">Name *</label>
            <input type="text" value={sName} onChange={e => setSName(e.target.value)} placeholder="e.g. Pay in full"
              className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-[13px] outline-none focus:border-teal-400" />
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-semibold text-slate-600">Schedule type</label>
            <select value={sType} onChange={e => setSType(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[13px] outline-none focus:border-teal-400">
              <option value="pay_in_full">Pay in full</option>
              <option value="recurring_installments">Recurring instalments</option>
              <option value="manual">Manual</option>
            </select>
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-semibold text-slate-600">Currency</label>
            <select value={sCurrency} onChange={e => setSCurrency(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[13px] outline-none focus:border-teal-400">
              <option value="AUD">AUD</option>
              <option value="USD">USD</option>
              <option value="NZD">NZD</option>
            </select>
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-semibold text-slate-600">Total amount ($)</label>
            <input type="number" min="0" step="0.01" value={sTotalAmount} onChange={e => setSTotalAmount(e.target.value)}
              placeholder="e.g. 200"
              className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-[13px] outline-none focus:border-teal-400" />
          </div>
          {sType === 'recurring_installments' && (
            <>
              <div>
                <label className="mb-1 block text-[11px] font-semibold text-slate-600">Instalment amount ($)</label>
                <input type="number" min="0" step="0.01" value={sInstAmount} onChange={e => setSInstAmount(e.target.value)}
                  placeholder="e.g. 20"
                  className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-[13px] outline-none focus:border-teal-400" />
              </div>
              <div>
                <label className="mb-1 block text-[11px] font-semibold text-slate-600">Number of instalments</label>
                <input type="number" min="1" value={sInstCount} onChange={e => setSInstCount(e.target.value)}
                  placeholder="e.g. 10"
                  className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-[13px] outline-none focus:border-teal-400" />
              </div>
              <div>
                <label className="mb-1 block text-[11px] font-semibold text-slate-600">Interval</label>
                <select value={sInterval} onChange={e => setSInterval(e.target.value)}
                  className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[13px] outline-none focus:border-teal-400">
                  <option value="week">Weekly</option>
                  <option value="fortnight">Fortnightly</option>
                  <option value="month">Monthly</option>
                </select>
              </div>
            </>
          )}
          <div className="sm:col-span-2">
            <label className="mb-1 block text-[11px] font-semibold text-slate-600">Member-facing note</label>
            <input type="text" value={sBuyerNote} onChange={e => setSBuyerNote(e.target.value)}
              placeholder="Short note shown at checkout"
              className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-[13px] outline-none focus:border-teal-400" />
          </div>
          <div className="sm:col-span-2">
            <label className="mb-1 block text-[11px] font-semibold text-slate-600">Internal note</label>
            <input type="text" value={sInternalNote} onChange={e => setSInternalNote(e.target.value)}
              placeholder="Not shown to members"
              className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-[13px] outline-none focus:border-teal-400" />
          </div>
        </div>

        {saveError && <p className="text-[11px] text-red-600">{saveError}</p>}

        <div className="flex gap-2">
          <button type="button" onClick={schedId ? () => handleUpdate(schedId) : handleCreate} disabled={saving}
            className="rounded-lg px-3 py-1.5 text-[12px] font-semibold text-white disabled:opacity-50"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}>
            {saving ? 'Saving…' : schedId ? 'Save changes' : 'Save as draft'}
          </button>
          <button type="button" onClick={closeForm}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[12px] font-medium text-slate-600 transition-colors hover:bg-slate-50">
            Cancel
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="mt-3 border-t border-slate-100 pt-3">
      <button type="button" onClick={toggleExpand}
        className="flex items-center gap-1.5 text-[12px] font-semibold text-teal-700 hover:text-teal-800">
        <span>{expanded ? '▾' : '▸'}</span>
        Payment schedules
        {loaded && schedules.length > 0 && (
          <span className="rounded-full bg-teal-100 px-1.5 py-0.5 text-[10px] text-teal-700">{schedules.length}</span>
        )}
      </button>

      {expanded && (
        <div className="mt-2 space-y-2">
          {loadError && <p className="text-[11px] text-red-600">{loadError}</p>}

          {formMode === 'new' && <SchedForm schedId={null} />}

          {schedules.map(s => (
            <div key={s.id}>
              {editingSchedId === s.id ? (
                <SchedForm schedId={s.id} />
              ) : (
                <div className="rounded-lg border border-slate-100 bg-white px-3 py-2 text-[12px]">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-1.5">
                        <span className="font-semibold text-navy-900">{s.name}</span>
                        <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold ${
                          s.status === 'published' ? 'bg-teal-100 text-teal-700'
                          : s.status === 'archived' ? 'bg-slate-200 text-slate-500'
                          : 'bg-amber-100 text-amber-700'
                        }`}>{s.status}</span>
                        <span className="text-slate-400">({scheduleTypeLabel(s.schedule_type)})</span>
                      </div>
                      <div className="mt-0.5 flex flex-wrap gap-2 text-slate-500">
                        {s.total_amount_cents != null && <span>Total: {fmtOptionPrice(s.total_amount_cents, s.currency)}</span>}
                        {s.installment_count != null && s.installment_amount_cents != null && (
                          <span>{s.installment_count} × {fmtOptionPrice(s.installment_amount_cents, s.currency)} {s.interval}</span>
                        )}
                      </div>
                    </div>
                    {formMode === null && (
                      <div className="flex shrink-0 flex-col gap-1 items-end">
                        {s.status !== 'archived' && (
                          <button type="button" onClick={() => openEdit(s)}
                            className="text-[10px] font-semibold text-slate-500 hover:text-navy-900">Edit</button>
                        )}
                        {s.status === 'draft' && (
                          <button type="button" onClick={() => handleStatusChange(s.id, 'published')}
                            className="text-[10px] font-semibold text-teal-700 hover:text-teal-800">Publish</button>
                        )}
                        {s.status === 'published' && (
                          <button type="button" onClick={() => handleStatusChange(s.id, 'draft')}
                            className="text-[10px] text-slate-500 hover:text-slate-700">Unpublish</button>
                        )}
                        {s.status !== 'archived' && (
                          <button type="button" onClick={() => handleArchive(s.id)}
                            className="text-[10px] text-slate-400 hover:text-red-500">Archive</button>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}

          {schedules.length === 0 && formMode === null && !loadError && (
            <p className="text-[12px] text-slate-400">No schedules yet.</p>
          )}

          {formMode === null && (
            <div className="flex gap-2 pt-1">
              <button type="button" onClick={openNew}
                className="rounded-lg border border-teal-200 bg-white px-2 py-1 text-[11px] font-semibold text-teal-700 transition-colors hover:bg-teal-50">
                + Add schedule
              </button>
              <button type="button" onClick={handleGenerate} disabled={generating}
                className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-50">
                {generating ? 'Generating…' : '⚡ Generate standard'}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function resetFormFields(
  setters: {
    setName: (v: string) => void
    setDescription: (v: string) => void
    setPaymentType: (v: string) => void
    setSessionsPerWeek: (v: string) => void
    setTotalSessions: (v: string) => void
    setPricePerSession: (v: string) => void
    setOverrideTotal: (v: string) => void
    setTermStart: (v: string) => void
    setTermEnd: (v: string) => void
    setCurrency: (v: string) => void
    setBuyerNote: (v: string) => void
    setInternalNote: (v: string) => void
  },
  opt?: PaymentOption,
) {
  setters.setName(opt?.name ?? '')
  setters.setDescription(opt?.description ?? '')
  setters.setPaymentType(opt?.payment_type ?? 'one_time')
  setters.setSessionsPerWeek(opt?.sessions_per_week != null ? String(opt.sessions_per_week) : '')
  setters.setTotalSessions(opt?.total_sessions != null ? String(opt.total_sessions) : '')
  setters.setPricePerSession(opt?.price_per_session_cents != null ? String(opt.price_per_session_cents / 100) : '')
  setters.setOverrideTotal(opt?.override_total_cents != null ? String(opt.override_total_cents / 100) : '')
  setters.setTermStart(opt?.term_start_date ?? '')
  setters.setTermEnd(opt?.term_end_date ?? '')
  setters.setCurrency(opt?.currency ?? 'AUD')
  setters.setBuyerNote(opt?.buyer_note ?? '')
  setters.setInternalNote(opt?.internal_note ?? '')
}

function PaymentOptionsSection({ spaceSlug, pathwaySlug }: { spaceSlug: string; pathwaySlug: string }) {
  const [options, setOptions] = useState<PaymentOption[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  // null = no form open; 'new' = adding; <id> = editing that option
  const [formMode, setFormMode] = useState<'new' | string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  // Shared form state (used for both add and edit)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [paymentType, setPaymentType] = useState('one_time')
  const [sessionsPerWeek, setSessionsPerWeek] = useState('')
  const [totalSessions, setTotalSessions] = useState('')
  const [pricePerSession, setPricePerSession] = useState('')
  const [overrideTotal, setOverrideTotal] = useState('')
  const [termStart, setTermStart] = useState('')
  const [termEnd, setTermEnd] = useState('')
  const [currency, setCurrency] = useState('AUD')
  const [buyerNote, setBuyerNote] = useState('')
  const [internalNote, setInternalNote] = useState('')

  const fieldSetters = { setName, setDescription, setPaymentType, setSessionsPerWeek, setTotalSessions, setPricePerSession, setOverrideTotal, setTermStart, setTermEnd, setCurrency, setBuyerNote, setInternalNote }

  async function load() {
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/payment-options`),
        { credentials: 'include' },
      )
      if (!res.ok) { setLoadError('Could not load payment options.'); return }
      setOptions(await res.json())
    } catch { setLoadError('Could not load payment options.') }
  }

  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function openNew() {
    resetFormFields(fieldSetters)
    setFormMode('new')
    setSaveError(null)
  }

  function openEdit(opt: PaymentOption) {
    resetFormFields(fieldSetters, opt)
    setFormMode(opt.id)
    setSaveError(null)
  }

  function closeForm() {
    setFormMode(null)
    setSaveError(null)
  }

  function buildPayload() {
    const payload: Record<string, unknown> = {
      name: name.trim(),
      description: description.trim() || null,
      payment_type: paymentType,
      currency,
      buyer_note: buyerNote.trim() || null,
      internal_note: internalNote.trim() || null,
      sessions_per_week: sessionsPerWeek ? parseInt(sessionsPerWeek) : null,
      total_sessions: totalSessions ? parseInt(totalSessions) : null,
      price_per_session_cents: pricePerSession ? Math.round(parseFloat(pricePerSession) * 100) : null,
      override_total_cents: overrideTotal ? Math.round(parseFloat(overrideTotal) * 100) : null,
      term_start_date: termStart || null,
      term_end_date: termEnd || null,
    }
    return payload
  }

  async function handleCreate() {
    if (!name.trim()) { setSaveError('Name is required.'); return }
    setSaving(true); setSaveError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/payment-options`),
        { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...buildPayload(), status: 'draft' }) },
      )
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        setSaveError(typeof b.detail === 'string' ? b.detail : 'Could not create option.')
        return
      }
      await load()
      closeForm()
    } catch { setSaveError('Could not create option.') }
    finally { setSaving(false) }
  }

  async function handleUpdate(optId: string) {
    if (!name.trim()) { setSaveError('Name is required.'); return }
    setSaving(true); setSaveError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/payment-options/${optId}`),
        { method: 'PATCH', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(buildPayload()) },
      )
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        setSaveError(typeof b.detail === 'string' ? b.detail : 'Could not save changes.')
        return
      }
      await load()
      closeForm()
    } catch { setSaveError('Could not save changes.') }
    finally { setSaving(false) }
  }

  async function handleStatusChange(optId: string, newStatus: string) {
    try {
      await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/payment-options/${optId}`),
        { method: 'PATCH', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: newStatus }) },
      )
      await load()
    } catch { /* ignore */ }
  }

  async function handleArchive(optId: string) {
    if (!confirm('Archive this payment option? It will no longer appear to members.')) return
    try {
      await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/payment-options/${optId}`),
        { method: 'DELETE', credentials: 'include' },
      )
      await load()
    } catch { /* ignore */ }
  }

  const isEditing = formMode !== null && formMode !== 'new'
  const editingOptId = isEditing ? formMode : null

  function OptionForm({ optId }: { optId: string | null }) {
    return (
      <div className="rounded-xl border border-teal-200 bg-teal-50/30 p-4 space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-[13px] font-semibold text-navy-900">
            {optId ? 'Edit payment option' : 'New payment option'}
          </p>
          {optId && (
            <p className="text-[11px] text-slate-400">Changes affect future checkouts only. Existing purchases are not changed.</p>
          )}
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className="mb-1 block text-[12px] font-semibold text-slate-600">Name *</label>
            <input
              type="text" value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Awaken — 1 session per week"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] outline-none focus:border-teal-400"
            />
          </div>

          <div className="sm:col-span-2">
            <label className="mb-1 block text-[12px] font-semibold text-slate-600">Description</label>
            <input
              type="text" value={description} onChange={e => setDescription(e.target.value)} placeholder="Optional short description"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] outline-none focus:border-teal-400"
            />
          </div>

          <div>
            <label className="mb-1 block text-[12px] font-semibold text-slate-600">Payment type</label>
            <select value={paymentType} onChange={e => setPaymentType(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] outline-none focus:border-teal-400">
              <option value="one_time">One-time</option>
              <option value="term_pass">Term pass</option>
              <option value="free">Free</option>
            </select>
          </div>

          <div>
            <label className="mb-1 block text-[12px] font-semibold text-slate-600">Currency</label>
            <select value={currency} onChange={e => setCurrency(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] outline-none focus:border-teal-400">
              <option value="AUD">AUD</option>
              <option value="USD">USD</option>
              <option value="NZD">NZD</option>
            </select>
          </div>

          <div>
            <label className="mb-1 block text-[12px] font-semibold text-slate-600">Sessions/week</label>
            <input type="number" min="1" value={sessionsPerWeek} onChange={e => setSessionsPerWeek(e.target.value)}
              placeholder="e.g. 1"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] outline-none focus:border-teal-400" />
          </div>

          <div>
            <label className="mb-1 block text-[12px] font-semibold text-slate-600">Total sessions</label>
            <input type="number" min="1" value={totalSessions} onChange={e => setTotalSessions(e.target.value)}
              placeholder="e.g. 10"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] outline-none focus:border-teal-400" />
          </div>

          <div>
            <label className="mb-1 block text-[12px] font-semibold text-slate-600">Price per session ($)</label>
            <input type="number" min="0" step="0.01" value={pricePerSession} onChange={e => setPricePerSession(e.target.value)}
              placeholder="e.g. 20"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] outline-none focus:border-teal-400" />
          </div>

          <div>
            <label className="mb-1 block text-[12px] font-semibold text-slate-600">Override total ($)</label>
            <input type="number" min="0" step="0.01" value={overrideTotal} onChange={e => setOverrideTotal(e.target.value)}
              placeholder="Leave blank to use calculated"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] outline-none focus:border-teal-400" />
          </div>

          {paymentType === 'term_pass' && (
            <>
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-slate-600">Term start</label>
                <input type="date" value={termStart} onChange={e => setTermStart(e.target.value)}
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] outline-none focus:border-teal-400" />
              </div>
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-slate-600">Term end</label>
                <input type="date" value={termEnd} onChange={e => setTermEnd(e.target.value)}
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] outline-none focus:border-teal-400" />
              </div>
            </>
          )}

          <div className="sm:col-span-2">
            <label className="mb-1 block text-[12px] font-semibold text-slate-600">Member-facing note</label>
            <input type="text" value={buyerNote} onChange={e => setBuyerNote(e.target.value)}
              placeholder="Short note shown to members at checkout"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] outline-none focus:border-teal-400" />
          </div>

          <div className="sm:col-span-2">
            <label className="mb-1 block text-[12px] font-semibold text-slate-600">Internal note</label>
            <input type="text" value={internalNote} onChange={e => setInternalNote(e.target.value)}
              placeholder="Not shown to members"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] outline-none focus:border-teal-400" />
          </div>
        </div>

        {saveError && <p className="text-[12px] text-red-600">{saveError}</p>}

        <div className="flex gap-2">
          <button
            type="button"
            onClick={optId ? () => handleUpdate(optId) : handleCreate}
            disabled={saving}
            className="rounded-lg px-4 py-2 text-[13px] font-semibold text-white disabled:opacity-50"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            {saving ? 'Saving…' : optId ? 'Save changes' : 'Save as draft'}
          </button>
          <button type="button" onClick={closeForm}
            className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-[13px] font-medium text-slate-600 transition-colors hover:bg-slate-50">
            Cancel
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-2xl border border-border bg-white p-6">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-[15px] font-semibold text-navy-900">Payment options</h2>
          <p className="mt-1 text-[13px] leading-relaxed text-slate-500">
            Create tiered or term-based pricing options for this pathway.
            Published options appear on the checkout page for members to choose from.
          </p>
        </div>
        {formMode === null && (
          <button
            type="button"
            onClick={openNew}
            className="shrink-0 rounded-xl border border-teal-200 bg-teal-50 px-3 py-1.5 text-[12px] font-semibold text-teal-700 transition-colors hover:bg-teal-100"
          >
            + Add option
          </button>
        )}
      </div>

      {/* Phase A notice */}
      <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-[12px] text-amber-800">
        <strong>Phase A:</strong> Booking limits are not enforced yet. Session counts are shown to members for transparency but do not restrict access.
      </div>

      {loadError && <p className="mb-3 text-[12px] text-red-600">{loadError}</p>}

      {/* New option form */}
      {formMode === 'new' && <div className="mb-4"><OptionForm optId={null} /></div>}

      {/* Existing options */}
      {options.length > 0 && (
        <div className="mb-4 space-y-3">
          {options.map(opt => (
            <div key={opt.id}>
              {editingOptId === opt.id ? (
                <OptionForm optId={opt.id} />
              ) : (
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-[14px] font-semibold text-navy-900">{opt.name}</span>
                        <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${
                          opt.status === 'published' ? 'bg-teal-100 text-teal-700'
                          : opt.status === 'archived' ? 'bg-slate-200 text-slate-500'
                          : 'bg-amber-100 text-amber-700'
                        }`}>
                          {opt.status}
                        </span>
                      </div>
                      {opt.description && <p className="mt-0.5 text-[12px] text-slate-500">{opt.description}</p>}
                      <div className="mt-2 flex flex-wrap gap-3 text-[12px] text-slate-500">
                        <span>Type: {opt.payment_type}</span>
                        {opt.sessions_per_week != null && <span>{opt.sessions_per_week}×/week</span>}
                        {opt.total_sessions != null && <span>{opt.total_sessions} sessions</span>}
                        {opt.price_per_session_cents != null && (
                          <span>{fmtOptionPrice(opt.price_per_session_cents, opt.currency)}/session</span>
                        )}
                        {opt.term_end_date && <span>Until {opt.term_end_date}</span>}
                      </div>
                      <div className="mt-1 text-[13px] font-semibold text-navy-900">
                        Effective price: {fmtOptionPrice(opt.effective_price_cents, opt.currency)}
                        {opt.calculated_total_cents != null && opt.override_total_cents != null && (
                          <span className="ml-1 text-[11px] font-normal text-slate-400">
                            (override; calculated {fmtOptionPrice(opt.calculated_total_cents, opt.currency)})
                          </span>
                        )}
                      </div>
                      {opt.internal_note && (
                        <p className="mt-1 text-[11px] italic text-slate-400">Note: {opt.internal_note}</p>
                      )}
                    </div>
                    <div className="flex shrink-0 flex-col gap-1.5 items-end">
                      {opt.status !== 'archived' && formMode === null && (
                        <button
                          type="button"
                          onClick={() => openEdit(opt)}
                          className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-slate-600 transition-colors hover:bg-slate-50"
                        >
                          Edit
                        </button>
                      )}
                      {opt.status === 'draft' && formMode === null && (
                        <button
                          type="button"
                          onClick={() => handleStatusChange(opt.id, 'published')}
                          className="rounded-lg border border-teal-200 bg-white px-2 py-1 text-[11px] font-semibold text-teal-700 transition-colors hover:bg-teal-50"
                        >
                          Publish
                        </button>
                      )}
                      {opt.status === 'published' && formMode === null && (
                        <button
                          type="button"
                          onClick={() => handleStatusChange(opt.id, 'draft')}
                          className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-slate-600 transition-colors hover:bg-slate-50"
                        >
                          Unpublish
                        </button>
                      )}
                      {opt.status !== 'archived' && formMode === null && (
                        <button
                          type="button"
                          onClick={() => handleArchive(opt.id)}
                          className="rounded-lg px-2 py-1 text-[11px] text-slate-400 transition-colors hover:text-red-500"
                        >
                          Archive
                        </button>
                      )}
                    </div>
                  </div>
                  {/* Nested payment schedules */}
                  {opt.status !== 'archived' && (
                    <PaymentSchedulesSection
                      spaceSlug={spaceSlug}
                      pathwaySlug={pathwaySlug}
                      optionId={opt.id}
                      effectivePrice={opt.effective_price_cents}
                      currency={opt.currency}
                    />
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {options.length === 0 && formMode === null && (
        <p className="text-[13px] text-slate-400">No payment options yet. Add one above.</p>
      )}
    </div>
  )
}

export default function EditPathwayClient({ pathway, steps: initialSteps, sections: initialSections, spaceSlug }: Props) {
  const router = useRouter()
  const [, startTransition] = useTransition()

  const [title, setTitle]               = useState(pathway.title)
  const [description, setDescription]   = useState(pathway.description ?? '')
  const [practiceBody, setPracticeBody] = useState(pathway.practice_body ?? '')
  const [status, setStatus]             = useState<string>(pathway.status)
  const [accessType, setAccessType]     = useState<string>(pathway.access_type ?? 'free')
  const [pricingMode, setPricingMode]   = useState<string>(pathway.pricing_mode ?? 'legacy')
  const [priceDollars, setPriceDollars] = useState(centsToDisplay(pathway.price_cents))
  const [currency, setCurrency]         = useState(pathway.currency ?? 'AUD')
  const [loading, setLoading]           = useState(false)
  const [saved, setSaved]               = useState(false)
  const [error, setError]               = useState<string | null>(null)
  const [priceError, setPriceError]     = useState<string | null>(null)
  const [steps, setSteps]               = useState<CreatorStep[]>(initialSteps)
  const [sections, setSections]         = useState<CreatorSection[]>(initialSections)

  const [coverUrl, setCoverUrl]             = useState<string | null>(pathway.cover_image_url ?? null)
  const [coverPreview, setCoverPreview]     = useState<string | null>(null)
  const [coverFile, setCoverFile]           = useState<File | null>(null)
  const [coverUploading, setCoverUploading] = useState(false)
  const [coverError, setCoverError]         = useState<string | null>(null)
  const [coverSaved, setCoverSaved]         = useState(false)

  const isPaid = accessType === 'one_time' || accessType === 'subscription'
  const needsSinglePrice = isPaid && pricingMode === 'legacy'

  function validate(): boolean {
    if (!title.trim()) { setError('Pathway title is required.'); return false }
    if (needsSinglePrice) {
      const dollars = parseFloat(priceDollars)
      if (!priceDollars.trim() || isNaN(dollars)) { setPriceError('Enter a price for this paid pathway.'); return false }
      if (dollars <= 0) { setPriceError('Price must be greater than 0.'); return false }
    }
    return true
  }

  async function handleSave() {
    setError(null)
    setPriceError(null)
    setSaved(false)
    if (!validate()) return
    const priceCents = needsSinglePrice ? Math.round(parseFloat(priceDollars) * 100) : null
    setLoading(true)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}`),
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            title: title.trim(),
            description: description.trim() || null,
            practice_body: practiceBody.trim() || null,
            status,
            access_type: accessType,
            pricing_mode: pricingMode,
            price_cents: priceCents,
            currency: needsSinglePrice ? currency : 'AUD',
            billing_interval: accessType === 'subscription' ? 'month' : null,
          }),
        },
      )
      if (!res.ok) {
        let detail: string | null = null
        try { const b = await res.json(); if (typeof b.detail === 'string') detail = b.detail } catch { /* ignore */ }
        setError(detail ?? 'Could not save changes. Please try again.')
        return
      }
      setSaved(true)
      startTransition(() => { router.refresh() })
      setTimeout(() => setSaved(false), 3000)
    } catch {
      setError('Could not save changes. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-8">

      {/* ── Two-column grid: form content left, settings/cover right ── */}
      <div className="grid gap-6 lg:grid-cols-[1fr_360px]">

        {/* LEFT — title, description, practice body, save */}
        <div className="rounded-2xl border border-border bg-white p-6">
          <div className="space-y-5">

            <div>
              <label className="mb-1 block text-[12px] font-semibold text-slate-600">
                Pathway title <span className="font-normal text-slate-400">(required)</span>
              </label>
              <input
                type="text" value={title}
                onChange={(e) => { setTitle(e.target.value); setError(null) }}
                placeholder="e.g. Slow Growth Practice"
                className={`w-full rounded-lg border px-3 py-2.5 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400 ${error && !title.trim() ? 'border-red-300' : 'border-slate-200'}`}
              />
            </div>

            <div>
              <label className="mb-1 block text-[12px] font-semibold text-slate-600">
                Short description <span className="font-normal text-slate-400">(optional)</span>
              </label>
              <input
                type="text" value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="A guided pathway for moving slowly, reflecting honestly, and building new rhythm."
                className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400"
              />
            </div>

            <div>
              <label className="mb-1 block text-[12px] font-semibold text-slate-600">
                What will people practise? <span className="font-normal text-slate-400">(optional)</span>
              </label>
              <textarea
                value={practiceBody}
                onChange={(e) => setPracticeBody(e.target.value)}
                placeholder="Describe the shift, skill, rhythm, or experience this pathway supports."
                rows={5}
                className="w-full resize-none rounded-lg border border-slate-200 px-3 py-2.5 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400"
              />
            </div>

          </div>

          {error && <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-600">{error}</p>}
          {saved && (
            <p className="mt-4 rounded-lg px-3 py-2 text-[13px] font-medium" style={{ background: 'rgba(56,160,158,0.08)', color: '#38A09E' }}>
              Changes saved.
            </p>
          )}

          <div className="mt-6 flex justify-end border-t border-border pt-5">
            <button
              type="button"
              disabled={loading || !title.trim()}
              onClick={handleSave}
              className="rounded-xl px-6 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
            >
              {loading ? 'Saving…' : 'Save changes'}
            </button>
          </div>
        </div>

        {/* RIGHT — status, access/pricing, cover image */}
        <div className="space-y-5">

          {/* Status */}
          <div className="rounded-2xl border border-border bg-white p-5">
            <label className="mb-2 block text-[12px] font-semibold text-slate-600">Status</label>
            <select
              value={status} onChange={(e) => setStatus(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400"
            >
              <option value="draft">Draft</option>
              <option value="active">Published</option>
              <option value="coming_soon">Coming soon</option>
              <option value="archived">Archived</option>
            </select>
          </div>

          {/* Access and pricing */}
          <div className="rounded-2xl border border-border bg-white p-5">
            <AccessPricingSection
              accessType={accessType}
              setAccessType={(v) => { setAccessType(v); setPriceError(null) }}
              pricingMode={pricingMode}
              setPricingMode={(v) => { setPricingMode(v); setPriceError(null) }}
              priceDollars={priceDollars}
              setPriceDollars={(v) => { setPriceDollars(v); setPriceError(null) }}
              currency={currency}
              setCurrency={setCurrency}
              priceError={priceError}
            />
          </div>

          {/* Cover image */}
          <div className="rounded-2xl border border-border bg-white p-5">
            <h2 className="mb-0.5 text-[14px] font-semibold text-navy-900">Pathway cover</h2>
            <p className="mb-3 text-[12px] text-slate-500">
              Wide image recommended (16:9). JPG or PNG.
            </p>

            {(coverPreview ?? resolveMediaUrl(coverUrl)) && (
              <div className="mb-3 overflow-hidden rounded-xl">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={coverPreview ?? resolveMediaUrl(coverUrl)!}
                  alt="Pathway cover preview"
                  className="w-full object-cover"
                  style={{ aspectRatio: '16/9' }}
                />
              </div>
            )}

            <div className="flex flex-wrap items-center gap-2">
              <label className="cursor-pointer rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[12px] font-medium text-navy-900 transition-colors hover:border-teal-300 hover:text-teal-700">
                {coverUrl || coverPreview ? 'Replace' : 'Choose image'}
                <input
                  type="file" accept="image/jpeg,image/png" className="sr-only"
                  onChange={(e) => {
                    const f = e.target.files?.[0] ?? null
                    setCoverFile(f); setCoverError(null); setCoverSaved(false)
                    if (f) {
                      const reader = new FileReader()
                      reader.onload = (ev) => setCoverPreview(ev.target?.result as string)
                      reader.readAsDataURL(f)
                    } else { setCoverPreview(null) }
                  }}
                />
              </label>

              {coverFile && (
                <button
                  type="button" disabled={coverUploading}
                  onClick={async () => {
                    if (!coverFile) return
                    setCoverUploading(true); setCoverError(null); setCoverSaved(false)
                    const form = new FormData()
                    form.append('file', coverFile)
                    try {
                      const res = await fetch(
                        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}/cover`),
                        { method: 'POST', credentials: 'include', body: form },
                      )
                      if (!res.ok) {
                        const b = await res.json().catch(() => ({}))
                        setCoverError(typeof b.detail === 'string' ? b.detail : 'Upload failed.')
                        return
                      }
                      const data = await res.json()
                      setCoverUrl(data.cover_image_url ?? null)
                      setCoverPreview(null); setCoverFile(null); setCoverSaved(true)
                      startTransition(() => { router.refresh() })
                      setTimeout(() => setCoverSaved(false), 3000)
                    } catch {
                      setCoverError('Upload failed. Please try again.')
                    } finally { setCoverUploading(false) }
                  }}
                  className="rounded-lg px-3 py-1.5 text-[12px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
                  style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
                >
                  {coverUploading ? 'Uploading…' : 'Upload'}
                </button>
              )}
            </div>

            {coverError && <p className="mt-2 text-[12px] text-red-600">{coverError}</p>}
            {coverSaved && <p className="mt-2 text-[12px] font-medium" style={{ color: '#38A09E' }}>Cover saved.</p>}
          </div>

        </div>
      </div>

      {/* ── About page — full width ── */}
      <div className="rounded-2xl border border-border bg-white p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-[15px] font-semibold text-navy-900">Pathway about page</h2>
            <p className="mt-1 text-[13px] leading-relaxed text-slate-500">
              Build the page people see before they start or unlock this pathway.
              Add rich content, images, video, and a clear call to action.
            </p>
          </div>
          <Link
            href={`/creator-studio/pathways/${pathway.slug}/about`}
            className="shrink-0 rounded-xl border border-border bg-white px-4 py-2 text-[13px] font-medium text-teal-700 transition-colors hover:border-teal-200 hover:bg-teal-50"
          >
            Edit about page →
          </Link>
        </div>
      </div>

      {/* ── Payment options — full width ── */}
      <PaymentOptionsSection spaceSlug={spaceSlug} pathwaySlug={pathway.slug} />

      {/* ── Pathway structure — full width ── */}
      <PathwayStructure
        pathway={pathway}
        steps={steps}
        sections={sections}
        spaceSlug={spaceSlug}
        setSteps={setSteps}
        setSections={setSections}
      />

    </div>
  )
}
