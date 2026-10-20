import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, existsSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * Offer Pages is gone from the frontend, and must not come back.
 *
 * Offer Pages was an unlaunched experiment in mini sales pages for
 * Creators. Production was verified to hold zero rows — no published
 * pages, no drafts — and the feature was formally retired, so the
 * frontend routes, editors, shortcuts, API client functions and types
 * were all removed.
 *
 * An earlier version of this file asserted the opposite: that each of
 * those files still existed, because the first step only removed the
 * navigation item. That half is obsolete and has been replaced. What
 * stays is the part that still protects a decision:
 *
 *  1. No route, component, type or API function returns.
 *  2. Nothing adjacent was taken with it — the Payment Option types
 *     that happened to live in the Offer Pages section of
 *     ``types/platform.ts``, the plan-gating controls whose names are
 *     confusingly similar, and the Gathering and Pathway editors that
 *     used to host the shortcuts.
 *  3. The new Offerings feature does not inherit the retired routes.
 *
 * The ``offer_pages`` table, migration 104 and the backend model are
 * deliberately NOT asserted here — they are backend concerns, left in
 * place by approval, and covered on that side.
 *
 * Comments are stripped before matching. This file names Offer Pages
 * repeatedly precisely because it is retired, so a raw substring check
 * would match the explanation rather than a real reference.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

const codeOnly = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

describe('no Offer Pages route remains reachable', () => {
  for (const path of [
    'app/creator-studio/offers',
    'app/spaces/[slug]/offers',
    'app/creator-studio/pathways/[pathwaySlug]/PathwayOfferPagesShortcut.tsx',
  ]) {
    test(`${path} does not exist`, () => {
      assert.ok(
        !existsSync(join(SRC, path)),
        `${path} is back; the retired routes must stay unreachable`,
      )
    })
  }

  test('no file under app/ declares an offers route segment', () => {
    // Walks the route tree rather than trusting the three paths above,
    // so an Offer Pages route re-added somewhere new is still caught.
    const offenders: string[] = []
    const walk = (rel: string) => {
      for (const entry of readdirSync(join(SRC, rel), { withFileTypes: true })) {
        const child = `${rel}/${entry.name}`
        if (entry.isDirectory()) {
          if (entry.name === 'offers') offenders.push(child)
          else walk(child)
        }
      }
    }
    walk('app')
    assert.deepEqual(offenders, [], `offers route segments found: ${offenders}`)
  })
})

describe('no Offer Pages code remains in the frontend', () => {
  test('the API client exposes no Offer Page reads', () => {
    const src = codeOnly('lib/serverApi.ts')
    for (const fn of [
      'getCreatorOfferPages',
      'getCreatorOfferPage',
      'getPublicOfferPage',
    ]) {
      assert.ok(!src.includes(fn), `serverApi still exports ${fn}`)
    }
  })

  test('no Offer Page types are declared', () => {
    const src = codeOnly('types/platform.ts')
    // Anchored on "OfferPage", not on the prefix "Offer".
    //
    // The looser pattern this replaces matched `CreatorOffering`,
    // `OfferingCover` and every other Offerings type added in B6/B7 —
    // a different, live feature. It would have failed on any future
    // type merely beginning with those letters, which is the classic
    // ban-the-word-instead-of-the-thing mistake: the retirement being
    // guarded is Offer *Pages*, so that is what the pattern names.
    assert.ok(
      !/export (?:type|interface) (?:Public|Creator)?OfferPage/.test(src),
      'an Offer Page type is back in types/platform.ts',
    )
    // And the guard must still be capable of failing.
    assert.ok(
      /export (?:type|interface) (?:Public|Creator)?OfferPage/.test(
        'export interface CreatorOfferPage {',
      ),
      'the pattern no longer detects an Offer Page type at all',
    )
  })

  test('the shortcut components are not imported anywhere', () => {
    for (const name of ['OfferPagesShortcut', 'SeriesChildOfferHint']) {
      const hits: string[] = []
      const walk = (rel: string) => {
        for (const entry of readdirSync(join(SRC, rel), { withFileTypes: true })) {
          const child = `${rel}/${entry.name}`
          if (entry.isDirectory()) walk(child)
          else if (/\.tsx?$/.test(entry.name)) {
            if (codeOnly(child).includes(name)) hits.push(child)
          }
        }
      }
      walk('app')
      assert.deepEqual(hits, [], `${name} is referenced again by ${hits}`)
    }
  })
})

describe('retiring Offer Pages took nothing adjacent with it', () => {
  test('the public Payment Option types survive', () => {
    // These sat inside the Offer Pages section of types/platform.ts
    // purely because that surface first exposed them. lib/paymentPlan.ts
    // reads them, so removing the section wholesale would have broken
    // live commerce code.
    const src = codeOnly('types/platform.ts')
    assert.match(src, /export interface PublicPaymentOption\b/)
    assert.match(src, /export interface PublicPaymentOptionSchedule\b/)
    assert.match(codeOnly('lib/paymentPlan.ts'), /PublicPaymentOption/)
  })

  test('the commercial plan controls are untouched', () => {
    // ``requiresPaidOffers`` / ``paidOffersEnabled`` are the plan gate.
    // Their names are one word away from Offer Pages and they have
    // nothing to do with it.
    const sidebar = codeOnly('app/creator-studio/CreatorStudioSidebar.tsx')
    assert.match(sidebar, /requiresPaidOffers\?: boolean/)
    assert.match(sidebar, /paidOffersEnabled\?: boolean/)
    assert.match(
      sidebar,
      /items\.filter\(\s*\(\{ requiresPaidOffers \}\) =>/,
      'the plan filter must survive the Offer Pages removal',
    )
    assert.match(
      codeOnly('app/creator-studio/layout.tsx'),
      /current_plan\?\.paid_offers_enabled/,
    )
  })

  test('the editors that hosted the shortcuts still render', () => {
    // Each kept every unrelated card and fetch; only the Offer Pages
    // shortcut and the two reads that fed it were removed.
    const series = codeOnly('app/creator-studio/gathering-series/[seriesSlug]/page.tsx')
    assert.match(series, /SeriesEditorClient/)
    assert.match(series, /getCreatorSeriesPaymentOptions/)

    const pathway = codeOnly('app/creator-studio/pathways/[pathwaySlug]/settings/page.tsx')
    assert.match(pathway, /PathwaySettingsClient/)
    assert.match(pathway, /PathwayHeader/)

    const gathering = codeOnly('app/creator/spaces/[slug]/events/[eventId]/EventEditorTabs.tsx')
    assert.match(gathering, /EventForm/)
    assert.match(gathering, /EventManagePanel/)
    assert.match(gathering, /AboutPageEditor/)
  })

  test('no navigation item is paused, so none says "Coming later"', () => {
    // Offer Pages was the only paused item. The capability is kept for
    // a future not-yet-open surface; an item using it today would be a
    // new product decision.
    const src = codeOnly('app/creator-studio/CreatorStudioSidebar.tsx')
    assert.ok(!/paused:\s*true/.test(src), 'a nav item is paused again')
  })

  test('Offerings must not inherit the retired route', () => {
    const src = codeOnly('app/creator-studio/CreatorStudioSidebar.tsx')
    const item = src
      .split('\n')
      .find((l) => /href: '\/creator-studio\/offering/.test(l))
    if (item) {
      assert.ok(
        !item.includes('/creator-studio/offers'),
        'Offerings must not reuse the Offer Pages route',
      )
    }
  })
})
