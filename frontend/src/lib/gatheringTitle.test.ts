import { describe, it } from 'node:test'
import assert from 'node:assert/strict'

import { extractSessionTheme } from './gatheringTitle.ts'

describe('extractSessionTheme', () => {
  it('extracts the theme after an em-dash', () => {
    assert.equal(
      extractSessionTheme('Saturday EMBODY Session — Radiance'),
      'Radiance',
    )
  })

  it('extracts the theme after an en-dash', () => {
    assert.equal(
      extractSessionTheme('Winter Workshop – Roots'),
      'Roots',
    )
  })

  it('extracts the theme after a spaced hyphen', () => {
    assert.equal(
      extractSessionTheme('Morning Circle - Presence'),
      'Presence',
    )
  })

  it('extracts the theme after a colon', () => {
    assert.equal(
      extractSessionTheme('Deep Dive: Vision'),
      'Vision',
    )
  })

  it('takes the LAST separator when several exist', () => {
    assert.equal(
      extractSessionTheme('Saturday — EMBODY Session — Expression'),
      'Expression',
    )
  })

  it('returns the full title when no separator is present', () => {
    assert.equal(
      extractSessionTheme('Grove Circle'),
      'Grove Circle',
    )
  })

  it('leaves hyphenated words like "post-work" alone', () => {
    // No whitespace-flanked separator → returned unchanged.
    assert.equal(
      extractSessionTheme('Post-work Reset'),
      'Post-work Reset',
    )
  })

  it('trims surrounding whitespace', () => {
    assert.equal(
      extractSessionTheme('  Grove Circle  '),
      'Grove Circle',
    )
  })

  it('falls back to the full title when the trailing segment is empty', () => {
    assert.equal(
      extractSessionTheme('Dangling Separator — '),
      'Dangling Separator —',
    )
  })
})
