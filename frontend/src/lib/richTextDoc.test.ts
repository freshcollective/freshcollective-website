import { describe, it } from 'node:test'
import assert from 'node:assert/strict'

import {
  docHasContent,
  docLeadsWithHeading,
  tryParseDoc,
} from './richTextDoc.ts'

// A snapshot of the shape we actually see in the DB (world-builders
// guidance_start_body): heading → bold paragraph → heading → paragraph.
const AUTHORED_WORLD_BUILDERS = JSON.stringify({
  type: 'doc',
  content: [
    { type: 'heading', attrs: { level: 1 },
      content: [{ type: 'text', text: '🌍 Welcome to World Builders' }] },
    { type: 'paragraph',
      content: [{ type: 'text', marks: [{ type: 'bold' }],
        text: 'The shared home for Fresh Collective Creators.' }] },
    { type: 'heading', attrs: { level: 3 },
      content: [{ type: 'text', text: 'Your journey starts here...' }] },
  ],
})

describe('tryParseDoc', () => {
  it('returns the doc for valid TipTap JSON', () => {
    const doc = tryParseDoc(AUTHORED_WORLD_BUILDERS)
    assert.ok(doc)
    assert.equal(doc.type, 'doc')
  })

  it('returns null for null / empty / whitespace', () => {
    assert.equal(tryParseDoc(null), null)
    assert.equal(tryParseDoc(undefined), null)
    assert.equal(tryParseDoc(''), null)
  })

  it('returns null for plain-text (legacy pre-TipTap rows)', () => {
    assert.equal(tryParseDoc('Begin with the Foundations pathway.'), null)
  })

  it('returns null for JSON that is not a TipTap doc', () => {
    assert.equal(tryParseDoc('{"type":"paragraph"}'), null)
    assert.equal(tryParseDoc('[]'), null)
  })
})


describe('docHasContent', () => {
  it('true for an authored doc', () => {
    assert.equal(docHasContent(tryParseDoc(AUTHORED_WORLD_BUILDERS)), true)
  })

  it('false for null / not-a-doc', () => {
    assert.equal(docHasContent(null), false)
  })

  it('false for a doc containing only empty paragraphs', () => {
    const doc = tryParseDoc(JSON.stringify({
      type: 'doc',
      content: [
        { type: 'paragraph' },
        { type: 'paragraph', content: [] },
      ],
    }))
    assert.equal(docHasContent(doc), false)
  })

  it('false for a paragraph whose only child is a hardBreak', () => {
    const doc = tryParseDoc(JSON.stringify({
      type: 'doc',
      content: [
        { type: 'paragraph', content: [{ type: 'hardBreak' }] },
      ],
    }))
    assert.equal(docHasContent(doc), false)
  })

  it('true even if the only content is a heading with text', () => {
    const doc = tryParseDoc(JSON.stringify({
      type: 'doc',
      content: [
        { type: 'heading', attrs: { level: 2 },
          content: [{ type: 'text', text: 'Hello' }] },
      ],
    }))
    assert.equal(docHasContent(doc), true)
  })

  it('false for a text node with an empty string', () => {
    const doc = tryParseDoc(JSON.stringify({
      type: 'doc',
      content: [{ type: 'paragraph', content: [{ type: 'text', text: '' }] }],
    }))
    assert.equal(docHasContent(doc), false)
  })
})


describe('docLeadsWithHeading', () => {
  it('true when the first block is a heading (matches world-builders)', () => {
    assert.equal(docLeadsWithHeading(tryParseDoc(AUTHORED_WORLD_BUILDERS)), true)
  })

  it('false when the first block is a paragraph', () => {
    const doc = tryParseDoc(JSON.stringify({
      type: 'doc',
      content: [
        { type: 'paragraph', content: [{ type: 'text', text: 'Hello' }] },
        { type: 'heading', attrs: { level: 2 },
          content: [{ type: 'text', text: 'Later' }] },
      ],
    }))
    assert.equal(docLeadsWithHeading(doc), false)
  })

  it('skips leading empty paragraphs when deciding the "first" block', () => {
    // A stray empty paragraph inserted before a heading (e.g. from a
    // paste) shouldn't disqualify the heading from being the leader.
    const doc = tryParseDoc(JSON.stringify({
      type: 'doc',
      content: [
        { type: 'paragraph' },
        { type: 'heading', attrs: { level: 1 },
          content: [{ type: 'text', text: 'Welcome' }] },
      ],
    }))
    assert.equal(docLeadsWithHeading(doc), true)
  })

  it('false for null / empty doc', () => {
    assert.equal(docLeadsWithHeading(null), false)
    assert.equal(docLeadsWithHeading(tryParseDoc('{"type":"doc","content":[]}')), false)
  })
})
