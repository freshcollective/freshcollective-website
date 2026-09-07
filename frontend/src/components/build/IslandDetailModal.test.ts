/**
 * Unit tests for the IslandDetailModal helper(s). The DOM behaviour
 * itself (focus, ESC, backdrop close, current-vs-not CTA branching)
 * is covered by manual verification in the browser; there is no
 * jsdom/react-testing-library harness in this project. What IS worth
 * unit-testing is the paragraph splitter — Atlas Entries come from
 * admin free-text and can arrive in any shape (single blank lines,
 * CRLF, trailing whitespace, hard-wrapped intra-paragraph newlines).
 * If this splitter regresses, member-facing atlas rendering follows.
 *
 * Run with the built-in Node test runner + Node's experimental type
 * stripping:
 *
 *   node --experimental-strip-types --test src/components/build/IslandDetailModal.test.ts
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
// @ts-expect-error - Node-native import path (matches api.test.ts pattern)
import { splitParagraphs } from './islandDetailUtils.ts'


describe('splitParagraphs — nullish', () => {
  test('null → []', () => {
    assert.deepEqual(splitParagraphs(null), [])
  })
  test('empty string → []', () => {
    assert.deepEqual(splitParagraphs(''), [])
  })
  test('whitespace-only → []', () => {
    assert.deepEqual(splitParagraphs('   \n\n  \n'), [])
  })
})


describe('splitParagraphs — happy path', () => {
  test('single paragraph passes through', () => {
    assert.deepEqual(
      splitParagraphs('An island of quiet water.'),
      ['An island of quiet water.'],
    )
  })

  test('two paragraphs split on blank line', () => {
    const input = 'First paragraph.\n\nSecond paragraph.'
    assert.deepEqual(splitParagraphs(input), ['First paragraph.', 'Second paragraph.'])
  })

  test('three paragraphs split on blank lines', () => {
    const input = 'Alpha.\n\nBeta.\n\nGamma.'
    assert.deepEqual(splitParagraphs(input), ['Alpha.', 'Beta.', 'Gamma.'])
  })
})


describe('splitParagraphs — messy admin input', () => {
  test('CRLF line endings normalise', () => {
    const input = 'One.\r\n\r\nTwo.'
    assert.deepEqual(splitParagraphs(input), ['One.', 'Two.'])
  })

  test('trailing / leading whitespace on paragraphs is trimmed', () => {
    const input = '   Alpha.   \n\n   Beta.   '
    assert.deepEqual(splitParagraphs(input), ['Alpha.', 'Beta.'])
  })

  test('multiple blank lines between paragraphs collapse to one break', () => {
    const input = 'Alpha.\n\n\n\nBeta.'
    assert.deepEqual(splitParagraphs(input), ['Alpha.', 'Beta.'])
  })

  test('empty paragraphs are dropped', () => {
    // Two blank lines around empty content → still two paragraphs.
    const input = 'Alpha.\n\n   \n\nBeta.'
    assert.deepEqual(splitParagraphs(input), ['Alpha.', 'Beta.'])
  })

  test('hard-wrapped intra-paragraph newlines are preserved as newlines within the paragraph text (single-\\n stays)', () => {
    // Single \n inside a paragraph is a soft break — kept as-is so
    // whichever way the admin authored the text, the visual result
    // matches. The renderer decides whether to visually honour it.
    const input = 'Line one\nLine two of same paragraph.\n\nSecond paragraph.'
    const out = splitParagraphs(input)
    assert.equal(out.length, 2)
    assert.ok(out[0].includes('Line one'))
    assert.ok(out[0].includes('Line two of same paragraph.'))
    assert.equal(out[1], 'Second paragraph.')
  })
})
