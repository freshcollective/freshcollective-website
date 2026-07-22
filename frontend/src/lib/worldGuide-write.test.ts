/**
 * Unit tests for the Write-mode converters.
 *
 * Run with the frontend test script:
 *
 *     npm test
 *
 * Exercises the pure Markdown → HTML transform and the DOM-tree →
 * Markdown walker with hand-built WNode fixtures — Node needs no DOM
 * parser to test the walker itself.
 */

import { strict as assert } from 'node:assert'
import { describe, test } from 'node:test'
// @ts-expect-error - Node-native import path
import {
  markdownToWriteHtml,
  walkWNodeToMarkdown,
  el,
  text,
} from './worldGuide-write.ts'


// ---------------------------------------------------------------------------
// markdownToWriteHtml
// ---------------------------------------------------------------------------


describe('markdownToWriteHtml', () => {
  test('empty input becomes a single empty paragraph so the caret has a home', () => {
    assert.equal(markdownToWriteHtml(''), '<p></p>')
    assert.equal(markdownToWriteHtml('   \n  '), '<p></p>')
  })

  test('emits standard HTML for common blocks', () => {
    const html = markdownToWriteHtml('## Heading\n\nBody paragraph.')
    assert.match(html, /<h2>Heading<\/h2>/)
    assert.match(html, /<p>Body paragraph\.<\/p>/)
  })

  test('wraps tables in a wg-md-block envelope with encoded source', () => {
    const md = '| Role | Duty |\n| --- | --- |\n| A | B |'
    const html = markdownToWriteHtml(md)
    assert.match(html, /class="wg-md-block"/)
    assert.match(html, /data-md-kind="table"/)
    // The rendered table is inside the envelope for the preview.
    assert.match(html, /<table>/)
    // The raw Markdown source is preserved via data-md so we can
    // round-trip it back to Markdown without touching the table's
    // content.
    assert.match(html, /data-md="([^"]+)"/)
  })

  test('preserves callouts as wg-callout asides for the Callout node to pick up', () => {
    const html = markdownToWriteHtml('> [!note] Heads up\n> Body text')
    assert.match(html, /<aside class="wg-callout wg-callout-note">/)
    assert.match(html, /wg-callout-title.*Heads up/)
  })

  test('preserves images as <img> for the Image node', () => {
    const html = markdownToWriteHtml('![alt text](/uploads/x.png)')
    assert.match(html, /<img [^>]*src="\/uploads\/x.png"/)
    assert.match(html, /alt="alt text"/)
  })

  test('preserves fenced code blocks', () => {
    const html = markdownToWriteHtml('```\nconst x = 1\n```')
    assert.match(html, /<pre><code>const x = 1<\/code><\/pre>/)
  })
})


// ---------------------------------------------------------------------------
// walkWNodeToMarkdown — driven by hand-built WNode trees so we get real
// walker coverage in Node without needing a DOM parser.
// ---------------------------------------------------------------------------


function body(...children: ReturnType<typeof el>[]): ReturnType<typeof el> {
  return el('BODY', children)
}


describe('walkWNodeToMarkdown', () => {
  test('paragraph', () => {
    const md = walkWNodeToMarkdown(body(el('P', [text('Hello there')])))
    assert.equal(md.trim(), 'Hello there')
  })

  test('headings H1/H2/H3', () => {
    assert.equal(walkWNodeToMarkdown(body(el('H1', [text('Title')]))).trim(), '# Title')
    assert.equal(walkWNodeToMarkdown(body(el('H2', [text('Sub')]))).trim(), '## Sub')
    assert.equal(walkWNodeToMarkdown(body(el('H3', [text('Deep')]))).trim(), '### Deep')
  })

  test('bold + italic marks', () => {
    const md = walkWNodeToMarkdown(body(
      el('P', [
        text('This is '),
        el('STRONG', [text('bold')]),
        text(' and '),
        el('EM', [text('italic')]),
      ]),
    ))
    assert.equal(md.trim(), 'This is **bold** and *italic*')
  })

  test('inline and fenced code', () => {
    const inline = walkWNodeToMarkdown(body(
      el('P', [text('use '), el('CODE', [text('render()')])]),
    ))
    assert.equal(inline.trim(), 'use `render()`')
    const fenced = walkWNodeToMarkdown(body(
      el('PRE', [el('CODE', [text('let x = 1')])]),
    ))
    assert.match(fenced, /```\nlet x = 1\n```/)
  })

  test('blockquote', () => {
    const md = walkWNodeToMarkdown(body(
      el('BLOCKQUOTE', [el('P', [text('one')]), el('P', [text('two')])]),
    ))
    assert.equal(md.trim(), '> one\n>\n> two')
  })

  test('bullet list', () => {
    const md = walkWNodeToMarkdown(body(
      el('UL', [
        el('LI', [text('First')]),
        el('LI', [text('Second')]),
      ]),
    ))
    assert.equal(md.trim(), '- First\n- Second')
  })

  test('numbered list', () => {
    const md = walkWNodeToMarkdown(body(
      el('OL', [
        el('LI', [text('One')]),
        el('LI', [text('Two')]),
      ]),
    ))
    assert.equal(md.trim(), '1. One\n2. Two')
  })

  test('task list preserves checked state without carrying it forward for new items', () => {
    const md = walkWNodeToMarkdown(body(
      el('UL', { class: 'wg-tasklist' }, [
        el('LI', { 'data-checked': 'true' }, [text('done')]),
        el('LI', { 'data-checked': 'false' }, [text('open')]),
      ]),
    ))
    assert.equal(md.trim(), '- [x] done\n- [ ] open')
  })

  test('link', () => {
    const md = walkWNodeToMarkdown(body(
      el('P', [
        text('Read '),
        el('A', { href: 'https://example.com' }, [text('the docs')]),
        text('.'),
      ]),
    ))
    assert.equal(md.trim(), 'Read [the docs](https://example.com).')
  })

  test('image', () => {
    const md = walkWNodeToMarkdown(body(
      el('P', [
        el('IMG', { src: '/uploads/x.png', alt: 'A diagram' }, []),
      ]),
    ))
    assert.equal(md.trim(), '![A diagram](/uploads/x.png)')
  })

  test('horizontal rule', () => {
    const md = walkWNodeToMarkdown(body(el('HR', {}, [])))
    assert.equal(md.trim(), '---')
  })

  test('callout aside', () => {
    const md = walkWNodeToMarkdown(body(
      el('ASIDE', { class: 'wg-callout wg-callout-note' }, [
        el('DIV', { class: 'wg-callout-title' }, [text('Heads up')]),
        el('DIV', { class: 'wg-callout-body' }, [el('P', [text('Body text')])]),
      ]),
    ))
    assert.equal(md.trim(), '> [!note] Heads up\n> Body text')
  })

  test('table preserved via wg-md-block envelope', () => {
    const raw = '| Role | Duty |\n| --- | --- |\n| A | B |'
    const encoded = encodeURIComponent(raw)
    const md = walkWNodeToMarkdown(body(
      el('DIV', { class: 'wg-md-block', 'data-md': encoded }, [
        el('TABLE', [
          el('THEAD', [el('TR', [el('TH', [text('Role')]), el('TH', [text('Duty')])])]),
          el('TBODY', [el('TR', [el('TD', [text('A')]), el('TD', [text('B')])])]),
        ]),
      ]),
    ))
    assert.equal(md.trim(), raw)
  })

  test('bare <table> without envelope falls back to a best-effort conversion', () => {
    const md = walkWNodeToMarkdown(body(
      el('TABLE', [
        el('THEAD', [el('TR', [el('TH', [text('a')]), el('TH', [text('b')])])]),
        el('TBODY', [el('TR', [el('TD', [text('1')]), el('TD', [text('2')])])]),
      ]),
    ))
    assert.equal(
      md.trim(),
      '| a | b |\n| --- | --- |\n| 1 | 2 |',
    )
  })

  test('unknown elements contribute only their inner content', () => {
    // A <span> or <font> from a paste should not survive as syntax.
    const md = walkWNodeToMarkdown(body(
      el('P', [
        text('mixed '),
        el('SPAN', [text('bold-ish')]),
        text(' words'),
      ]),
    ))
    assert.equal(md.trim(), 'mixed bold-ish words')
  })
})


// ---------------------------------------------------------------------------
// Round-trip: Markdown → HTML → (build WNode from HTML shape) → Markdown
// ---------------------------------------------------------------------------


describe('round-trip', () => {
  test('markdown → write html preserves the round-trip source for tables', () => {
    const md = '| Header | Header |\n| --- | --- |\n| Cell | Cell |'
    const html = markdownToWriteHtml(md)
    const dataMatch = /data-md="([^"]+)"/.exec(html)
    assert.ok(dataMatch, 'expected data-md attribute')
    const decoded = decodeURIComponent(dataMatch![1])
    assert.equal(decoded.trim(), md.trim())
  })
})
