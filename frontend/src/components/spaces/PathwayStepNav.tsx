'use client'

import { useState } from 'react'
import Link from 'next/link'
import type { PathwaySection, StepSummary } from '@/types/platform'

const CONTENT_TYPE_LABEL: Record<string, string> = {
  text:       'Read',
  reflection: 'Reflect',
  exercise:   'Exercise',
  video:      'Watch',
  audio:      'Listen',
}

interface Props {
  pathwayTitle: string
  pathwayHref: string
  steps: StepSummary[]
  sections: PathwaySection[]
  currentStepSlug: string
  spaceSlug: string
  pathwaySlug: string
  completedCount: number
  totalCount: number
}

// ---------------------------------------------------------------------------
// Single step row — shared by both mobile and desktop renders
// ---------------------------------------------------------------------------

function StepNavItem({
  step,
  index,
  isActive,
  href,
}: {
  step: StepSummary
  index: number
  isActive: boolean
  href: string
}) {
  const typeLabel = CONTENT_TYPE_LABEL[step.content_type] ?? step.content_type

  return (
    <li>
      <Link
        href={href}
        aria-current={isActive ? 'page' : undefined}
        className={`group flex items-start gap-2.5 rounded-xl px-3 py-2.5 transition-colors ${
          isActive ? 'bg-teal-50' : 'hover:bg-slate-50'
        }`}
      >
        {/* Step indicator */}
        <span
          aria-hidden="true"
          className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${
            isActive
              ? 'bg-teal-500 text-white'
              : step.is_completed
                ? 'bg-teal-100 text-teal-600'
                : 'bg-slate-100 text-slate-500'
          }`}
        >
          {step.is_completed && !isActive ? '✓' : index + 1}
        </span>

        {/* Text */}
        <div className="min-w-0">
          <p
            className={`text-[13px] leading-snug ${
              isActive
                ? 'font-semibold text-navy-900'
                : step.is_completed
                  ? 'text-slate-400'
                  : 'text-navy-900 group-hover:text-teal-700'
            }`}
          >
            {step.title}
          </p>
          <p className="mt-0.5 text-[11px] text-slate-400">
            {typeLabel}
            {step.estimated_minutes ? ` · ${step.estimated_minutes} min` : ''}
          </p>
        </div>
      </Link>
    </li>
  )
}

// ---------------------------------------------------------------------------
// Progress bar (shared)
// ---------------------------------------------------------------------------

function ProgressBar({
  completedCount,
  totalCount,
  progressPct,
}: {
  completedCount: number
  totalCount: number
  progressPct: number
}) {
  return (
    <>
      <div className="mb-1 flex items-center justify-between text-[11px] text-slate-400">
        <span>{completedCount} of {totalCount} complete</span>
        <span>{progressPct}%</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-teal-100">
        <div
          className="h-full rounded-full bg-teal-500 transition-all duration-500"
          style={{ width: `${progressPct}%` }}
        />
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// Collapsible section group
// ---------------------------------------------------------------------------

function SectionGroup({
  section,
  globalOffset,
  currentStepSlug,
  spaceSlug,
  pathwaySlug,
}: {
  section: PathwaySection
  globalOffset: number
  currentStepSlug: string
  spaceSlug: string
  pathwaySlug: string
}) {
  const hasActiveStep = section.steps.some((s) => s.slug === currentStepSlug)
  const [open, setOpen] = useState<boolean>(hasActiveStep)
  const sectionCompleted = section.steps.filter((s) => s.is_completed).length

  return (
    <li>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left hover:bg-slate-50 transition-colors"
      >
        <div className="min-w-0">
          <span className="block text-[12px] font-semibold text-slate-600 leading-snug">
            {section.title}
          </span>
          <span className="text-[11px] text-slate-400">
            {sectionCompleted} of {section.steps.length} complete
          </span>
        </div>
        <svg
          className={`ml-2 h-3.5 w-3.5 shrink-0 text-slate-400 transition-transform ${open ? '' : '-rotate-90'}`}
          fill="none"
          viewBox="0 0 12 12"
          aria-hidden="true"
        >
          <path d="M2 4l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <ul className="ml-2 mt-0.5 space-y-0.5 border-l border-slate-100 pl-2">
          {section.steps.map((step, i) => (
            <StepNavItem
              key={step.id}
              step={step}
              index={globalOffset + i}
              isActive={step.slug === currentStepSlug}
              href={`/spaces/${spaceSlug}/pathways/${pathwaySlug}/${step.slug}`}
            />
          ))}
        </ul>
      )}
    </li>
  )
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export default function PathwayStepNav({
  pathwayTitle,
  pathwayHref,
  steps,
  sections,
  currentStepSlug,
  spaceSlug,
  pathwaySlug,
  completedCount,
  totalCount,
}: Props) {
  const [mobileOpen, setMobileOpen] = useState(false)
  const progressPct = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0
  const currentIndex = steps.findIndex((s) => s.slug === currentStepSlug)

  const hasSections = sections.length > 0

  // Unsectioned steps (steps with no section or pathway has no sections)
  const sectionedStepIds = new Set(sections.flatMap((sec) => sec.steps.map((s) => s.id)))
  const unsectionedSteps = steps.filter((s) => !sectionedStepIds.has(s.id))

  // Build section-grouped list: sections first (in position order), unsectioned steps last
  const buildSectionList = () => {
    const items: React.ReactNode[] = []
    let offset = 0

    sections.forEach((sec) => {
      items.push(
        <SectionGroup
          key={sec.id}
          section={sec}
          globalOffset={offset}
          currentStepSlug={currentStepSlug}
          spaceSlug={spaceSlug}
          pathwaySlug={pathwaySlug}
        />
      )
      offset += sec.steps.length
    })

    // Unsectioned steps at the bottom (if any)
    if (unsectionedSteps.length > 0) {
      if (sections.length > 0) {
        items.push(
          <li key="__unsectioned-label" className="px-3 pt-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Other</span>
          </li>
        )
      }
      unsectionedSteps.forEach((step, i) => {
        items.push(
          <StepNavItem
            key={step.id}
            step={step}
            index={offset + i}
            isActive={step.slug === currentStepSlug}
            href={`/spaces/${spaceSlug}/pathways/${pathwaySlug}/${step.slug}`}
          />
        )
      })
    }

    return items
  }

  const flatStepList = (
    <ul className="space-y-0.5">
      {steps.map((step, i) => (
        <StepNavItem
          key={step.id}
          step={step}
          index={i}
          isActive={step.slug === currentStepSlug}
          href={`/spaces/${spaceSlug}/pathways/${pathwaySlug}/${step.slug}`}
        />
      ))}
    </ul>
  )

  const stepList = hasSections ? (
    <ul className="space-y-1">{buildSectionList()}</ul>
  ) : flatStepList

  return (
    <>
      {/* ──────────────────────────────────────────────────────────────────────
          Mobile: collapsible "Pathway steps" button (hidden on ≥lg screens)
      ────────────────────────────────────────────────────────────────────── */}
      <div className="lg:hidden">
        <button
          type="button"
          onClick={() => setMobileOpen((v) => !v)}
          className="flex w-full items-center justify-between rounded-xl border border-slate-200 bg-white px-4 py-3 text-left shadow-sm"
        >
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-teal-600">
              {pathwayTitle}
            </p>
            <p className="mt-0.5 text-[13px] font-medium text-navy-900">
              Step {currentIndex + 1} of {totalCount}
              {completedCount > 0 && (
                <span className="ml-2 text-[12px] font-normal text-slate-400">
                  · {completedCount} complete
                </span>
              )}
            </p>
          </div>
          <svg
            className={`h-4 w-4 shrink-0 text-slate-400 transition-transform ${mobileOpen ? 'rotate-180' : ''}`}
            fill="none"
            viewBox="0 0 16 16"
            aria-hidden="true"
          >
            <path
              d="M3 6l5 5 5-5"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>

        {mobileOpen && (
          <div className="mt-1 overflow-hidden rounded-xl border border-slate-100 bg-white shadow-sm">
            <div className="border-b border-slate-100 px-4 py-3">
              <ProgressBar completedCount={completedCount} totalCount={totalCount} progressPct={progressPct} />
            </div>
            <div className="p-2">{stepList}</div>
          </div>
        )}
      </div>

      {/* ──────────────────────────────────────────────────────────────────────
          Desktop: sticky left sidebar (hidden on <lg screens)
      ────────────────────────────────────────────────────────────────────── */}
      <div className="hidden lg:block">
        <div className="sticky top-6 overflow-hidden rounded-2xl border border-slate-100 bg-white shadow-sm">

          {/* Header: back link + progress */}
          <div className="border-b border-slate-100 px-4 py-4">
            <Link
              href={pathwayHref}
              className="mb-3 inline-block text-[12px] font-medium text-slate-400 transition-colors hover:text-teal-600"
            >
              ← {pathwayTitle}
            </Link>
            <ProgressBar completedCount={completedCount} totalCount={totalCount} progressPct={progressPct} />
          </div>

          {/* Step list — scrollable when the pathway is long */}
          <div
            className="overflow-y-auto p-2"
            style={{ maxHeight: 'calc(100vh - 14rem)' }}
          >
            {stepList}
          </div>

        </div>
      </div>
    </>
  )
}
