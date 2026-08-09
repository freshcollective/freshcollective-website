'use client'

import { useEffect, useState } from 'react'
import type { KnowledgeGuideSection } from '@/types/platform'

/**
 * KnowledgeGuideNav — sticky chapter list rendered next to the
 * continuous guide document.
 *
 * Each entry is a hash-anchor link that smooth-scrolls to its
 * section on the same page. An IntersectionObserver highlights the
 * chapter currently in view as the reader scrolls.
 *
 * No progress ticks, no locks, no completion state — a Knowledge
 * Guide is a reference document, not a journey to complete.
 */
interface Props {
  sections: KnowledgeGuideSection[]
}

export default function KnowledgeGuideNav({ sections }: Props) {
  const [activeSlug, setActiveSlug] = useState<string | null>(
    sections[0]?.slug ?? null,
  )

  useEffect(() => {
    if (sections.length === 0) return
    // Threshold + rootMargin picked so a chapter counts as "current"
    // once its heading crosses roughly the top third of the viewport —
    // matches how readers experience "which chapter am I in".
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const slug = entry.target.getAttribute('data-chapter-slug')
            if (slug) setActiveSlug(slug)
          }
        }
      },
      { rootMargin: '-30% 0px -60% 0px', threshold: 0 },
    )
    for (const s of sections) {
      const el = document.getElementById(`chapter-${s.slug}`)
      if (el) observer.observe(el)
    }
    return () => observer.disconnect()
  }, [sections])

  if (sections.length === 0) return null

  return (
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
      <ul className="space-y-1.5">
        {sections.map((section) => {
          const isActive = section.slug === activeSlug
          return (
            <li key={section.id}>
              <a
                href={`#chapter-${section.slug}`}
                className={
                  isActive
                    ? 'block rounded-md px-3 py-1.5 text-[13.5px] font-semibold text-teal-700'
                    : 'block rounded-md px-3 py-1.5 text-[13.5px] text-navy-800 hover:bg-slate-100'
                }
                style={
                  isActive
                    ? { background: 'rgba(56,160,158,0.10)' }
                    : undefined
                }
              >
                {section.title}
              </a>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
