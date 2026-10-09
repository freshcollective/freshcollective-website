import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

/**
 * Quotes and the Pause & Reflect panel read the Collective's palette.
 *
 * Both used to be platform teal regardless of the Collective they
 * appeared in. The Atlas is explicit that the Colour Palette drives the
 * collective interface — accents, dividers, card highlights — so a
 * warm Collective rendering a cool teal quote rule was the palette
 * being ignored, not a style choice.
 *
 * The resolution order matters more than the colours, and is what these
 * tests pin:
 *
 *   1. ``--fc-quote-accent``  — a palette-coloured container overrides
 *   2. ``--fc-accent``        — the Collective's palette primary
 *   3. a literal              — only for a Collective with no palette
 *
 * Step 3 existing is the compatibility guarantee: nothing about a
 * palette-less Collective changes.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

/** Source with comments stripped — the comments here discuss the very
 *  literals these tests assert are no longer used bare. */
function code(path: string): string {
  return read(path)
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
}

describe('the rendered blockquote', () => {
  const RENDERER = 'components/RichTextRenderer.tsx'

  test('falls through container → collective accent → literal', () => {
    assert.match(
      code(RENDERER),
      /var\(--fc-quote-accent,\s*var\(--fc-accent,\s*#5eead4\)\)/,
    )
  })

  test('no longer stops at the platform teal', () => {
    // The precise old value, which rendered teal in every Collective.
    assert.ok(
      !code(RENDERER).includes('var(--fc-quote-accent, #5eead4)'),
      'the blockquote still falls straight to teal',
    )
  })

  test('a container override still wins', () => {
    // --fc-quote-accent must remain the first term, or a quote inside a
    // tinted container loses the container's own accent.
    const style = code(RENDERER).match(/borderColor:\s*'([^']+)'/)
    assert.ok(style, 'the blockquote no longer sets a border colour')
    assert.ok(
      style[1].indexOf('--fc-quote-accent') < style[1].indexOf('--fc-accent,'),
      'the container override must be resolved before the collective accent',
    )
  })

  test('only the rule is tinted — quote text keeps its own colour', () => {
    // Readability guarantee: no palette can lower the text contrast,
    // because no palette touches the text.
    const source = code(RENDERER)
    const start = source.indexOf("case 'blockquote':")
    const section = source.slice(start, start + 900)
    assert.match(section, /text-black/)
    assert.ok(
      !/color:\s*'var\(--fc-accent/.test(section),
      'quote text must not be palette-coloured',
    )
  })
})

describe("the creator's editor shows the same colour", () => {
  test('the ProseMirror blockquote reads the same variables', () => {
    const css = read('app/globals.css')
    assert.match(
      css,
      /\.rich-editor \.ProseMirror blockquote \{[^}]*var\(--fc-quote-accent,\s*var\(--fc-accent,\s*#5BBFBD\)\)/,
    )
  })

  test('it no longer hardcodes the teal literal as the border', () => {
    const css = read('app/globals.css')
    assert.ok(
      !/border-left:\s*3px solid #5BBFBD/.test(css),
      'the editor still paints a fixed teal quote rule',
    )
  })
})

describe('the Pause & Reflect panel', () => {
  const ACTIONS = 'components/spaces/StepActions.tsx'

  test('its background reads the palette', () => {
    assert.match(
      code(ACTIONS),
      /background:\s*'var\(--fc-accent-tint,\s*rgba\(56,160,158,0\.045\)\)'/,
    )
  })

  test('its border reads the palette', () => {
    assert.match(
      code(ACTIONS),
      /border:\s*'1px solid var\(--fc-accent-line,\s*rgba\(56,160,158,0\.14\)\)'/,
    )
  })

  test('no bare platform teal is left in the panel', () => {
    // Every remaining occurrence must sit inside a var() fallback, which
    // is what keeps palette-less Collectives looking unchanged.
    const source = code(ACTIONS)
    for (const match of source.matchAll(/rgba\(56,160,158,[0-9.]+\)/g)) {
      const before = source.slice(Math.max(0, match.index - 60), match.index)
      assert.match(
        before,
        /var\(--fc-accent[a-z-]*,\s*$/,
        `a bare teal literal remains at offset ${match.index}`,
      )
    }
  })

  test('the parts that were already themed still are', () => {
    // Guards against this change accidentally replacing a working
    // variable with a literal while moving things around.
    //
    // Reads the panel *and* the shared component it now delegates the
    // box to: the "Private to you" line and the save button moved into
    // ``PrivateResponseArea`` when Exercise blocks needed the same
    // thing. The guarantee is that these are still palette variables
    // and not literals, which does not depend on which file they are
    // in.
    const source = code(ACTIONS) + '\n' + code('components/spaces/PrivateResponseArea.tsx')
    assert.match(source, /var\(--fc-accent,\s*#0f766e\)/)   // "Private to you"
    assert.match(source, /var\(--fc-accent,\s*#38A09E\)/)   // save button
  })

  test('the panel itself still themes its own background and border', () => {
    // These stayed in StepActions — the Exercise block deliberately has
    // no panel of its own, so this is not shared.
    const source = code(ACTIONS)
    assert.match(source, /var\(--fc-accent-tint,\s*rgba\(56,160,158,0\.045\)\)/)
    assert.match(source, /var\(--fc-accent-line,\s*rgba\(56,160,158,0\.14\)\)/)
  })
})
