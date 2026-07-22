/**
 * Unit tests for the legacy exercise → TipTap migration helper.
 *
 * Run with the built-in Node test runner + Node's experimental type
 * stripping — no new dev dependency required:
 *
 *     node --experimental-strip-types --test src/lib/exerciseSteps.test.ts
 */

import { strict as assert } from 'node:assert'
import { describe, test } from 'node:test'
// @ts-expect-error - Node-native import path
import { exerciseContentToRichText } from './exerciseSteps.ts'


describe('exerciseContentToRichText', () => {
  test('empty / null / whitespace → empty string', () => {
    assert.equal(exerciseContentToRichText(null), '')
    assert.equal(exerciseContentToRichText(undefined), '')
    assert.equal(exerciseContentToRichText(''), '')
    assert.equal(exerciseContentToRichText('   '), '')
  })

  test('TipTap doc content returned verbatim', () => {
    const doc = JSON.stringify({
      type: 'doc',
      content: [{ type: 'paragraph', content: [{ type: 'text', text: 'hello' }] }],
    })
    assert.equal(exerciseContentToRichText(doc), doc)
  })

  test('legacy step envelope → TipTap orderedList doc', () => {
    const legacy = JSON.stringify({ exercise: { steps: ['Take a breath', 'Notice what changes', 'Write it down'] } })
    const out = exerciseContentToRichText(legacy)
    const parsed = JSON.parse(out)
    assert.equal(parsed.type, 'doc')
    assert.equal(parsed.content[0].type, 'orderedList')
    assert.equal(parsed.content[0].content.length, 3)
    assert.equal(parsed.content[0].content[0].content[0].content[0].text, 'Take a breath')
    assert.equal(parsed.content[0].content[2].content[0].content[0].text, 'Write it down')
  })

  test('legacy envelope with all-empty steps → empty string', () => {
    const legacy = JSON.stringify({ exercise: { steps: ['', '   ', ''] } })
    assert.equal(exerciseContentToRichText(legacy), '')
  })

  test('plain text returned verbatim (renderer falls back to paragraphs)', () => {
    assert.equal(exerciseContentToRichText('just some prose'), 'just some prose')
  })

  test('malformed JSON returned verbatim', () => {
    assert.equal(exerciseContentToRichText('{not json'), '{not json')
  })
})
