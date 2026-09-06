/**
 * SEC-016 — safeHref navigation guard tests.
 *
 * Run with:
 *
 *   node --experimental-strip-types --test src/lib/safeHref.test.ts
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
// @ts-expect-error - Node-native import path
import { safeHref } from './safeHref.ts'


describe('safeHref — safe URLs pass through', () => {
  test('https', () => {
    assert.equal(safeHref('https://example.com/x'), 'https://example.com/x')
  })
  test('http', () => {
    assert.equal(safeHref('http://example.com'), 'http://example.com')
  })
  test('mailto with address', () => {
    assert.equal(safeHref('mailto:a@b.com'), 'mailto:a@b.com')
  })
  test('single-slash internal path', () => {
    assert.equal(safeHref('/spaces/foo'), '/spaces/foo')
  })
  test('trims surrounding whitespace on safe URLs', () => {
    assert.equal(safeHref('  https://example.com  '), 'https://example.com')
  })
})


describe('safeHref — dangerous schemes return null', () => {
  const dangerous = [
    'javascript:alert(1)',
    'JavaScript:alert(1)',
    'JAVASCRIPT:alert(1)',
    '   javascript:alert(1)   ',
    '\tjavascript:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'DATA:text/html,foo',
    'vbscript:msgbox("xss")',
    'VBScript:msgbox("xss")',
    'blob:https://evil/xxx',
    'file:///etc/passwd',
    'ftp://example.com',
    'tel:+15555555555',
  ]

  for (const raw of dangerous) {
    test(`rejects ${JSON.stringify(raw)}`, () => {
      assert.equal(safeHref(raw), null)
    })
  }
})


describe('safeHref — protocol-relative URLs return null', () => {
  test('//host is not a same-origin path', () => {
    assert.equal(safeHref('//evil.com/x'), null)
  })
  test('   //host with whitespace is still not a same-origin path', () => {
    assert.equal(safeHref('   //evil.com/x'), null)
  })
})


describe('safeHref — empty / nullish returns null', () => {
  test('empty string', () => {
    assert.equal(safeHref(''), null)
  })
  test('whitespace-only', () => {
    assert.equal(safeHref('   '), null)
  })
  test('null', () => {
    assert.equal(safeHref(null), null)
  })
  test('undefined', () => {
    assert.equal(safeHref(undefined), null)
  })
})
