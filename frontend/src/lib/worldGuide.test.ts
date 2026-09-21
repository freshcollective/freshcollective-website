import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import {
  WG_DOC, WG_SECTIONS, groupIntoSections, wgHref,
  type PublicDocumentCard,
} from './worldGuide.ts'

/**
 * Publishing the governance set.
 *
 * The documents themselves live in World Management and are already
 * published; nothing here duplicates their content. What these cover
 * is how they are grouped, linked, and kept away from draft or admin
 * routes.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

function card(slug: string, title: string, category = 'governance'): PublicDocumentCard {
  return {
    slug, title, category, audience: 'everyone', summary: null,
    version_number: '1.0', reading_time_minutes: 10, effective_date: null,
  } as unknown as PublicDocumentCard
}

/** The nine live documents, as production serves them. */
const LIVE = [
  card('creator-agreement', 'Creator Agreement', 'creators'),
  card('community-guidelines', 'Community Guidelines'),
  card('glossary', 'Glossary'),
  card('our-philosophy', 'Our Philosophy'),
  card('payment-refund-and-cancellation-policy', 'Payment, Refund and Cancellation Policy'),
  card('privacy-policy', 'Privacy Policy'),
  card('term-of-use', 'Terms of Use'),
  card('world-guide', 'World Guide'),
  card('membership-terms', 'Membership Terms', 'members'),
]

describe('the directory groups by what a reader is doing', () => {
  test('the four intended sections, in order', () => {
    assert.deepEqual(
      groupIntoSections(LIVE).map((s) => s.label),
      ['How Fresh Collective works', 'Using Fresh Collective', 'Members', 'Creators'],
    )
  })

  test('each section holds the documents it should', () => {
    const by = Object.fromEntries(
      groupIntoSections(LIVE).map((s) => [s.key, s.items.map((i) => i.slug)]),
    )
    assert.deepEqual(by['how-it-works'], ['glossary', 'our-philosophy'])
    assert.deepEqual(by['using'], [
      'term-of-use', 'privacy-policy', 'community-guidelines',
      'payment-refund-and-cancellation-policy',
    ])
    assert.deepEqual(by['members'], ['membership-terms'])
    assert.deepEqual(by['creators'], ['creator-agreement'])
  })

  test('the World Guide does not link to itself', () => {
    // The reader is standing on it.
    const slugs = groupIntoSections(LIVE).flatMap((s) => s.items.map((i) => i.slug))
    assert.ok(!slugs.includes('world-guide'))
    assert.equal(slugs.length, 8, 'the other eight all appear')
  })

  test('a document nobody has mapped still lands somewhere', () => {
    const sections = groupIntoSections([...LIVE, card('new-thing', 'New Thing', 'members')])
    const members = sections.find((s) => s.key === 'members')!
    assert.deepEqual(members.items.map((i) => i.slug), ['membership-terms', 'new-thing'])
  })

  test('an empty section is not rendered', () => {
    const sections = groupIntoSections([card('glossary', 'Glossary')])
    assert.deepEqual(sections.map((s) => s.key), ['how-it-works'])
  })

  test('nothing at all renders nothing', () => {
    assert.deepEqual(groupIntoSections([]), [])
  })

  test('the page renders from this function and not from category', () => {
    const page = read('app/world-guide/page.tsx')
    assert.match(page, /groupIntoSections\(cards\)/)
    assert.ok(!page.includes("'governance'"), 'no hard-coded category order left')
  })
})

describe('canonical routes', () => {
  test('every link is built by wgHref', () => {
    assert.equal(wgHref(WG_DOC.TERMS_OF_USE), '/world-guide/term-of-use')
    assert.equal(wgHref(WG_DOC.PAYMENT_POLICY),
      '/world-guide/payment-refund-and-cancellation-policy')
  })

  test('no surface points at an admin or draft route', () => {
    // A governance link that reached /admin/world-guide would be both
    // broken and a disclosure.
    for (const f of [
      'components/layout/PublicFooter.tsx',
      'app/signup/SignupForm.tsx',
      'app/spaces/[slug]/about/JoiningDoors.tsx',
      'components/checkout/PaymentPlanConfirmDialog.tsx',
      'app/creator-onboarding/page.tsx',
      'components/community/CreatePostForm.tsx',
      'components/settings/SettingsNav.tsx',
    ]) {
      assert.ok(!read(f).includes('/admin/world-guide'), f)
      // Scoped to world-guide links: an unanchored /preview/ matches
      // an image preview and says nothing about governance routes.
      const wgLinks = read(f).match(/\/world-guide\/[^"'`\s)]*/g) ?? []
      for (const link of wgLinks) {
        assert.ok(!link.includes('?'), `${f}: query on ${link}`)
        assert.ok(!link.includes('preview'), `${f}: draft preview route ${link}`)
      }
    }
  })

  test('no governance link hard-codes a hostname', () => {
    const footer = read('components/layout/PublicFooter.tsx')
    assert.ok(!footer.includes('onrender.com'))
    assert.ok(!footer.includes('https://'))
  })
})

describe('the footer carries four, not nine', () => {
  const footer = () => read('components/layout/PublicFooter.tsx')

  test('the four a person reaches for', () => {
    const src = footer()
    for (const label of ['World Guide', 'Terms of Use', 'Privacy Policy', 'Payments & Refunds']) {
      assert.ok(src.includes(label), label)
    }
  })

  test('and not the other five', () => {
    const src = footer()
    for (const label of ['Glossary', 'Our Philosophy', 'Community Guidelines',
                         'Membership Terms', 'Creator Agreement']) {
      assert.ok(!src.includes(label), `${label} should live on the World Guide, not the footer`)
    }
  })

  test('Payments & Refunds points at the full policy', () => {
    assert.match(footer(), /wgHref\(WG_DOC\.PAYMENT_POLICY\)/)
  })

  test('one footer, shared by every public shell', () => {
    // Not two implementations drifting apart.
    assert.match(read('components/layout/SiteShell.tsx'), /<PublicFooter \/>/)
  })
})

describe('governance appears where it is relevant', () => {
  const cases: [string, string, string[]][] = [
    ['signup', 'app/signup/SignupForm.tsx', ['TERMS_OF_USE', 'PRIVACY_POLICY']],
    ['joining a Collective', 'app/spaces/[slug]/about/JoiningDoors.tsx',
      ['MEMBERSHIP_TERMS', 'PAYMENT_POLICY']],
    ['checkout confirmation', 'components/checkout/PaymentPlanConfirmDialog.tsx',
      ['PAYMENT_POLICY', 'TERMS_OF_USE']],
    ['creator onboarding', 'app/creator-onboarding/page.tsx',
      ['CREATOR_AGREEMENT', 'TERMS_OF_USE']],
    ['posting a conversation', 'components/community/CreatePostForm.tsx',
      ['COMMUNITY_GUIDELINES']],
  ]

  for (const [surface, file, docs] of cases) {
    test(`${surface} links to ${docs.join(' + ')}`, () => {
      const src = read(file)
      for (const doc of docs) {
        assert.match(src, new RegExp(`wgHref\\(WG_DOC\\.${doc}\\)`), doc)
      }
    })
  }

  test('the join surface shows them before the account, not after', () => {
    // Someone weighing a purchase should not have to sign up to find
    // out what it commits them to.
    const src = read('app/spaces/[slug]/about/JoiningDoors.tsx')
    const signedOut = src.slice(src.indexOf('if (!isLoggedIn)'), src.indexOf('return (\n    <div className="flex flex-col gap-4">'))
    assert.match(signedOut, /wgHref\(WG_DOC\.MEMBERSHIP_TERMS\)/)
    assert.match(signedOut, /wgHref\(WG_DOC\.PAYMENT_POLICY\)/)
  })

  test('settings offers a route to the World Guide', () => {
    assert.match(read('components/settings/SettingsNav.tsx'), /href: '\/world-guide'/)
  })

  test('signup states the age requirement', () => {
    // Smallest sensible wording — no DOB, no verification.
    assert.match(read('app/signup/SignupForm.tsx'), /18 or over/)
  })

  test('signup adds no new required checkbox', () => {
    // There was no consent pattern to extend; inventing a ceremony
    // would be worse than the plain sentence.
    const src = read('app/signup/SignupForm.tsx')
    assert.ok(!/type="checkbox"/.test(src))
  })

  test('community guidelines appear at the composer, not on every page', () => {
    assert.ok(!read('app/spaces/[slug]/community/page.tsx').includes('COMMUNITY_GUIDELINES'))
  })
})
