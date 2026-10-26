import { strict as assert } from 'node:assert'
import { describe, it } from 'node:test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import { formatCollectivePricingSummary } from './pricing.ts'
import { CREATOR_ONLY_BADGE } from './collectiveDestination.ts'

/**
 * The creator-only Collective card, as the Explore surfaces render it.
 *
 * A note on method, because it matters for what these tests do and do
 * not prove. The frontend test runner is ``node --test`` with
 * ``--experimental-strip-types``, which strips TypeScript annotations
 * but does not transform JSX — importing a ``.tsx`` component fails
 * with ``ERR_UNKNOWN_FILE_EXTENSION``. So there is no way to render the
 * component here without adding a test framework and a JSX transform.
 *
 * What these assert instead is the **structure that governs the
 * render**: that the pricing pill sits inside a ``creator_only`` guard
 * rather than being reworded, that the badge renders the shared
 * constant, and that the label and destination come from the shared
 * rule. Comments are stripped first — this file and the component both
 * discuss "Free to join" in prose, and a blunt substring check would
 * pass on the explanation rather than the code.
 *
 * The actual rendered markup is verified against production after
 * deploy, which is the only place a real render exists.
 */

const SRC = dirname(dirname(fileURLToPath(import.meta.url)))
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

/** Strip comments so a check cannot pass on prose about the code. */
function codeOnly(source: string): string {
  return source
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
}

const CARD = 'components/explore/CollectiveCard.tsx'

/** A World-Builders-shaped card, as ``/api/public/spaces`` returns it. */
const wbCard = {
  pricing_type: 'free' as const,
  pricing_currency: 'AUD',
  pricing_amount_cents: null,
  pricing_note: null,
  has_paid_internal_content: false,
  derived_has_paid_internal_content: false,
  paid_content_summary: null,
  included_access_summary: null,
  min_paid_pathway_price_cents: null,
  join_policy: 'open' as const,
}

describe('the misleading pricing pill', () => {
  it('the summary really would say "Free to join · all included"', () => {
    // The defect, demonstrated rather than asserted from memory: with
    // World Builders' actual pricing fields, the shared helper reports
    // free public joining. Neither half is true — ``join_space`` and
    // ``request_access`` both answer 403, and membership comes from
    // creator eligibility rather than being chosen.
    assert.equal(
      formatCollectivePricingSummary(wbCard),
      'Free to join · all included',
    )
  })

  it('so the card does not render it for a creator-only Collective', () => {
    const code = codeOnly(read(CARD))
    const at = code.indexOf('formatCollectivePricingSummary(space)')
    assert.ok(at > 0, 'the summary call still exists for ordinary cards')
    // The call sits inside a negated creator_only guard.
    const guard = code.lastIndexOf('!space.creator_only', at)
    assert.ok(guard > 0 && guard < at,
      'the pricing pill must be behind a !creator_only guard')
  })

  it('it was removed, not reworded', () => {
    // Replacing it with softer pricing language would be the same
    // mistake in quieter words.
    const code = codeOnly(read(CARD))
    for (const phrase of ['Free to join', 'all included', 'Free ·', 'No cost']) {
      assert.ok(!code.includes(phrase), `card must not hardcode "${phrase}"`)
    }
  })

  it('ordinary cards keep their pricing summary', () => {
    // The helper is accurate for them, and the guard is a negation —
    // so an ordinary card still reaches it.
    const code = codeOnly(read(CARD))
    assert.match(code, /formatCollectivePricingSummary\(space\)/)
    assert.equal(
      formatCollectivePricingSummary({ ...wbCard, min_paid_pathway_price_cents: 2500,
        derived_has_paid_internal_content: true }),
      'Free to join · pathways from $25 AUD',
    )
  })
})

describe('the badge', () => {
  it('reads For Creators Only', () => {
    assert.equal(CREATOR_ONLY_BADGE, 'For Creators Only')
  })

  it('the card renders the shared constant, not its own string', () => {
    const code = codeOnly(read(CARD))
    assert.match(code, /\{CREATOR_ONLY_BADGE\}/)
    assert.ok(!code.includes("'For Creators"), 'no hardcoded badge copy')
  })

  it('it keeps the existing pill styling and position', () => {
    const code = codeOnly(read(CARD))
    // Same class string as the Joined badge — one visual language.
    const pill = /rounded-full px-2\.5 py-0\.5 text-\[10px\] font-semibold uppercase tracking-wide/g
    assert.ok((code.match(pill) ?? []).length >= 2, 'both badges share the pill')
    // Still in the top-left badge row, which is a wrapping flex.
    assert.match(code, /absolute left-3 top-3 flex flex-wrap gap-1\.5/)
  })

  it('the longer text cannot break mid-phrase', () => {
    // "For Creators Only" is three words in a wrapping flex row.
    const code = codeOnly(read(CARD))
    assert.match(code, /whitespace-nowrap rounded-full px-2\.5 py-0\.5/)
  })

  it('ordinary cards get no creator-only badge', () => {
    const code = codeOnly(read(CARD))
    // The render site, not the import at the top of the file.
    const at = code.indexOf('{CREATOR_ONLY_BADGE}')
    assert.ok(at > 0, 'the badge is rendered somewhere')
    // The nearest preceding guard is the creator_only one.
    const guard = code.lastIndexOf('space.creator_only &&', at)
    assert.ok(guard > 0 && guard < at,
      'the badge must sit behind a creator_only guard')
  })
})

describe('both Explore surfaces apply the same rules', () => {
  it('the card is the only place either is decided', () => {
    // Explore and Discover Places both render this component, so there
    // is no second code path to keep in step.
    const exp = read('components/explore/ExploreCollectivesExperience.tsx')
    assert.equal((exp.match(/<CollectiveCard/g) ?? []).length, 1)
  })

  it('the signed-in Explore passes the viewer through', () => {
    // Signed in or not, the same component decides — the page only
    // supplies who is asking.
    assert.match(read('app/spaces/page.tsx'), /isCreator=\{isCreator\}/)
    assert.match(read('app/spaces/page.tsx'), /joinedSlugs=\{joinedSlugs\}/)
    const exp = read('components/explore/ExploreCollectivesExperience.tsx')
    assert.match(exp, /isJoined=\{joinedSet\.has\(space\.slug\)\}/)
    assert.match(exp, /isCreator=\{isCreator\}/)
  })

  it('the dashboard card is deliberately untouched', () => {
    // It renders only Collectives the viewer already belongs to, and
    // its destination already matches — /spaces/{slug}. Its uniform
    // "Continue →" is its own convention and changing it for one
    // Collective would make that grid inconsistent with itself.
    const dash = read('app/dashboard/page.tsx')
    assert.match(dash, /href=\{`\/spaces\/\$\{card\.membership\.space_slug\}`\}/)
  })
})
