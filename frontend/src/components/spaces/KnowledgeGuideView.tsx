import type { KnowledgeGuide, StepBlock } from '@/types/platform'
import type { CollectivePaletteMeta } from '@/lib/collectivePalette'
import { renderBlocks } from '@/components/spaces/BlockList'
import KnowledgeGuideNav from '@/components/spaces/KnowledgeGuideNav'
import type { KnowledgeGuideChapter } from '@/components/spaces/knowledgeGuideChapters'

/**
 * KnowledgeGuideView — the member surface for a pathway with
 * pathway_type === 'knowledge_guide'.
 *
 * A guide is presented as a set of chapters (one per Section). The
 * URL's ``?section=<slug>`` picks which chapter is on-screen; only
 * that chapter's steps render in the reading pane. Switching
 * chapters is a Next.js Link navigation — feels instant, back
 * button works, deep links stay valid.
 *
 * When a pathway has no named Sections, ``flat`` mode kicks in:
 * every step renders continuously in one document and the nav
 * shows the flat step list.
 */

interface Props {
  guide: KnowledgeGuide
  spaceSlug: string
  pathwaySlug: string
  collectivePalette: CollectivePaletteMeta | null
  /** Ordered chapters — always empty when ``flat`` is true. */
  chapters: KnowledgeGuideChapter[]
  /** The chapter to render in the reading pane. Null only when
   *  ``flat`` is true (flat mode uses ``flatSteps`` instead). */
  activeChapter: KnowledgeGuideChapter | null
  /** True when the pathway has no named sections. The reading pane
   *  renders every step in one continuous document; the nav shows
   *  a flat step list. */
  flat: boolean
}

export default function KnowledgeGuideView({
  guide,
  spaceSlug,
  pathwaySlug,
  collectivePalette,
  chapters,
  activeChapter,
  flat,
}: Props) {
  const hasAnyContent = flat
    ? guide.orphan_steps.length > 0
    : chapters.some((c) => c.steps.length > 0)

  // Flat mode renders every step in one document; chapter mode
  // renders only the active chapter's steps.
  const stepsToRender = flat
    ? guide.orphan_steps
    : activeChapter?.steps ?? []

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      {/* Pathway identity — always visible above the layout so the
          guide's "home" reads consistently across chapters. */}
      <header className="mb-8 border-b border-border pb-6">
        <h1
          className="font-serif text-[30px] leading-tight text-navy-900 md:text-[34px]"
          style={{ letterSpacing: '-0.01em' }}
        >
          {guide.title}
        </h1>
        {guide.description && (
          <p
            className="mt-3 text-[15px] leading-relaxed"
            style={{
              color: 'rgba(12, 24, 38, 0.72)',
              fontFamily: 'Georgia, serif',
            }}
          >
            {guide.description}
          </p>
        )}
      </header>

      <div className="grid gap-10 lg:grid-cols-[240px_1fr]">
        <aside>
          <KnowledgeGuideNav
            chapters={chapters}
            activeChapterSlug={activeChapter?.slug ?? null}
            spaceSlug={spaceSlug}
            pathwaySlug={pathwaySlug}
            flat={flat}
            flatSteps={flat ? guide.orphan_steps : []}
          />
        </aside>

        <article className="min-w-0">
          {!hasAnyContent && (
            <div
              className="rounded-2xl border border-dashed border-slate-300 bg-white px-8 py-12 text-center"
            >
              <p
                className="font-serif text-[17px]"
                style={{ color: '#0C1826' }}
              >
                This guide is empty for now.
              </p>
              <p
                className="mx-auto mt-2 max-w-sm text-[13.5px] italic leading-relaxed"
                style={{ color: 'rgba(12, 24, 38, 0.60)', fontFamily: 'Georgia, serif' }}
              >
                The author is still gathering the pieces. Check back soon.
              </p>
            </div>
          )}

          {/* Chapter heading — hidden for the orphan bucket and for
              flat mode. Rendered as the primary heading of the
              current chapter document. */}
          {!flat && activeChapter && !activeChapter.isOrphanBucket && activeChapter.title && (
            <>
              <h2
                className="mb-2 font-serif text-[24px] leading-snug text-navy-900 md:text-[26px]"
                style={{ letterSpacing: '-0.005em' }}
              >
                {activeChapter.title}
              </h2>
              <div
                className="mb-6 h-[2px] w-10 rounded-full"
                style={{ background: 'var(--fc-accent, #38A09E)' }}
              />
            </>
          )}

          {stepsToRender.map((step) => (
            <section
              key={step.id}
              id={`step-${step.slug}`}
              className="mb-10 scroll-mt-24"
            >
              <h3 className="mb-3 mt-6 font-semibold text-[17px] leading-snug text-navy-900">
                {step.title}
              </h3>
              {renderBlocks(step.blocks as StepBlock[], collectivePalette)}
            </section>
          ))}
        </article>
      </div>
    </div>
  )
}
