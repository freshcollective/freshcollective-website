import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

/**
 * A floor under block spacing, not a new rhythm.
 *
 * Every block type in the Pathway renderer carried its own vertical
 * margin except Content and Columns, which had none — so two adjacent
 * paragraphs sat flush while every other pairing had between 16 and
 * 32px. Those two now carry 6px.
 *
 * What these tests mostly protect is the restraint. Normalising every
 * block to 6px would have been "consistent" and would also have
 * compressed every published Pathway from its established 24px rhythm
 * down to a quarter of it. So the margins that already existed are
 * asserted here by value: a later tidy-up that unifies them is a change
 * to published creator content, and should have to delete a test that
 * says so rather than slip through as housekeeping.
 *
 * Margin collapsing is what makes the floor a floor. A Content block
 * beside an image resolves to the image's 24px, not 24+6.
 *
 * The About renderer is deliberately absent: its pages apply
 * ``space-y-6`` / ``space-y-4`` at the wrapper, so its blocks are
 * uniformly spaced already and carry no margins by design. Adding any
 * there would be overridden on top and leave stray bottom margins.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

const PATHWAY = 'components/spaces/BlockList.tsx'
const PREVIEW = 'components/creator/BlockEditorShared.tsx'

/** Source with comments stripped — the comments here name the very
 *  classes and pixel values being asserted. */
function code(path: string): string {
  return read(path)
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
}

/** Every class name the element a given block branch returns can carry.
 *
 *  Several branches set the className through a ternary — ``{wrapped ?
 *  '' : 'my-6 …'}`` — so reading only the first quoted string returns
 *  the empty wrapped case and reports no margin at all. An earlier
 *  version of this helper did exactly that, which left ``audio``,
 *  ``reflection_prompt`` and ``exercise`` unasserted: flattening
 *  ``audio`` from 24px to 6px went undetected. Both arms are collected
 *  so each is checked in its own right. */
function branchClasses(source: string, blockType: string): string[] {
  const start = source.indexOf(`if (t === '${blockType}'`)
  assert.ok(start !== -1, `no branch for ${blockType}`)
  // Slice to the *next* branch rather than a fixed window: the
  // ``resource`` branch computes for ~1.5k characters before returning,
  // so any fixed window either misses it or reaches into its neighbour.
  //
  // The boundary is ``if (t === '`` and not ``t === '`` because
  // ``block.content === 'new_tab'`` ends in exactly that substring —
  // the final "t" of "content". Searching for the loose form cut the
  // button branch off before its own className and reported it as
  // having no margin, and is also why ``new_tab``/``same_tab`` can look
  // like block types when grepping this file.
  const rest = source.slice(start + 12)
  const nextBranch = rest.indexOf("if (t === '")
  const segment = nextBranch === -1 ? rest : rest.slice(0, nextBranch)
  const attr = segment.match(/className=(?:"([^"]*)"|\{((?:[^{}]|\{[^}]*\})*)\})/)
  assert.ok(attr, `no className found in the ${blockType} branch`)
  if (attr[1] !== undefined) return [attr[1]]
  // Ternary form: each arm separately. Joining them into one string
  // let a flattened arm hide behind an untouched one — the wrapped
  // ``'my-6'`` arm kept the assertion green while the un-wrapped arm
  // that members actually see had been cut to 6px.
  return [...attr[2].matchAll(/'([^']*)'/g)].map((m) => m[1])
}

/** Every arm that sets a margin must set the *expected* margin.
 *
 *  Arms with no margin class at all are ignored — the wrapped arm of a
 *  soft-container block legitimately has none, because the container
 *  supplies the spacing. */
function assertEveryMarginArm(arms: string[], expected: string): void {
  const withMargin = arms.filter((arm) => /\bmy-[\d.]+/.test(arm))
  assert.ok(withMargin.length > 0, `no arm sets a margin (expected ${expected})`)
  for (const arm of withMargin) {
    assert.match(
      arm,
      new RegExp(`\\b${expected.replace('.', '\\.')}\\b`),
      `an arm has a different margin than ${expected}: "${arm}"`,
    )
  }
}

describe('the two block types that had no spacing now have 6px', () => {
  test('Content carries my-1.5 in the Pathway renderer', () => {
    assertEveryMarginArm(branchClasses(code(PATHWAY), 'text'), 'my-1.5')
  })

  test('Columns carries my-1.5 in the Pathway renderer', () => {
    assertEveryMarginArm(branchClasses(code(PATHWAY), 'columns'), 'my-1.5')
  })

  test('the Creator Studio preview matches, so the preview is honest', () => {
    assertEveryMarginArm(branchClasses(code(PREVIEW), 'text'), 'my-1.5')
    // Columns previews through ColumnsPreview, which carries its own.
    const preview = code(PREVIEW)
    const columnsPreview = preview.slice(preview.indexOf('function ColumnsPreview'))
    assert.match(columnsPreview.slice(0, 400), /className="my-1\.5"/)
  })
})

describe('the blocks that already had spacing are untouched', () => {
  // By value, on purpose. Unifying these is a visible change to every
  // published Pathway, so it should cost a deleted test.
  const EXPECTED: Record<string, string> = {
    divider: 'my-8',
    image: 'my-6',
    video_embed: 'my-6',
    file_download: 'my-4',
    link: 'my-4',
    callout: 'my-5',
    embed: 'my-6',
    button: 'my-5',
    // These three set their margin through a ternary. They were the
    // blind spot that let a flattening mutation survive.
    audio: 'my-6',
    reflection_prompt: 'my-6',
    exercise: 'my-6',
    resource: 'my-5',
  }

  for (const [blockType, expected] of Object.entries(EXPECTED)) {
    test(`${blockType} still has ${expected}`, () => {
      assertEveryMarginArm(branchClasses(code(PATHWAY), blockType), expected)
    })
  }

  test('nothing was normalised to a single uniform margin', () => {
    // If every block ends up with the same value, the floor has become
    // a rewrite of the page rhythm.
    const source = code(PATHWAY)
    const values = new Set(
      Object.keys(EXPECTED).map(
        (t) => branchClasses(source, t).join(' ').match(/my-[\d.]+/)?.[0],
      ),
    )
    assert.ok(
      values.size > 1,
      'every block now shares one margin — published spacing has been rewritten',
    )
  })
})

describe('no wrapper-level spacing was introduced', () => {
  // A ``space-y`` on the wrapper overrides each block's own top margin
  // through specificity, silently flattening the rhythm it looks like
  // it is merely adding to. ``flex flex-col gap`` is the opposite trap:
  // it stops margins collapsing and roughly doubles every gap.
  const CONSUMERS = [
    'app/spaces/[slug]/pathways/[pathway-slug]/[step-slug]/page.tsx',
    'components/spaces/KnowledgeGuideView.tsx',
  ]

  for (const consumer of CONSUMERS) {
    test(`${consumer} does not wrap blocks in space-y or a flex gap`, () => {
      const source = read(consumer)
      const call = source.indexOf('renderBlocks(')
      assert.ok(call !== -1, 'this consumer no longer renders blocks')
      // The element that directly contains the call.
      const before = source.slice(Math.max(0, call - 400), call)
      const wrapper = before.slice(before.lastIndexOf('<'))
      assert.ok(
        !/\bspace-y-/.test(wrapper),
        'wrapper space-y would override every block’s own margin',
      )
      assert.ok(
        !/\bflex\b[^"]*\bflex-col\b[^"]*\bgap-/.test(wrapper),
        'a flex gap would stop margins collapsing and double every gap',
      )
    })
  }

  test('renderBlocks still returns a bare list, not a spaced container', () => {
    // It maps straight over blocks; wrapping it would reintroduce the
    // specificity problem in a single place.
    assert.match(code(PATHWAY), /return blocks\.map\(/)
  })
})
