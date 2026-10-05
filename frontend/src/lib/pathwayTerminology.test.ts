import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  isKnowledgeGuide,
  openLabel,
  showsProgress,
  unitCountLabel,
  unitNoun,
  unitNounPlural,
  viewAllLabel,
} from './pathwayTerminology.ts'

const read = (rel: string) => readFileSync(new URL(rel, import.meta.url), 'utf8')
const codeOnly = (rel: string) =>
  read(rel)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const GUIDE = { pathway_type: 'knowledge_guide' } as const
const GUIDED = { pathway_type: 'guided_experience' } as const

const ABOUT = '../app/spaces/[slug]/pathways/[pathway-slug]/about/page.tsx'
const CARD = '../components/spaces/PathwayCard.tsx'
const STUDIO_LIST = '../app/creator-studio/pathways/PathwaysClient.tsx'
const STUDIO_HEADER = '../app/creator-studio/pathways/[pathwaySlug]/PathwayHeader.tsx'
const STUDIO_CONTENT = '../app/creator-studio/pathways/[pathwaySlug]/PathwayContentClient.tsx'

describe('the type comes from the canonical field', () => {
  test('knowledge_guide is recognised', () => {
    assert.equal(isKnowledgeGuide(GUIDE), true)
  })

  test('guided_experience is not', () => {
    assert.equal(isKnowledgeGuide(GUIDED), false)
  })

  test('absent means Guided Experience, so older payloads are unchanged', () => {
    assert.equal(isKnowledgeGuide({}), false)
    assert.equal(isKnowledgeGuide(null), false)
    assert.equal(isKnowledgeGuide(undefined), false)
    assert.equal(isKnowledgeGuide({ pathway_type: null }), false)
  })

  test('no surface infers the type from a title or slug', () => {
    for (const rel of [CARD, ABOUT, STUDIO_LIST, STUDIO_HEADER, STUDIO_CONTENT]) {
      const src = codeOnly(rel)
      assert.ok(
        !/title.*knowledge|slug.*knowledge|knowledge.*guide.*title/i.test(src),
        `${rel} appears to infer the type from text`,
      )
    }
  })

  test('the string literal lives in one module', () => {
    // Scattered comparisons are what the brief asked to avoid.
    for (const rel of [CARD, ABOUT, STUDIO_LIST, STUDIO_HEADER, STUDIO_CONTENT]) {
      assert.ok(
        !codeOnly(rel).includes("'knowledge_guide'"),
        `${rel} compares the enum directly instead of using the helper`,
      )
    }
  })
})

describe('Guided Experience terminology is unchanged', () => {
  test('counts are steps', () => {
    assert.equal(unitCountLabel(GUIDED, 5), '5 steps')
    assert.equal(unitCountLabel(GUIDED, 1), '1 step')
  })

  test('nouns are steps', () => {
    assert.equal(unitNoun(GUIDED), 'step')
    assert.equal(unitNounPlural(GUIDED), 'steps')
  })

  test('the CTA is Begin', () => {
    assert.equal(openLabel(GUIDED), 'Begin')
  })

  test('the overview link is View all steps', () => {
    assert.equal(viewAllLabel(GUIDED), 'View all steps')
  })

  test('progress is shown', () => {
    assert.equal(showsProgress(GUIDED), true)
    assert.equal(showsProgress({}), true, 'and for an untyped payload')
  })
})

describe('Knowledge Guide terminology', () => {
  test('counts are sections', () => {
    assert.equal(unitCountLabel(GUIDE, 5), '5 sections')
    assert.equal(unitCountLabel(GUIDE, 1), '1 section')
  })

  test('nouns are sections', () => {
    assert.equal(unitNoun(GUIDE), 'section')
    assert.equal(unitNounPlural(GUIDE), 'sections')
  })

  test('the CTA is Open guide, not Continue', () => {
    // "Continue reading" would imply a stored reading position. There
    // is none, and inventing one to justify a verb is backwards.
    assert.equal(openLabel(GUIDE), 'Open guide')
    assert.ok(!openLabel(GUIDE).toLowerCase().includes('continue'))
  })

  test('the overview link is View sections', () => {
    assert.equal(viewAllLabel(GUIDE), 'View sections')
  })

  test('progress is not shown', () => {
    assert.equal(showsProgress(GUIDE), false)
  })

  test('an empty count says nothing rather than "0 sections"', () => {
    assert.equal(unitCountLabel(GUIDE, 0), null)
    assert.equal(unitCountLabel(GUIDE, null), null)
    assert.equal(unitCountLabel(GUIDED, 0), null)
  })
})

describe('the member About surface', () => {
  const src = codeOnly(ABOUT)

  test('the progress block is gated on the type', () => {
    assert.match(src, /showsProgress\(pathway\) && pathway\.step_count > 0/)
  })

  test('"X of Y complete" and the percentage sit inside that gate', () => {
    const gate = src.indexOf('showsProgress(pathway)')
    assert.ok(gate > 0)
    const complete = src.indexOf('of {pathway.step_count} complete')
    const pct = src.indexOf('{progressPct}%')
    assert.ok(complete > gate, 'the completion line must be inside the gate')
    assert.ok(pct > gate, 'the percentage must be inside the gate')
  })

  test('the progress bar sits inside that gate too', () => {
    const gate = src.indexOf('showsProgress(pathway)')
    assert.ok(src.indexOf('width: `${progressPct}%`') > gate)
  })

  test('counts go through the helper', () => {
    assert.match(src, /unitCountLabel\(pathway, pathway\.step_count\)/)
    assert.ok(
      !/\{pathway\.step_count\} step\{/.test(src),
      'a hand-built "N step(s)" label survives',
    )
  })

  test('the CTA and overview link are type-aware', () => {
    assert.match(src, /\? 'Open guide'/)
    assert.match(src, /viewAllLabel\(pathway\)/)
    assert.ok(!src.includes('View all steps →'), 'hardcoded link text survives')
  })

  test('Guided Experience CTA wording is preserved', () => {
    assert.match(src, /'Begin pathway'/)
    assert.match(src, /'Review'/)
    assert.match(src, /'Continue'/)
  })
})

describe('the member card', () => {
  const src = codeOnly(CARD)

  test('the count goes through the helper', () => {
    assert.match(src, /unitCountLabel\(pathway, pathway\.step_count\)/)
  })

  test('the CTA goes through the helper', () => {
    assert.match(src, /openLabel\(pathway\)/)
  })

  test('no hand-built step label survives', () => {
    assert.ok(!/step\$\{/.test(src))
  })
})

describe('Creator Studio', () => {
  test('the listing header counts sections for a guide', () => {
    const src = codeOnly(STUDIO_LIST)
    assert.match(src, /unitCountLabel\(pathway, pathway\.step_count\)/)
    assert.ok(
      !/'step' : 'steps'/.test(src),
      'the hand-built step label survives in the listing',
    )
  })

  test('the pathway header counts sections for a guide', () => {
    const src = codeOnly(STUDIO_HEADER)
    assert.match(src, /unitCountLabel\(pathway, steps\.length\)/)
  })

  test('a guide header shows only its section count', () => {
    // "N sections · Published" — the grouping count is suppressed
    // rather than renamed, because a compact header does not earn a
    // second word for the groupings. The structure is visible in the
    // editor, where it is actually worked on.
    const src = codeOnly(STUDIO_HEADER)
    assert.match(src, /&& !isKnowledgeGuide\(pathway\)/)
    assert.ok(!src.includes("'chapters'"), 'no chapter count in the header')
  })

  test('Guided Experience still shows both counts', () => {
    const src = codeOnly(STUDIO_HEADER)
    assert.match(src, /unitCountLabel\(pathway, steps\.length\)/)
    assert.match(src, /'section' : 'sections'/)
  })

  test('authoring labels take the unit as a prop', () => {
    const src = codeOnly(STUDIO_CONTENT)
    assert.match(src, /unit: 'step' \| 'section'/)
    assert.match(src, /unit=\{unitNoun\(pathway\)\}/)
  })

  test('the add form and its buttons use it', () => {
    const src = codeOnly(STUDIO_CONTENT)
    assert.match(src, /New \{unit\}/)
    assert.match(src, /`Add \$\{unit\}`/)
    assert.ok(!src.includes("'Add step'"), 'a hardcoded Add step survives')
    assert.ok(!src.includes('>New step<'), 'a hardcoded New step survives')
  })

  test('its validation and error copy follow the unit', () => {
    const src = codeOnly(STUDIO_CONTENT)
    assert.match(src, /Could not add \$\{unit\}/)
    assert.ok(
      !src.includes("'Could not add step. Please try again.'"),
      'hardcoded step error copy survives',
    )
  })
})

describe('no member-facing step wording survives for a guide', () => {
  test('the About surface has no unconditional "step" in member copy', () => {
    // Narrow on purpose: "steps" legitimately appears in variable names
    // and in the Guided Experience branches, so this checks the
    // *rendered strings* that are not inside a type conditional.
    const src = codeOnly(ABOUT)
    for (const literal of [
      '} step{', 'steps in this pathway', 'View all steps →',
    ]) {
      assert.ok(!src.includes(literal), `unconditional member copy: ${literal}`)
    }
  })

  test('the reader surface is the existing continuous guide view', () => {
    // Unchanged by this work: anchors and one continuous page.
    const page = codeOnly('../app/spaces/[slug]/pathways/[pathway-slug]/page.tsx')
    assert.match(page, /<KnowledgeGuideView/)
  })
})
