/**
 * Unit tests for the pure functions in ``worldGuide.ts``.
 *
 * Run with the built-in Node test runner + Node's experimental type
 * stripping — no new dev dependency required:
 *
 *     node --experimental-strip-types --test src/lib/worldGuide.test.ts
 *
 * These cover the manual-Markdown "auto-continue" logic and the
 * import parser. Their only job is to lock the shape of these pure
 * functions so future edits don't accidentally regress the editor.
 */

import { strict as assert } from 'node:assert'
import { describe, test } from 'node:test'
// The `.ts` extension is required by Node's native TS stripping;
// tsconfig excludes this test file from the Next build so tsc does
// not enforce ``allowImportingTsExtensions`` here.
// @ts-expect-error - Node-native import path
import { continueListOnEnter, parseImportedMarkdown, renderMarkdown } from './worldGuide.ts'


describe('continueListOnEnter', () => {
  test('continues a numbered list and increments', () => {
    const r = continueListOnEnter('1. First item')
    assert.deepEqual(r, { kind: 'continue', insert: '\n2. ' })
  })

  test('handles multi-digit numbering', () => {
    const r = continueListOnEnter('  9. Ninth item')
    assert.deepEqual(r, { kind: 'continue', insert: '\n  10. ' })
  })

  test('continues a bullet list with `-`', () => {
    const r = continueListOnEnter('- an item')
    assert.deepEqual(r, { kind: 'continue', insert: '\n- ' })
  })

  test('continues a bullet list with `*`', () => {
    const r = continueListOnEnter('* an item')
    assert.deepEqual(r, { kind: 'continue', insert: '\n* ' })
  })

  test('continues a bullet list with `+`', () => {
    const r = continueListOnEnter('+ an item')
    assert.deepEqual(r, { kind: 'continue', insert: '\n+ ' })
  })

  test('preserves indent when continuing bullets', () => {
    const r = continueListOnEnter('    - deep item')
    assert.deepEqual(r, { kind: 'continue', insert: '\n    - ' })
  })

  test('continues a checklist with an empty box', () => {
    const r = continueListOnEnter('- [ ] a task')
    assert.deepEqual(r, { kind: 'continue', insert: '\n- [ ] ' })
  })

  test('does not carry the completed state forward', () => {
    const r = continueListOnEnter('- [x] a completed task')
    assert.deepEqual(r, { kind: 'continue', insert: '\n- [ ] ' })
    const rCap = continueListOnEnter('- [X] shouted completion')
    assert.deepEqual(rCap, { kind: 'continue', insert: '\n- [ ] ' })
  })

  test('continues a blockquote', () => {
    const r = continueListOnEnter('> a quote')
    assert.deepEqual(r, { kind: 'continue', insert: '\n> ' })
  })

  test('ends a numbered list on an empty item', () => {
    const r = continueListOnEnter('3. ')
    assert.equal(r.kind, 'end')
  })

  test('ends a bullet list on an empty item', () => {
    const r = continueListOnEnter('- ')
    assert.equal(r.kind, 'end')
  })

  test('ends a checklist on an empty item', () => {
    const r = continueListOnEnter('- [ ] ')
    assert.equal(r.kind, 'end')
  })

  test('ends a blockquote on an empty line', () => {
    const r = continueListOnEnter('> ')
    assert.equal(r.kind, 'end')
    const rBare = continueListOnEnter('>')
    assert.equal(rBare.kind, 'end')
  })

  test('returns default for plain paragraphs', () => {
    assert.deepEqual(continueListOnEnter('Just a paragraph.'), { kind: 'default' })
    assert.deepEqual(continueListOnEnter(''), { kind: 'default' })
    assert.deepEqual(continueListOnEnter('    '), { kind: 'default' })
  })
})


describe('renderMarkdown callout', () => {
  test('emits a flat wg-callout with no inline shadow or radius', () => {
    const html = renderMarkdown('> [!note] Heads up\n> Body text')
    assert.match(html, /<aside class="wg-callout wg-callout-note">/)
    // The shared prose stylesheet is responsible for visuals — the
    // rendered HTML must not carry any inline shadow / radius that
    // could re-introduce the floating-card look.
    assert.doesNotMatch(html, /box-shadow/i)
    assert.doesNotMatch(html, /border-radius/i)
    // Title + body both present.
    assert.match(html, /wg-callout-title.*Heads up/)
    assert.match(html, /wg-callout-body/)
  })

  test('emits ordered lists (1.1 numbering stays visible in headings)', () => {
    const html = renderMarkdown('## 1.2 Roles and responsibilities')
    assert.match(html, /<h2>1\.2 Roles and responsibilities<\/h2>/)
  })

  test('renders a Markdown table', () => {
    const html = renderMarkdown('| Role | Duty |\n| --- | --- |\n| A | B |')
    assert.match(html, /<table>/)
    assert.match(html, /<th>Role<\/th>/)
    assert.match(html, /<td>A<\/td>/)
  })
})

describe('parseImportedMarkdown', () => {
  test('splits by canonical section headings', () => {
    const src = `# Why this exists\nreason\n\n# What this covers\nscope\n\n# Main content\nbody\n\n# What's changed\nnotes`
    const p = parseImportedMarkdown(src)
    assert.equal(p.why_this_exists, 'reason')
    assert.equal(p.what_this_covers, 'scope')
    assert.equal(p.main_content, 'body')
    assert.equal(p.whats_changed, 'notes')
    assert.equal(p.fallback_all_to_main, false)
  })

  test('routes unmatched content into main_content', () => {
    const src = `# Random Heading\nthing\n\n# Purpose\nreason`
    const p = parseImportedMarkdown(src)
    // "Purpose" maps to why_this_exists via aliases.
    assert.equal(p.why_this_exists, 'reason')
    // "Random Heading" doesn't map → its body lands in main_content.
    assert.ok(p.main_content.includes('thing'))
  })

  test('everything goes to main_content when no headings match', () => {
    const src = 'Just a body with no section headings.\n\nSecond paragraph.'
    const p = parseImportedMarkdown(src)
    assert.equal(p.fallback_all_to_main, true)
    assert.ok(p.main_content.startsWith('Just a body'))
    assert.equal(p.why_this_exists, '')
    assert.equal(p.what_this_covers, '')
    assert.equal(p.whats_changed, '')
  })
})
