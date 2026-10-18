import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * Offer Pages is retired: no entry point, nothing deleted.
 *
 * Offer Pages was an unlaunched experiment in mini sales pages for
 * Creators, last seen in Creator Studio as a muted "Offer Pages ·
 * Coming later" item. It is retired because the new digital-products
 * feature is called **Offerings**, and two adjacent Creator Studio
 * entries one letter apart would be a permanent source of confusion.
 *
 * This file pins both halves of that decision, because each one can
 * regress in the opposite direction:
 *
 *  1. The navigation item is gone, and stays gone. Re-adding it — or
 *     reaching for it as a convenient home for Offerings — is the
 *     regression the first half guards.
 *
 *  2. Nothing else was removed. The routes, the editor, the public
 *     page and the API client still exist, because retiring a feature
 *     is not deleting its data. A future "finish the cleanup" change
 *     that deletes them is a *product* decision requiring approval,
 *     and these assertions make it fail a test rather than pass
 *     quietly. They are not a claim that the code is reachable by a
 *     Creator — it deliberately is not.
 *
 * Comments are stripped before matching. This file and the sidebar
 * both discuss Offer Pages at length precisely because it is retired,
 * so a raw substring check would match the explanation rather than a
 * real nav entry.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

const codeOnly = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const SIDEBAR = 'app/creator-studio/CreatorStudioSidebar.tsx'

describe('Offer Pages has no entry point in Creator Studio', () => {
  test('the sidebar declares no Offer Pages item', () => {
    const src = codeOnly(SIDEBAR)
    assert.ok(
      !src.includes("href: '/creator-studio/offers'"),
      'the retired Offer Pages nav item is back in the sidebar',
    )
    assert.ok(
      !src.includes("'Offer Pages'"),
      'an Offer Pages label is back in the sidebar',
    )
  })

  test('no navigation item is paused, so none says "Coming later"', () => {
    // Offer Pages was the only paused item. The capability itself is
    // kept for a future not-yet-open surface, but an item using it
    // today would be a new product decision, not a side effect of
    // this change.
    const src = codeOnly(SIDEBAR)
    assert.ok(
      !/paused:\s*true/.test(src),
      'a nav item is paused again — "Coming later" is a product decision',
    )
  })

  test('Offerings must not be introduced as the Offer Pages route', () => {
    // The specific mistake this prevents: wiring the new Offerings
    // feature to /creator-studio/offers because the route already
    // exists. Offerings is its own feature with its own route.
    const src = codeOnly(SIDEBAR)
    const offeringsItem = src
      .split('\n')
      .find((l) => /href: '\/creator-studio\/offering/.test(l))
    if (offeringsItem) {
      assert.ok(
        !offeringsItem.includes('/creator-studio/offers'),
        'Offerings must not reuse the Offer Pages route',
      )
    }
  })
})

describe('retiring Offer Pages removed no code or data', () => {
  // Each of these is a deliberate survivor. If a later change deletes
  // one, that is the approval-gated cleanup — not this change.
  for (const path of [
    'app/creator-studio/offers/page.tsx',
    'app/creator-studio/offers/OffersIndexClient.tsx',
    'app/creator-studio/offers/OfferPagesShortcut.tsx',
    'app/creator-studio/offers/[offerSlug]/page.tsx',
    'app/creator-studio/offers/[offerSlug]/OfferPageEditor.tsx',
    'app/spaces/[slug]/offers/[offerSlug]/page.tsx',
  ]) {
    test(`${path} still exists`, () => {
      assert.ok(
        existsSync(join(SRC, path)),
        `${path} was deleted; retiring the feature must not remove it`,
      )
    })
  }

  test('the API client still exposes the Offer Page reads', () => {
    const src = codeOnly('lib/serverApi.ts')
    assert.match(src, /getPublicOfferPage/)
  })

  test('the editor shortcuts stay disabled by their own flag', () => {
    // Two components carry OFFER_PAGES_PAUSED and early-return null,
    // which is what keeps the Pathway, Gathering Series and Gathering
    // editors free of Offer Page cards. The nav item's removal does
    // not cover these surfaces, so their own guard must remain.
    for (const path of [
      'app/creator-studio/offers/OfferPagesShortcut.tsx',
      'app/creator-studio/offers/SeriesChildOfferHint.tsx',
    ]) {
      const src = codeOnly(path)
      assert.match(
        src,
        /const OFFER_PAGES_PAUSED = true/,
        `${path} must keep its own disable flag`,
      )
      assert.match(
        src,
        /if \(OFFER_PAGES_PAUSED\) return null/,
        `${path} must still render nothing`,
      )
    }
  })
})
