import type {
  KnowledgeGuide,
  KnowledgeGuideStep,
} from '@/types/platform'

/**
 * Knowledge Guide chapter model — how the member surface groups
 * content into switchable documents.
 *
 * A "chapter" is one continuous document the reader sees at a time,
 * addressed by ``?section=<slug>``. Named sections map 1-to-1 to
 * chapters. Unsectioned steps, when they exist, are folded into a
 * single synthetic chapter with slug ``more`` and no title so the
 * member surface doesn't invent a group heading for them.
 *
 * The helper is intentionally pure so it can be unit-tested and so
 * both the landing page (which needs the chapter set to pick the
 * active one) and the nav (which needs to render them) derive from
 * the same source of truth.
 */

export const ORPHAN_CHAPTER_SLUG = 'more'

export interface KnowledgeGuideChapter {
  /** ``?section=`` value that selects this chapter. Never surfaces
   *  as visible text — always displayed via ``title``. */
  slug: string
  /** null for the orphan bucket. Callers hide the chapter heading
   *  entirely when this is null. */
  title: string | null
  steps: KnowledgeGuideStep[]
  /** True for the synthetic bucket of unsectioned steps. */
  isOrphanBucket: boolean
}

/** Ordered list of chapters — named sections first, then a single
 *  orphan bucket (if there are any unsectioned steps). */
export function computeChapters(guide: KnowledgeGuide): KnowledgeGuideChapter[] {
  const named: KnowledgeGuideChapter[] = guide.sections.map((s) => ({
    slug: s.slug,
    title: s.title,
    steps: s.steps,
    isOrphanBucket: false,
  }))
  if (guide.orphan_steps.length > 0) {
    named.push({
      slug: ORPHAN_CHAPTER_SLUG,
      title: null,
      steps: guide.orphan_steps,
      isOrphanBucket: true,
    })
  }
  return named
}

/** True when the pathway has no named sections. Callers render the
 *  flat step list on the sidebar and skip the ``?section=`` URL
 *  conventions entirely. */
export function isFlatKnowledgeGuide(guide: KnowledgeGuide): boolean {
  return guide.sections.length === 0
}

/** Find which chapter a step lives in. Used by the step-URL redirect
 *  to build the canonical ``?section=<slug>#step-<step-slug>`` link.
 *  Returns null when the step slug isn't found — caller decides
 *  whether that's a not-found or a bare-URL fallback. */
export function findChapterForStep(
  chapters: KnowledgeGuideChapter[],
  stepSlug: string,
): KnowledgeGuideChapter | null {
  for (const c of chapters) {
    if (c.steps.some((s) => s.slug === stepSlug)) return c
  }
  return null
}
