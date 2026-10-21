import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

/**
 * Default Offering artwork in World Settings → World Artwork.
 *
 * The five shared cover categories are managed by the same page that
 * owns the dashboard tiles, the homepage scenes and the member cards.
 * These tests pin the decisions that are expressible as source: the
 * section exists, it is its own section rather than extra slots inside
 * Member Dashboard, the five keys match the backend's, and the picker
 * stores a category rather than a URL.
 *
 * Comments are stripped before matching — several checks here would
 * otherwise pass on a word inside an explanatory comment.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

function codeOnly(source: string): string {
  return source
    .replace(/^\s*\/\/.*$/gm, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
}

const CLIENT = 'app/admin/settings/artwork/PlatformArtworkClient.tsx'
const PICKER = 'app/creator-studio/offerings/[offeringSlug]/OfferingDetailsClient.tsx'

/** The GROUPS array, in render order, as declared. */
function groupLabels(): string[] {
  const src = read(CLIENT)
  const start = src.indexOf('const GROUPS: Group[] = [')
  assert.ok(start !== -1, 'GROUPS array no longer declared')
  const end = src.indexOf('\n]', start)
  const body = src.slice(start, end)
  return [...body.matchAll(/label: '([^']+)'/g)].map((m) => m[1])
}

/** The keys declared for one group. */
function groupKeys(groupKey: string): string[] {
  const src = read(CLIENT)
  const at = src.indexOf(`key: '${groupKey}'`)
  assert.ok(at !== -1, `no group with key '${groupKey}'`)
  const after = src.slice(at)
  const keysAt = after.indexOf('keys: [')
  const close = after.indexOf(']', keysAt)
  return [...after.slice(keysAt, close).matchAll(/'([^']+)'/g)].map((m) => m[1])
}

describe('the Default Offering Artwork section', () => {
  test('it exists, with the agreed label', () => {
    assert.ok(
      groupLabels().includes('Default Offering Artwork'),
      'the section is missing from GROUPS',
    )
  })

  test('it sits directly under Member Dashboard', () => {
    // Its own section rather than extra slots inside the dashboard one —
    // these are not dashboard artwork — and placed second so the page
    // stays organised as more shared-artwork categories arrive.
    const labels = groupLabels()
    assert.equal(labels[0], 'Member Dashboard')
    assert.equal(labels[1], 'Default Offering Artwork')
  })

  test('the five slots are not in the Member Dashboard group', () => {
    const dashboard = groupKeys('member_dashboard')
    for (const k of dashboard) {
      assert.ok(
        !k.startsWith('offering_cover_'),
        `${k} is an Offering cover slot but sits in Member Dashboard`,
      )
    }
  })

  test('it carries the agreed description', () => {
    const src = read(CLIENT)
    assert.match(
      src,
      /The shared images used for digital Offerings across Fresh Collective\. Creators can use these defaults or upload their own\./,
    )
  })

  test('it lists exactly the five categories', () => {
    assert.deepEqual(groupKeys('default_offering_artwork'), [
      'offering_cover_workbook_guides',
      'offering_cover_audio',
      'offering_cover_spreadsheet',
      'offering_cover_collections',
      'offering_cover_other_resources',
    ])
  })

  test('each slot declares the Offering cover presentation', () => {
    // Every Offering surface reserves a 3:2 box, so a slot guiding an
    // admin towards another ratio would produce a cropped cover.
    const code = codeOnly(read(CLIENT))
    const at = code.indexOf('OFFERING_COVER_DISPLAY')
    assert.ok(at !== -1, 'the display config is gone')
    const block = code.slice(at, at + 1600)
    assert.match(block, /aspectRatio: '3 \/ 2'/)
    assert.match(block, /1200×800/)
    assert.match(block, /thumbnail is generated automatically/i)
  })

  test('the empty state is described, not left blank', () => {
    // Requirement: an Offering must not show a broken image when a slot
    // is empty. The admin is told what happens instead.
    const code = codeOnly(read(CLIENT))
    assert.match(code, /soft teal gradient until an image is added/i)
  })

  test('no second artwork manager was introduced', () => {
    // The whole point of the change: these slots go through the existing
    // page, which means no new upload control, route or storage call.
    const code = codeOnly(read(CLIENT))
    assert.ok(
      !/offering-covers\//.test(code),
      'the retired offering-covers namespace is referenced here',
    )
    assert.equal(
      (code.match(/const GROUPS: Group\[\] = \[/g) ?? []).length,
      1,
    )
  })
})

describe('the creator cover picker', () => {
  test('it stores a category key, not a URL', () => {
    const code = codeOnly(read(PICKER))
    assert.match(code, /default_cover_key: key/)
    assert.ok(
      !/cover_image_url: url/.test(code),
      'the picker still PATCHes a cover URL',
    )
  })

  test('selection is read from the stored category, not by URL comparison', () => {
    // Comparing URLs could not survive the shared image being replaced —
    // the selected tile would silently stop looking selected.
    const code = codeOnly(read(PICKER))
    assert.match(code, /categoryKey === c\.key/)
    assert.ok(
      !/current === c\.url/.test(code),
      'selection is still inferred by comparing URLs',
    )
  })

  test('a creator upload is detected from its own field', () => {
    const code = codeOnly(read(PICKER))
    assert.match(code, /const isCustom = Boolean\(customCover\)/)
  })

  test('a category with no artwork yet is still selectable and says so', () => {
    const code = codeOnly(read(PICKER))
    assert.match(code, /No shared image yet/)
    // And it previews the real outcome — the same gradient the Offering
    // itself shows — rather than an empty frame.
    assert.match(code, /linear-gradient\(135deg, rgba\(56,160,158/)
  })

  test('the three cover states are tracked separately', () => {
    // shown / customCover / categoryKey. Collapsing them would make
    // "remove my upload and fall back to the category" unexpressible.
    const code = codeOnly(read(PICKER))
    for (const name of ['setCover', 'setCustomCover', 'setCategoryKey']) {
      assert.match(code, new RegExp(name))
    }
  })
})
