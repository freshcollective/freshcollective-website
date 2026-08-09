'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import type { KnowledgeGuideStep } from '@/types/platform'
import type { KnowledgeGuideChapter } from '@/components/spaces/knowledgeGuideChapters'

/**
 * KnowledgeGuideNav — persistent guide navigation.
 *
 * Desktop: sticky sidebar. Chapter titles are top-level entries;
 * each chapter's step titles nest beneath and are always visible so
 * a member can jump straight to the piece of information they need.
 * The active chapter (from ``?section=``) is highlighted; the step
 * currently in view within that chapter is highlighted via an
 * IntersectionObserver watching the rendered step blocks.
 *
 * Mobile: the sidebar is replaced by a native ``<select>`` chapter
 * dropdown at the top of the reading pane. Scales to any number of
 * chapters and reveals every option in one tap.
 *
 * Flat mode (no named sections): the sidebar shows the flat step
 * list. No dropdown, no chapter concept.
 */

interface Props {
  chapters: KnowledgeGuideChapter[]
  activeChapterSlug: string | null
  spaceSlug: string
  pathwaySlug: string
  flat: boolean
  flatSteps: KnowledgeGuideStep[]
}

export default function KnowledgeGuideNav({
  chapters,
  activeChapterSlug,
  spaceSlug,
  pathwaySlug,
  flat,
  flatSteps,
}: Props) {
  const router = useRouter()
  const [activeStepSlug, setActiveStepSlug] = useState<string | null>(null)

  // Track which step is currently in view within the active chapter.
  // Runs when the active chapter changes (chapter switch = new step
  // set to observe). Also seeds from the URL hash on mount so the
  // right entry is highlighted immediately after a step deep link.
  const observedStepSlugs = flat
    ? flatSteps.map((s) => s.slug)
    : chapters.find((c) => c.slug === activeChapterSlug)?.steps.map((s) => s.slug) ?? []

  useEffect(() => {
    if (observedStepSlugs.length === 0) {
      setActiveStepSlug(null)
      return
    }
    // Seed from URL hash so deep-linked steps highlight straight away.
    const hash = window.location.hash.replace(/^#/, '')
    if (hash.startsWith('step-')) {
      const s = hash.slice('step-'.length)
      if (observedStepSlugs.includes(s)) {
        setActiveStepSlug(s)
      } else {
        setActiveStepSlug(observedStepSlugs[0])
      }
    } else {
      setActiveStepSlug(observedStepSlugs[0])
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const id = entry.target.getAttribute('id')
            if (id?.startsWith('step-')) {
              setActiveStepSlug(id.slice('step-'.length))
            }
          }
        }
      },
      { rootMargin: '-30% 0px -60% 0px', threshold: 0 },
    )
    for (const slug of observedStepSlugs) {
      const el = document.getElementById(`step-${slug}`)
      if (el) observer.observe(el)
    }
    return () => observer.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [observedStepSlugs.join('|')])

  const basePath = `/spaces/${spaceSlug}/pathways/${pathwaySlug}`

  // ── Mobile: chapter dropdown ────────────────────────────────────
  // Rendered above the desktop sidebar so on mobile it appears
  // where the reader expects it (top of content) and on desktop it
  // stays hidden. No dropdown in flat mode — nothing to switch.
  const mobileDropdown = flat ? null : (
    <div className="mb-4 lg:hidden">
      <label
        htmlFor="kg-chapter-select"
        className="mb-1.5 block text-[10.5px] font-semibold uppercase tracking-[0.16em]"
        style={{ color: 'rgba(12,24,38,0.55)' }}
      >
        In this guide
      </label>
      <select
        id="kg-chapter-select"
        value={activeChapterSlug ?? ''}
        onChange={(e) => {
          const slug = e.target.value
          if (slug) router.push(`${basePath}?section=${encodeURIComponent(slug)}`)
        }}
        className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400"
      >
        {chapters.map((c) => (
          <option key={c.slug} value={c.slug}>
            {c.title ?? '…'}
          </option>
        ))}
      </select>
    </div>
  )

  // ── Desktop: sticky sidebar ─────────────────────────────────────
  const desktopSidebar = (
    <nav
      aria-label="In this guide"
      className="sticky top-6 hidden lg:block"
    >
      <p
        className="mb-3 text-[10.5px] font-semibold uppercase tracking-[0.16em]"
        style={{ color: 'rgba(12,24,38,0.55)' }}
      >
        In this guide
      </p>

      {flat ? (
        <ul className="space-y-1">
          {flatSteps.map((s) => (
            <li key={s.id}>
              <a
                href={`#step-${s.slug}`}
                className={
                  activeStepSlug === s.slug
                    ? 'block rounded-md px-3 py-1.5 text-[13.5px] font-semibold text-teal-700'
                    : 'block rounded-md px-3 py-1.5 text-[13.5px] text-navy-800 hover:bg-slate-100'
                }
                style={
                  activeStepSlug === s.slug
                    ? { background: 'rgba(56,160,158,0.10)' }
                    : undefined
                }
              >
                {s.title}
              </a>
            </li>
          ))}
        </ul>
      ) : (
        <ul className="space-y-4">
          {chapters.map((chapter) => {
            const isActive = chapter.slug === activeChapterSlug
            return (
              <li key={chapter.slug}>
                {/* Chapter title. Hidden entirely for the orphan
                    bucket — its steps sit under a divider so the
                    reader doesn't see an invented group heading. */}
                {chapter.title !== null && (
                  <Link
                    href={`${basePath}?section=${encodeURIComponent(chapter.slug)}`}
                    className={
                      isActive
                        ? 'block rounded-md px-3 py-1.5 text-[13.5px] font-semibold text-teal-700'
                        : 'block rounded-md px-3 py-1.5 text-[13.5px] font-semibold text-navy-900 hover:bg-slate-100'
                    }
                    style={
                      isActive
                        ? { background: 'rgba(56,160,158,0.10)' }
                        : undefined
                    }
                  >
                    {chapter.title}
                  </Link>
                )}

                {chapter.title === null && (
                  <div
                    className="my-2 h-px w-full"
                    style={{ background: 'rgba(12,24,38,0.10)' }}
                    aria-hidden="true"
                  />
                )}

                <ul className="mt-1 space-y-0.5 border-l border-slate-100 pl-2">
                  {chapter.steps.map((s) => {
                    const isCurrentStep = isActive && activeStepSlug === s.slug
                    return (
                      <li key={s.id}>
                        <Link
                          href={`${basePath}?section=${encodeURIComponent(chapter.slug)}#step-${s.slug}`}
                          className={
                            isCurrentStep
                              ? 'block rounded-md px-3 py-1 text-[13px] font-medium text-teal-700'
                              : 'block rounded-md px-3 py-1 text-[13px] text-navy-700 hover:bg-slate-100 hover:text-navy-900'
                          }
                          style={
                            isCurrentStep
                              ? { background: 'rgba(56,160,158,0.10)' }
                              : undefined
                          }
                        >
                          {s.title}
                        </Link>
                      </li>
                    )
                  })}
                </ul>
              </li>
            )
          })}
        </ul>
      )}
    </nav>
  )

  return (
    <>
      {mobileDropdown}
      {desktopSidebar}
    </>
  )
}
