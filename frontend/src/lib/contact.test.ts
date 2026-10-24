import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

import { CONTACT_INFO_EMAIL, CONTACT_SUPPORT_EMAIL } from './contact.ts'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')
const codeOnly = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const FOOTER = 'components/layout/PublicFooter.tsx'
const SECURITY = 'app/settings/security/page.tsx'
const CHECKOUT = 'components/checkout/CompleteFlow.tsx'

describe('the addresses themselves', () => {
  test('they are the three working mailboxes, spelled once', () => {
    assert.equal(CONTACT_INFO_EMAIL, 'info@freshcollective.au')
    assert.equal(CONTACT_SUPPORT_EMAIL, 'support@freshcollective.au')
  })

  test('no surface spells an address inline', () => {
    // A typo in one of four places would be invisible until somebody's
    // email bounced, so every surface goes through the constant.
    for (const f of [FOOTER, SECURITY, CHECKOUT]) {
      assert.ok(
        !/@freshcollective\.au/.test(codeOnly(f)),
        `${f} hardcodes an address instead of importing the constant`,
      )
    }
  })
})

describe('the public footer', () => {
  test('it offers a Contact link', () => {
    const src = codeOnly(FOOTER)
    assert.match(src, /mailto:\$\{CONTACT_INFO_EMAIL\}/)
    assert.match(src, />\s*Contact\s*</)
  })

  test('it uses info@, not support@ or hello@', () => {
    // A footer catches enquiries from people who are not yet members.
    const src = codeOnly(FOOTER)
    assert.match(src, /CONTACT_INFO_EMAIL/)
    assert.ok(!/CONTACT_SUPPORT_EMAIL/.test(src))
    assert.ok(!/hello@/.test(src))
  })

  test('the existing navigation is intact', () => {
    const src = codeOnly(FOOTER)
    for (const label of ['Explore Collectives', 'Log in', 'Join']) {
      assert.ok(src.includes(label), `${label} is missing from the footer`)
    }
  })

  test('the Contact link sits in the main nav, not the governance one', () => {
    const src = codeOnly(FOOTER)
    const mainNav = src.indexOf('aria-label="Footer"')
    const govNav = src.indexOf('aria-label="Governance and help"')
    const contact = src.indexOf('CONTACT_INFO_EMAIL', mainNav)
    assert.ok(mainNav > -1 && govNav > mainNav, 'nav order changed')
    assert.ok(
      contact > mainNav && contact < govNav,
      'the Contact link must be in the main nav',
    )
  })

  test('it is an anchor, not a next/link route', () => {
    // A mailto is not a route; next/link has nothing to prefetch.
    const src = codeOnly(FOOTER)
    assert.ok(!/<Link[^>]*mailto/.test(src))
  })
})

describe('account security', () => {
  test('the email-change instruction is now actionable', () => {
    const src = codeOnly(SECURITY)
    assert.match(src, /To change your email, contact/)
    assert.match(src, /mailto:\$\{CONTACT_SUPPORT_EMAIL\}/)
  })

  test('it uses support@, because an email change is an account matter', () => {
    const src = codeOnly(SECURITY)
    assert.ok(!/CONTACT_INFO_EMAIL/.test(src))
  })
})

describe('checkout errors', () => {
  test('the shared error card carries the support address', () => {
    const src = codeOnly(CHECKOUT)
    assert.match(src, /mailto:\$\{CONTACT_SUPPORT_EMAIL\}/)
  })

  test('resolveFlow stays a pure function returning plain strings', () => {
    // The address is rendered by ErrorCard, not embedded in the
    // messages — putting markup in the resolver would make it harder
    // to test and change nothing for the reader.
    const src = codeOnly(CHECKOUT)
    const start = src.indexOf('export function resolveFlow')
    assert.ok(start > -1, 'resolveFlow not found')
    // Bounded by the next top-level declaration, not by
    // ``export default`` — that appears EARLIER in this file, which
    // made the first version of this test slice nothing and pass
    // vacuously in the other direction.
    const after = src.slice(start + 1)
    const nextDecl = after.search(/\n(export |function )/)
    const resolver = nextDecl > -1 ? after.slice(0, nextDecl) : after
    assert.ok(resolver.includes('claim link has expired'),
      'the slice did not capture resolveFlow')
    assert.ok(
      !/mailto|CONTACT_SUPPORT_EMAIL|<a /.test(resolver),
      'resolveFlow must not build markup',
    )
  })

  test('both stuck-purchase messages are unchanged', () => {
    // These are what a paying customer reads. The change adds an
    // address beneath them; it does not reword them.
    const src = read(CHECKOUT)
    assert.ok(src.includes(
      'This purchase has already been claimed on another account.',
    ))
    assert.ok(src.includes(
      'This claim link has expired. Please contact support to have it re-issued.',
    ))
  })

  test('the address is rendered once, on the shared card', () => {
    const src = codeOnly(CHECKOUT)
    const hits = src.match(/mailto:\$\{CONTACT_SUPPORT_EMAIL\}/g) ?? []
    assert.equal(hits.length, 1, 'one support line serves every error flow')
  })
})

describe('what must not have changed', () => {
  test('the creator support form still posts to its endpoint', () => {
    assert.match(
      codeOnly('app/creator/support/CreatorSupportForm.tsx'),
      /community-care\/creator-support/,
    )
  })

  test('the Organisation enquiry still routes to the waitlist', () => {
    assert.match(codeOnly('app/for-creators/page.tsx'), /ecosystem-interest/)
  })

  test('creator-to-member messaging is untouched', () => {
    // "Message Lindsey" is a member reaching THEIR creator, not
    // platform support. Replacing it with an address would be a
    // regression, not an improvement.
    const pathway = read('app/spaces/[slug]/pathways/[pathway-slug]/page.tsx')
    assert.ok(pathway.includes('Message Lindsey'))
    assert.ok(!/@freshcollective\.au/.test(pathway))
  })

  test('no address leaked into a transactional email template', () => {
    // Sender and Reply-To are deliberately out of scope.
    const events = read('app/spaces/[slug]/events/page.tsx')
    assert.ok(!/@freshcollective\.au/.test(events))
  })
})
