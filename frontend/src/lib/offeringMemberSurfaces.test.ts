import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

/**
 * Source contracts for the member-facing Offerings surfaces.
 *
 * These assert on the source rather than on rendered output because
 * the node test runner strips types but not JSX, so a ``.tsx`` file
 * can only be read as text. That is a real limitation and worth being
 * honest about: what follows pins the *decisions* that are expressible
 * as the presence or absence of a line, and the behaviour behind them
 * is covered by the backend suites, which exercise the production
 * handlers against a real database.
 *
 * Comments are stripped before matching. Every one of these checks has
 * a sibling in the repo's history that passed or failed on a word
 * inside an explanatory comment rather than in the code.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

/**
 * Strip comments so a check matches code, not prose.
 *
 * Line comments first, deliberately: a ``//`` comment that mentions
 * ``/*`` would otherwise make the block stripper swallow real code
 * after it. That exact bug has been fixed in this repo once already.
 */
function codeOnly(source: string): string {
  return source
    .replace(/^\s*\/\/.*$/gm, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
}

const ACQUIRE = 'components/offerings/AcquireOffering.tsx'
const DETAIL = 'app/spaces/[slug]/offerings/[offeringSlug]/page.tsx'
const CATALOGUE = 'app/spaces/[slug]/offerings/page.tsx'
const COLLECTION = 'app/dashboard/collection/page.tsx'
const CARD = 'components/spaces/OfferingCard.tsx'
const COLLECTION_CARD = 'components/offerings/CollectionCard.tsx'

describe('the acquisition control', () => {
  test('free and paid go to different endpoints', () => {
    const code = codeOnly(read(ACQUIRE))
    assert.match(code, /\/offerings\/\$\{offering\.slug\}\/acquire/)
    assert.match(code, /'\/api\/checkout\/offering'/)
  })

  test('the free path is a POST with credentials', () => {
    const code = codeOnly(read(ACQUIRE))
    assert.match(code, /method:\s*'POST'/)
    assert.match(code, /credentials:\s*'include'/)
  })

  test('a signed-out visitor is offered an account, not a dead button', () => {
    // The established Pathway and Gathering journey: sign up or log in
    // with ?next= back to this page.
    const code = codeOnly(read(ACQUIRE))
    assert.match(code, /requires_account/)
    assert.match(code, /\/signup\?next=/)
    assert.match(code, /\/login\?next=/)
    assert.ok(
      !/disabled=\{true\}/.test(code),
      'a hard-disabled button would read as a promise withheld',
    )
  })

  test('the membership notice names the Collective and precedes the button', () => {
    const code = codeOnly(read(ACQUIRE))
    assert.match(code, /will_join_collective/)
    assert.match(code, /become a member of/)
    assert.match(code, /collectiveName/)
    // Order matters: for a paid Offering this has to be visible before
    // the payment, not after it.
    const noticeAt = code.indexOf('const notice =')
    const buttonAt = code.indexOf('Purchase Offering')
    assert.ok(noticeAt !== -1 && buttonAt !== -1)
    assert.ok(
      noticeAt < buttonAt,
      'the notice is declared after the button copy — check the render order',
    )
  })

  test('the two approved button labels are used', () => {
    const code = codeOnly(read(ACQUIRE))
    assert.match(code, /'Purchase Offering'/)
    assert.match(code, /'Get this Offering'/)
  })

  test('the approved success wording is used verbatim', () => {
    const code = codeOnly(read(ACQUIRE))
    assert.match(code, /It&rsquo;s yours!/)
    assert.match(code, /added to Your Collection/)
    assert.match(code, /You&rsquo;ve also joined/)
    assert.match(code, /Welcome!/)
  })

  test('an already-owned Offering offers a way in, not a second purchase', () => {
    const code = codeOnly(read(ACQUIRE))
    assert.match(code, /viewer_owns/)
    assert.match(code, /in Your Collection/i)
    assert.match(code, /\/dashboard\/collection/)
  })

  test('the refusal reason comes from the server', () => {
    // The page must not re-derive why acquiring is unavailable; the
    // backend resolved it with the same function the write paths
    // guard with.
    const code = codeOnly(read(ACQUIRE))
    assert.match(code, /acquire_blocked/)
    assert.match(code, /acquire_message/)
  })

  test('an already_owned 409 refreshes rather than reporting an error', () => {
    const code = codeOnly(read(ACQUIRE))
    assert.match(code, /already_owned/)
    assert.match(code, /router\.refresh\(\)/)
  })
})

describe('the Offering detail page', () => {
  test('it states the digital-download nature more than once', () => {
    const code = codeOnly(read(DETAIL))
    const hits = (code.match(/Digital download|digital download/g) ?? []).length
    assert.ok(hits >= 2, `expected the download statement repeated, saw ${hits}`)
  })

  test('it says the cover is an illustration and nothing is posted', () => {
    const code = codeOnly(read(DETAIL))
    assert.match(code, /Cover illustration/)
    assert.match(code, /not part of this/)
    assert.match(code, /nothing physical is posted/)
  })

  test('the price label comes from the server', () => {
    // Two formatters would eventually disagree between the card and
    // the page.
    const code = codeOnly(read(DETAIL))
    assert.match(code, /offering\.price_label/)
    assert.ok(
      !/toFixed\(2\)/.test(code),
      'the page is formatting a price again instead of reading price_label',
    )
  })

  test('the Stripe redirect is not treated as proof of payment', () => {
    const code = codeOnly(read(DETAIL))
    // "purchased=true AND they own it" is the only confirmed state;
    // "purchased=true AND they do not" says so honestly.
    assert.match(code, /justPaidAndConfirmed/)
    assert.match(code, /justPaidAwaitingWebhook/)
    assert.match(code, /viewer_owns/)
  })

  test('a cancelled checkout says nothing was charged', () => {
    const code = codeOnly(read(DETAIL))
    assert.match(code, /cancelled/)
    assert.match(code, /nothing has been charged/)
  })

  test('the acquisition control is delegated, not reimplemented here', () => {
    const code = codeOnly(read(DETAIL))
    assert.match(code, /<AcquireOffering/)
    assert.ok(
      !/api\/checkout/.test(code),
      'the page is calling checkout directly instead of via AcquireOffering',
    )
  })
})

describe('the catalogue', () => {
  test('it guards on the offerings area', () => {
    const code = codeOnly(read(CATALOGUE))
    assert.match(code, /requireArea\(space,\s*'offerings'\)/)
  })

  test('it states the illustration caveat once for the whole grid', () => {
    const code = codeOnly(read(CATALOGUE))
    assert.match(code, /illustrations/)
    assert.match(code, /not included/)
    assert.match(code, /nothing physical is posted/)
  })

  test('it has an empty state rather than a blank page', () => {
    const code = codeOnly(read(CATALOGUE))
    assert.match(code, /No Offerings yet/)
  })
})

describe('the Offering card', () => {
  test('it carries the digital-download badge', () => {
    assert.match(codeOnly(read(CARD)), /Digital download/)
  })

  test('the category comes from the server, not the cover image', () => {
    const code = codeOnly(read(CARD))
    assert.match(code, /offering\.category_label/)
    // Ban the *mechanism*, not a word that happens to appear nearby:
    // the cover manifest's keys are what a client-side derivation
    // would have to match on, so their absence is the real signal.
    // (An earlier version of this check used a dot-matches-newline
    // regex over the whole file and failed on two unrelated lines —
    // which is the hazard with assertions about proximity.)
    for (const coverKey of [
      'workbook-guides', 'audio', 'spreadsheet', 'collections', 'other',
    ]) {
      assert.ok(
        !code.includes(`'${coverKey}'`),
        `the card maps cover key '${coverKey}' to something — the ` +
        'category must come from the files, via category_label',
      )
    }
  })

  test('an owned Offering shows a way in rather than a price', () => {
    const code = codeOnly(read(CARD))
    assert.match(code, /viewer_owns/)
    assert.match(code, /In Your Collection/)
  })

  test('a missing cover is a gradient, never a broken image', () => {
    // The default cover assets are installed as a separate launch
    // step, so this is the state the catalogue renders until then.
    const code = codeOnly(read(CARD))
    assert.match(code, /cover \?/)
    assert.match(code, /linear-gradient/)
  })
})

describe('Your Collection', () => {
  test('it is named "Your Collection" throughout', () => {
    for (const path of [COLLECTION, COLLECTION_CARD, ACQUIRE]) {
      const code = codeOnly(read(path))
      assert.ok(
        !/My Collection|My Library|Your Library/.test(code),
        `${path} uses a rejected name for Your Collection`,
      )
    }
    assert.match(codeOnly(read(COLLECTION)), /Your Collection/)
  })

  test('it does not touch or rename the Creator Library', () => {
    // Published World Builders instructions refer to the Creator
    // Library. Those instructions must stay accurate.
    for (const path of [COLLECTION, COLLECTION_CARD]) {
      assert.ok(
        !/Creator Library/.test(read(path).replace(/^\s*\*.*$/gm, '')),
        `${path} mentions the Creator Library in code`,
      )
    }
  })

  test('the empty state is an invitation with a route to discovery', () => {
    const code = codeOnly(read(COLLECTION))
    assert.match(code, /Your Collection starts here/)
    assert.match(code, /workbooks, guides, audio/)
    assert.match(code, /href="\/spaces"/)
  })

  test('it is one list, not split into Offerings and Files', () => {
    const code = codeOnly(read(COLLECTION))
    assert.ok(
      !/My Offerings|My Files/.test(code),
      'the Collection has been split, against the stated preference',
    )
  })

  test('a closed area 404s rather than rendering an empty collection', () => {
    // ``null`` means the Offerings feature is off; an empty ``items``
    // means a member who has acquired nothing. Different answers.
    const code = codeOnly(read(COLLECTION))
    assert.match(code, /collection === null/)
    assert.match(code, /notFound\(\)/)
  })

  test('it says ownership outlasts membership and retirement', () => {
    const code = codeOnly(read(COLLECTION))
    assert.match(code, /whether or not you/)
    assert.match(code, /remain a member/)
  })
})

describe('the Collection card', () => {
  test('a retired Offering is marked, not hidden', () => {
    const code = codeOnly(read(COLLECTION_CARD))
    assert.match(code, /offering_status === 'retired'/)
    assert.match(code, /No longer offered/)
  })

  test('unavailable files are explained, not left as a broken download', () => {
    const code = codeOnly(read(COLLECTION_CARD))
    assert.match(code, /files_available/)
    assert.match(code, /being updated/)
    assert.match(code, /stays yours/)
  })

  test('a missing Collective still renders the card', () => {
    // An archived Collective must not make a member's own collection
    // disappear.
    const code = codeOnly(read(COLLECTION_CARD))
    assert.match(code, /if \(!href\)/)
  })
})

describe('Your World links to Your Collection', () => {
  test('the band is present and routes to the page', () => {
    const code = codeOnly(read('app/dashboard/page.tsx'))
    assert.match(code, /Your Collection/)
    assert.match(code, /href="\/dashboard\/collection"/)
  })

  test('the band is absent when the feature is off', () => {
    // ``getYourCollection`` returns null when the area is closed.
    const code = codeOnly(read('app/dashboard/page.tsx'))
    assert.match(code, /collection !== null/)
  })

  test('Creator Studio and the Creator Library are untouched', () => {
    const code = read('app/dashboard/page.tsx')
    assert.match(code, /Creator Studio/)
    assert.ok(
      !/Creator Library/.test(code),
      'the dashboard now mentions the Creator Library',
    )
  })
})
