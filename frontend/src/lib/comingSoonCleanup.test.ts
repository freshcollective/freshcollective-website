import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * Three cleanups from the "coming soon" audit, and the many messages
 * the audit found ACCURATE and left alone.
 *
 * The last describe block is the important half. Most "coming soon"
 * copy in this codebase is a legitimate product state — a Pathway
 * status a creator selects, a pricing type they choose, a genuinely
 * unbuilt payment path. A future sweep that removed them by text match
 * would break working surfaces, so they are pinned here as deliberate.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

const FLOW_A = 'app/creator-studio/create/CreateCollectiveForm.tsx'
const FLOW_B = 'app/creator-studio/create-collective/CreateCollectiveFlow.tsx'
const FLOWS = [FLOW_A, FLOW_B]
const PROFILE = 'app/spaces/[slug]/members/[memberId]/page.tsx'
const SERIES = 'app/spaces/[slug]/gathering-series/[series-slug]/page.tsx'
const FOR_CREATORS = 'app/for-creators/page.tsx'

// ---------------------------------------------------------------------------
// 1 · Creator Plus → Ecosystem
// ---------------------------------------------------------------------------

describe('the Collective-limit screens name Ecosystem, not Creator Plus', () => {
  for (const f of FLOWS) {
    test(`${f}: no Creator Plus anywhere`, () => {
      // Renamed offering, not an abandoned one — so the terminology is
      // what was outdated, and both flows had it.
      assert.ok(!/Creator Plus/.test(read(f)), `${f} still says Creator Plus`)
    })

    test(`${f}: Ecosystem is presented as upcoming`, () => {
      const src = read(f)
      assert.match(src, /Explore Ecosystem/)
      assert.match(src, /upcoming option for/)
    })

    test(`${f}: it links to the existing waitlist`, () => {
      assert.match(read(f), /href="\/ecosystem-interest"/)
    })

    test(`${f}: nothing implies it can be bought or upgraded to today`, () => {
      // A waitlist CTA is the honest one here. "Upgrade", "Buy" or a
      // price would promise a purchase that does not exist.
      const src = read(f)
      assert.ok(!/Upgrade to Ecosystem|Buy Ecosystem|Get Ecosystem/i.test(src))
      assert.match(src, /Join the Ecosystem waitlist/)
    })

    test(`${f}: the Collective limit itself is unchanged`, () => {
      // The copy changed; the eligibility rule it describes did not.
      assert.match(read(f), /MAX_COLLECTIVES_FOR_FOUNDING_CREATOR/)
      assert.match(read(f), /Founding Creator access includes up to/)
    })
  }

  test('both flows say the same thing', () => {
    // They are near-duplicate files, which is how the same outdated
    // name came to exist twice. One cannot be updated without the
    // other.
    const sentence = /Need more room to grow\? Explore Ecosystem, our upcoming option for\s+creators building across multiple Collectives\./
    for (const f of FLOWS) {
      assert.match(read(f), sentence, `${f}: wording diverged`)
    }
    const labels = FLOWS.map((f) =>
      /Join the Ecosystem waitlist/.test(read(f)))
    assert.deepEqual(labels, [true, true])
  })

  test('the waitlist destination still exists and is untouched', () => {
    const forCreators = read(FOR_CREATORS)
    assert.match(forCreators, /href: '\/ecosystem-interest'/)
    assert.match(forCreators, /name: 'Ecosystem'/)
    // For Creators still marks it Coming soon — that badge is correct
    // and was not part of this cleanup.
    assert.match(forCreators, /badge: 'Coming soon'/)
  })
})

// ---------------------------------------------------------------------------
// 2 · Member profile placeholders
// ---------------------------------------------------------------------------

describe('the member profile shows no unbuilt placeholders', () => {
  test('the Pathways placeholder row is gone', () => {
    const src = read(PROFILE)
    assert.ok(!/Coming soon\./.test(src))
    // The whole row, not just its text — a label with nothing beside
    // it reads as a loading failure rather than as an absence.
    assert.ok(!/>Pathways</.test(src), 'the empty Pathways row survived')
  })

  test('the Recent contributions card is gone', () => {
    const src = read(PROFILE)
    assert.ok(!/Contributions coming soon/.test(src))
    // The card's only content was the placeholder, so a surviving card
    // would be a titled empty panel.
    assert.ok(!/Recent contributions/.test(src))
  })

  test('the real profile information is intact', () => {
    const src = read(PROFILE)
    for (const kept of ['Role', 'Joined', 'spaces_led', 'Collectives led']) {
      assert.ok(src.includes(kept), `${kept} was removed`)
    }
  })

  test('no data fetching or member functionality was removed', () => {
    // Both placeholders were static TODOs reading nothing. The page
    // must still load the same profile it always did.
    const src = read(PROFILE)
    assert.match(src, /getSpaceMemberProfile|profile\./)
    assert.ok(!/TODO: show pathway progress/.test(src))
    assert.ok(!/TODO: show real contribution history/.test(src))
  })
})

// ---------------------------------------------------------------------------
// 3 · Gathering Series description fallback
// ---------------------------------------------------------------------------

describe('a Series with no description says so plainly', () => {
  test('the wording no longer promises something is coming', () => {
    const src = read(SERIES)
    assert.ok(!/More about this Series is coming soon/.test(src))
    assert.match(src, /No additional details have been provided for this Series\./)
  })

  test('it applies only when the creator wrote no description', () => {
    // The fallback sits in the else branch of the description check,
    // so an authored description still renders instead.
    const src = read(SERIES)
    assert.match(src, /detail\.description/)
    const descAt = src.indexOf('{detail.description}')
    const fallbackAt = src.indexOf('No additional details have been provided')
    assert.ok(descAt > -1, 'the authored description render is gone')
    assert.ok(fallbackAt > descAt, 'the fallback must be the else branch')
  })
})

// ---------------------------------------------------------------------------
// The messages the audit found ACCURATE — pinned so a future sweep
// cannot remove them by text match
// ---------------------------------------------------------------------------

describe('legitimate "coming soon" states are preserved', () => {
  test('coming_soon is still a selectable Pathway status', () => {
    for (const f of [
      'app/creator-studio/pathways/new/NewPathwayClient.tsx',
      'app/creator-studio/pathways/[pathwaySlug]/PathwaySettingsClient.tsx',
    ]) {
      assert.match(read(f), /value="coming_soon"/, `${f}: status option gone`)
    }
    assert.match(
      read('app/creator-studio/pathways/[pathwaySlug]/PathwayHeader.tsx'),
      /coming_soon: 'Coming soon'/,
    )
  })

  test('coming_soon is still a selectable Collective pricing type', () => {
    assert.match(
      read('app/creator-studio/settings/CollectiveSettingsForm.tsx'),
      /value: 'coming_soon'/,
    )
  })

  test('the member-facing paid-access state is unchanged', () => {
    // Driven by the creator's own pricing choice, so it is accurate.
    assert.match(
      read('app/spaces/[slug]/about/SpaceAboutCTA.tsx'),
      /Paid access coming soon/,
    )
  })

  test('the subscription-billing notice stays — it is true', () => {
    // PaymentOptionType.subscription exists in the enum and is
    // referenced nowhere in application code. Removing this would drop
    // a member into a checkout that cannot complete.
    assert.match(
      read('app/spaces/[slug]/pathways/[pathway-slug]/checkout/page.tsx'),
      /Subscription billing is coming soon/,
    )
  })

  test('the Payment Options Gathering notice stays — it is protective', () => {
    // A gathering grant returns a fatal error at fulfilment and marks
    // the purchase blocked, so the warning prevents a broken bundle.
    assert.match(
      read('app/creator-studio/payment-options/[optionId]/ExperiencePickerModal.tsx'),
      /Not yet available for Payment Options/,
    )
  })
})
