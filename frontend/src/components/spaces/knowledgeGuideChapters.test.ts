import { describe, it } from 'node:test'
import assert from 'node:assert/strict'

import {
  ORPHAN_CHAPTER_SLUG,
  computeChapters,
  findChapterForStep,
  isFlatKnowledgeGuide,
} from './knowledgeGuideChapters.ts'
import type {
  KnowledgeGuide,
  KnowledgeGuideSection,
  KnowledgeGuideStep,
} from '../../types/platform.ts'

function step(slug: string): KnowledgeGuideStep {
  return { id: `st-${slug}`, slug, title: slug, blocks: [] }
}

function section(slug: string, steps: string[]): KnowledgeGuideSection {
  return {
    id: `sec-${slug}`,
    slug,
    title: slug.replace(/-/g, ' '),
    banner_image_url: null,
    steps: steps.map(step),
  }
}

function guide(overrides: Partial<KnowledgeGuide> = {}): KnowledgeGuide {
  return {
    id: 'pw-1',
    slug: 'pw',
    title: 'Pathway',
    description: null,
    cover_image_url: null,
    pathway_type: 'knowledge_guide',
    orphan_steps: [],
    sections: [],
    ...overrides,
  }
}

describe('computeChapters', () => {
  it('returns named sections in order when there are no orphans', () => {
    const chapters = computeChapters(guide({
      sections: [section('getting-started', ['a', 'b']), section('pathways', ['c'])],
    }))
    assert.equal(chapters.length, 2)
    assert.equal(chapters[0].slug, 'getting-started')
    assert.equal(chapters[0].isOrphanBucket, false)
    assert.equal(chapters[1].slug, 'pathways')
  })

  it('appends the orphan bucket after named sections', () => {
    const chapters = computeChapters(guide({
      sections: [section('getting-started', ['a'])],
      orphan_steps: [step('extra'), step('appendix')],
    }))
    assert.equal(chapters.length, 2)
    assert.equal(chapters[1].slug, ORPHAN_CHAPTER_SLUG)
    // Orphan bucket has no visible title — callers hide the heading.
    assert.equal(chapters[1].title, null)
    assert.equal(chapters[1].isOrphanBucket, true)
    assert.deepEqual(chapters[1].steps.map((s) => s.slug), ['extra', 'appendix'])
  })

  it('omits the orphan bucket entirely when there are no unsectioned steps', () => {
    const chapters = computeChapters(guide({
      sections: [section('one', ['a'])],
    }))
    assert.equal(chapters.length, 1)
    assert.equal(chapters[0].isOrphanBucket, false)
  })

  it('returns an empty list for a pathway with no content', () => {
    assert.deepEqual(computeChapters(guide()), [])
  })
})

describe('isFlatKnowledgeGuide', () => {
  it('is true when there are no named sections (even if orphans exist)', () => {
    assert.equal(
      isFlatKnowledgeGuide(guide({ orphan_steps: [step('a'), step('b')] })),
      true,
    )
  })

  it('is false as soon as any named section is present', () => {
    assert.equal(
      isFlatKnowledgeGuide(guide({ sections: [section('s', ['a'])] })),
      false,
    )
  })
})

describe('findChapterForStep', () => {
  it('locates a step inside a named section', () => {
    const chapters = computeChapters(guide({
      sections: [section('a', ['x']), section('b', ['y'])],
    }))
    const c = findChapterForStep(chapters, 'y')
    assert.equal(c?.slug, 'b')
  })

  it('locates a step in the orphan bucket', () => {
    const chapters = computeChapters(guide({
      sections: [section('a', ['x'])],
      orphan_steps: [step('extra')],
    }))
    const c = findChapterForStep(chapters, 'extra')
    assert.equal(c?.slug, ORPHAN_CHAPTER_SLUG)
    assert.equal(c?.isOrphanBucket, true)
  })

  it('returns null for an unknown step slug', () => {
    const chapters = computeChapters(guide({
      sections: [section('a', ['x'])],
    }))
    assert.equal(findChapterForStep(chapters, 'nope'), null)
  })
})
