import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = (rel: string) => readFileSync(new URL(rel, import.meta.url), 'utf8')
const codeOnly = (rel: string) =>
  read(rel)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const CONTENT = '../app/creator-studio/pathways/[pathwaySlug]/PathwayContentClient.tsx'
const BLOCKS = '../components/spaces/BlockList.tsx'
const RICH = '../components/RichTextRenderer.tsx'

describe('the two add controls no longer share a label', () => {
  const src = codeOnly(CONTENT)

  test('the grouping noun is derived from the pathway type', () => {
    assert.match(
      src,
      /const groupNoun = isKnowledgeGuide\(pathway\) \? 'chapter' : 'section'/,
    )
  })

  test('the control that creates a grouping is labelled with it', () => {
    // This one POSTs to /sections — the larger grouping — so for a
    // Knowledge Guide it is the chapter.
    assert.match(src, /\+ Add \{groupNoun\}/)
    assert.ok(
      !/\+ Add section\s*\n\s*<\/button>/.test(src),
      'a hardcoded "+ Add section" grouping control survives',
    )
  })

  test('its form heading and submit button follow', () => {
    assert.match(src, /New \{groupNoun\}/)
    assert.match(src, /`Add \$\{groupNoun\}`/)
    assert.ok(!src.includes("'Add section'"), 'hardcoded submit label survives')
  })

  test('the control that creates a content unit stays "section"', () => {
    // This one POSTs to /steps — the content unit.
    assert.match(src, /\+ Add \{unitNoun\(pathway\)\} here/)
    assert.match(src, /\+ Add \$\{unitNoun\(pathway\)\}/)
  })

  test('the two controls use different nouns for a guide', () => {
    // groupNoun = chapter, unitNoun = section. The whole point.
    assert.ok(src.includes('groupNoun') && src.includes('unitNoun(pathway)'))
  })

  test('the labels are keyed on the type, not on which button it is', () => {
    assert.match(src, /isKnowledgeGuide\(pathway\)/)
  })
})

describe('the structure line counts the right thing', () => {
  const src = codeOnly(CONTENT)

  test('the content count goes through the shared helper', () => {
    assert.match(src, /unitCountLabel\(pathway, steps\.length\)/)
  })

  test('no hand-built step label survives on this screen', () => {
    assert.ok(
      !/\$\{steps\.length === 1 \? 'step' : 'steps'\}/.test(src),
      'the "N steps" literal is still here',
    )
    assert.ok(!/'step' : 'steps'/.test(src), 'a step/steps ternary survives')
  })

  test('per-grouping counts use the helper too', () => {
    assert.match(src, /unitCountLabel\(pathway, sectionSteps\.length\)/)
    assert.match(src, /unitCountLabel\(pathway, unsectionedSteps\.length\)/)
  })

  test('the ungrouped row reads naturally for a guide', () => {
    assert.match(src, /isKnowledgeGuide\(pathway\) \? 'No chapter' : 'Unsectioned'/)
  })

  test('the grouping count is pluralised with the right noun', () => {
    assert.match(src, /groupNoun : `\$\{groupNoun\}s`/)
  })

  test('Guided Experience wording is unchanged', () => {
    // groupNoun falls back to 'section', unitNoun to 'step'.
    assert.match(src, /\? 'chapter' : 'section'/)
    assert.match(
      codeOnly('./pathwayTerminology.ts'),
      /isKnowledgeGuide\(pathway\) \? 'section' : 'step'/,
    )
  })
})

describe('Reflection Prompt line breaks survive rendering', () => {
  const blocks = read(BLOCKS)
  const rich = read(RICH)

  test('the prompt paragraph preserves author newlines', () => {
    assert.match(
      blocks,
      /<p className="whitespace-pre-wrap font-serif italic[^"]*">\s*\n\s*\{block\.content\}/,
    )
  })

  test('the supporting context does too', () => {
    assert.match(
      blocks,
      /<p className="mt-2 whitespace-pre-wrap[^"]*">\s*\n\s*\{block\.caption\}/,
    )
  })

  test('the legacy plain-text fallback preserves them as well', () => {
    // It split on blank lines already, so paragraphs worked — but a
    // single newline inside a paragraph was still collapsed.
    assert.match(rich, /my-3 whitespace-pre-wrap text-\[15px\]/)
  })

  test('the TipTap branch is untouched', () => {
    // Rich text carries its own hardBreak nodes; it needs no
    // whitespace handling and must not get any.
    const jsonBranch = rich.slice(0, rich.indexOf('Fallback: render as legacy plain text'))
    assert.ok(!jsonBranch.includes('whitespace-pre-wrap'))
    assert.match(rich, /return <br key=\{key\} \/>/)
  })

  test('the content itself is never manipulated', () => {
    // No <br> injection, no HTML conversion — the brief ruled both out.
    const prompt = blocks.slice(
      blocks.indexOf("t === 'reflection_prompt'"),
      blocks.indexOf("t === 'exercise'"),
    )
    assert.ok(!prompt.includes('dangerouslySetInnerHTML'))
    assert.ok(!/replace\(\/\\n\//.test(prompt), 'no newline rewriting')
    assert.ok(!/<br\s*\/?>/.test(prompt), 'no <br> injection')
  })

  test('HTML-like prompt text stays escaped', () => {
    // JSX interpolation escapes it; nothing here opts out of that.
    const prompt = blocks.slice(
      blocks.indexOf("t === 'reflection_prompt'"),
      blocks.indexOf("t === 'exercise'"),
    )
    assert.match(prompt, /\{block\.content\}/)
    assert.ok(!prompt.includes('innerHTML'))
  })

  test('one shared renderer covers every surface', () => {
    // BlockList is used by the member step page, the Knowledge Guide
    // view and Creator Studio's block editor — so this is fixed once.
    for (const rel of [
      '../app/spaces/[slug]/pathways/[pathway-slug]/[step-slug]/page.tsx',
      '../components/spaces/KnowledgeGuideView.tsx',
      '../app/creator-studio/pathways/[pathwaySlug]/steps/[stepSlug]/StepBlockEditor.tsx',
    ]) {
      assert.match(codeOnly(rel), /BlockList/, `${rel} renders via BlockList`)
    }
  })
})

describe('whitespace handling is presentation only', () => {
  test('long lines still wrap normally', () => {
    // pre-wrap, never pre or nowrap — ordinary wrapping must survive.
    const blocks = read(BLOCKS)
    assert.ok(!/whitespace-pre\b(?!-wrap)/.test(blocks))
    assert.ok(!/whitespace-nowrap/.test(
      blocks.slice(
        blocks.indexOf("t === 'reflection_prompt'"),
        blocks.indexOf("t === 'exercise'"),
      ),
    ))
  })

  test('blank lines are preserved by pre-wrap', () => {
    // Documenting the semantics the fix relies on: pre-wrap keeps
    // sequences of newlines, so an intentional blank line survives.
    const sample = 'Line 1\n\nLine 3'
    assert.equal(sample.split('\n').length, 3)
    assert.match(read(BLOCKS), /whitespace-pre-wrap/)
  })
})
