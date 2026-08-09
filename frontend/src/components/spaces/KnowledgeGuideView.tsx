import type { KnowledgeGuide, StepBlock } from '@/types/platform'
import type { CollectivePaletteMeta } from '@/lib/collectivePalette'
import { renderBlocks } from '@/components/spaces/BlockList'
import KnowledgeGuideNav from '@/components/spaces/KnowledgeGuideNav'

/**
 * KnowledgeGuideView — the continuous document member surface for a
 * pathway with pathway_type === 'knowledge_guide'.
 *
 * Feels like opening a practical handbook:
 *   * title + description at the top
 *   * "In this guide" table of contents generated from the sections
 *   * chapters (sections) with their steps rendered inline as
 *     subsections, using the same BlockList as the Guided surface
 *   * a sticky chapter list on the side highlights the current chapter
 *     as the reader scrolls
 *
 * No progress, no completion, no next/previous — those belong to the
 * Guided Experience. The URL for an individual step in a Knowledge
 * Guide redirects here with a #step-{slug} anchor so notification and
 * bookmark deep links still work.
 */

interface Props {
  guide: KnowledgeGuide
  collectivePalette: CollectivePaletteMeta | null
}

export default function KnowledgeGuideView({ guide, collectivePalette }: Props) {
  const hasChapters = guide.sections.length > 0
  // When the author hasn't organised into sections yet, every step
  // ends up in orphan_steps. Render them flat so the guide is still
  // usable while the author organises. If both are empty we render
  // a calm empty state instead of a blank page.
  const isEmpty = !hasChapters && guide.orphan_steps.length === 0

  return (
    <div className="mx-auto grid max-w-6xl gap-10 px-4 py-8 lg:grid-cols-[220px_1fr]">
      {/* Sticky chapter nav (desktop only). Hidden on mobile — the
          TOC below already gives every section a tap target. */}
      <aside>
        <KnowledgeGuideNav sections={guide.sections} />
      </aside>

      <article className="min-w-0">
        <header className="mb-8 border-b border-border pb-6">
          <p
            className="mb-2 text-[11px] font-semibold uppercase tracking-[0.20em]"
            style={{ color: '#38A09E' }}
          >
            Knowledge Guide
          </p>
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

          {/* In this guide — a plain, calm table of contents. Only
              rendered when there are chapters to jump to. Duplicated
              in the sidebar for desktop; here it stays reachable on
              mobile too. */}
          {hasChapters && (
            <div
              className="mt-6 rounded-2xl border border-border bg-white p-5"
              aria-label="In this guide"
            >
              <p
                className="mb-3 text-[10.5px] font-semibold uppercase tracking-[0.16em]"
                style={{ color: 'rgba(12,24,38,0.55)' }}
              >
                In this guide
              </p>
              <ol className="space-y-1.5">
                {guide.sections.map((s, i) => (
                  <li key={s.id}>
                    <a
                      href={`#chapter-${s.slug}`}
                      className="flex items-baseline gap-3 text-[14.5px] text-navy-800 hover:text-teal-700"
                    >
                      <span
                        className="w-6 shrink-0 text-right font-mono text-[12px]"
                        style={{ color: 'rgba(12,24,38,0.45)' }}
                      >
                        {String(i + 1).padStart(2, '0')}
                      </span>
                      <span>{s.title}</span>
                    </a>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </header>

        {isEmpty && (
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

        {/* Sectionless steps render above the chapters — a small
            preface for guides whose author left an intro step
            outside any section. Empty for well-organised guides. */}
        {guide.orphan_steps.length > 0 && (
          <div className="mb-10">
            {guide.orphan_steps.map((step) => (
              <section
                key={step.id}
                id={`step-${step.slug}`}
                className="mb-8 scroll-mt-24"
              >
                <h2 className="mb-3 font-serif text-[22px] leading-snug text-navy-900">
                  {step.title}
                </h2>
                {renderBlocks(step.blocks as StepBlock[], collectivePalette)}
              </section>
            ))}
          </div>
        )}

        {guide.sections.map((section) => (
          <section
            key={section.id}
            id={`chapter-${section.slug}`}
            data-chapter-slug={section.slug}
            className="mb-14 scroll-mt-24"
          >
            <h2
              className="mb-2 font-serif text-[24px] leading-snug text-navy-900 md:text-[26px]"
              style={{ letterSpacing: '-0.005em' }}
            >
              {section.title}
            </h2>
            <div
              className="mb-5 h-[2px] w-10 rounded-full"
              style={{ background: 'var(--fc-accent, #38A09E)' }}
            />

            {section.steps.map((step) => (
              <div
                key={step.id}
                id={`step-${step.slug}`}
                className="mb-8 scroll-mt-24"
              >
                <h3 className="mb-3 mt-6 font-semibold text-[17px] leading-snug text-navy-900">
                  {step.title}
                </h3>
                {renderBlocks(step.blocks as StepBlock[], collectivePalette)}
              </div>
            ))}
          </section>
        ))}
      </article>
    </div>
  )
}
