/**
 * Structural tests for the standalone Gathering card.
 *
 * Same pattern as ``src/app/creator-studio/settings/DangerZone.test.ts``:
 * read the source and assert the load-bearing invariants without spinning
 * up React DOM.
 *
 * Why this file exists
 * --------------------
 * The Attendance dashboard entry point was added as a ``<button>`` with an
 * ``onClick`` that set ``window.location.href``, so that it could live
 * inside the card's outer ``<Link>`` without nesting one anchor in
 * another. The component has no ``'use client'`` directive, so every
 * render of the Gatherings page failed with:
 *
 *   Event handlers cannot be passed to Client Component props
 *
 * Both halves of that mistake are asserted against here, because either
 * one alone would bring it back: no event-handler props in a Server
 * Component, and no anchor nested inside the card link.
 *
 * Comments are stripped before matching. The prose above deliberately
 * contains the very strings being banned, and a blunt ``includes()``
 * against the raw file would fail on its own documentation.
 *
 * Run with:
 *
 *   node --experimental-strip-types --test \
 *     src/app/creator-studio/gatherings/StandaloneGatheringCard.test.ts
 */

import { strict as assert } from 'node:assert'
import { describe, test } from 'node:test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const _here = dirname(fileURLToPath(import.meta.url))
const SOURCE = readFileSync(join(_here, 'StandaloneGatheringCard.tsx'), 'utf-8')
const CODE = SOURCE.replace(/\/\*[^]*?\*\//g, '')
  .split('\n')
  .map((line) => line.replace(/\/\/.*$/, ''))
  .join('\n')


describe('StandaloneGatheringCard — stays a Server Component', () => {
  test('declares no client directive', () => {
    // If this ever needs to flip, the handler assertions below stop
    // being the right contract and this file should be revisited
    // rather than the directive quietly added.
    assert.ok(
      !/^\s*['"]use client['"]/m.test(SOURCE),
      'card is a Server Component by design; nothing here needs browser state',
    )
  })

  test('passes no event-handler prop to any element', () => {
    // React serialises Server Component output, and a function is not
    // serialisable. Any onFoo={...} prop here is a production 500 on
    // the whole Gatherings page, not a degraded button.
    const handlers = CODE.match(/\bon[A-Z]\w*\s*=\s*\{/g) ?? []
    assert.deepEqual(
      handlers, [],
      `event handlers cannot cross the server/client boundary: found ${handlers.join(', ')}`,
    )
  })

  test('reaches for no browser globals', () => {
    // ``window.location.href`` was how the old button navigated. There
    // is no window on the server.
    assert.ok(
      !/\b(window|document|localStorage)\s*\./.test(CODE),
      'no browser global may be dereferenced in a Server Component',
    )
  })
})


describe('StandaloneGatheringCard — link structure is valid HTML', () => {
  test('the card chrome is a div, so the two links can be siblings', () => {
    // An <a> inside an <a> is invalid and React will not render it.
    // The chrome (group/rounded/border/hover-lift) therefore sits on a
    // plain element and both links are its children.
    assert.match(
      CODE,
      /<div\s+[^>]*className=\{`group flex h-full flex-col overflow-hidden rounded-2xl/,
      'expected the card chrome on a <div>, not on the edit <Link>',
    )
  })

  test('the attendance Link is not nested inside the card Link', () => {
    const cardLink = CODE.indexOf('<Link href={editHref}')
    const cardLinkClose = CODE.indexOf('</Link>', cardLink)
    const attendanceLink = CODE.indexOf('/attendance`}')

    assert.ok(cardLink !== -1, 'expected the card link to still exist')
    assert.ok(attendanceLink !== -1, 'expected an attendance link')
    assert.ok(
      attendanceLink > cardLinkClose,
      'the attendance Link must come after the card Link closes, ' +
        'never inside it',
    )
  })

  test('the card still links to the editor', () => {
    assert.match(
      CODE,
      /const editHref = `\/creator\/spaces\/\$\{slug\}\/events\/\$\{event\.id\}`/,
      'the main card target must remain the Gathering editor',
    )
  })

  test('the attendance link points at the attendance route', () => {
    assert.match(
      CODE,
      /href=\{`\/creator\/spaces\/\$\{slug\}\/events\/\$\{event\.id\}\/attendance`\}/,
      'attendance entry point must be a real href, not a programmatic jump',
    )
  })
})


describe('StandaloneGatheringCard — attendance visibility is unchanged', () => {
  test('shown only when the Gathering takes bookings and is not cancelled', () => {
    // The condition that shipped with the Attendance dashboard. A
    // Gathering with no bookings has nothing to show, and a cancelled
    // one should not invite the creator to work its door list.
    assert.match(
      CODE,
      /showAttendance\s*=\s*event\.requires_booking\s*&&\s*!isCancelled/,
      'visibility must stay `event.requires_booking && !isCancelled`',
    )
  })

  test('that condition is what gates the link', () => {
    assert.match(
      CODE,
      /\{showAttendance\s*&&\s*\(/,
      'the attendance block must be gated by showAttendance',
    )
  })
})
