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
const CONTACT_SECTION = 'components/layout/FooterContact.tsx'

describe('the addresses themselves', () => {
  test('they are the three working mailboxes, spelled once', () => {
    assert.equal(CONTACT_INFO_EMAIL, 'info@freshcollective.au')
    assert.equal(CONTACT_SUPPORT_EMAIL, 'support@freshcollective.au')
  })

  test('no surface spells an address inline', () => {
    // A typo in one of four places would be invisible until somebody's
    // email bounced, so every surface goes through the constant.
    for (const f of [FOOTER, SECURITY, CHECKOUT, CONTACT_SECTION]) {
      assert.ok(
        !/@freshcollective\.au/.test(codeOnly(f)),
        `${f} hardcodes an address instead of importing the constant`,
      )
    }
  })
})

describe('the public footer offers both addresses, not a mailto', () => {
  // This block used to assert a single ``mailto:info@…`` Contact link
  // in the nav. That link was replaced: a mailto hands the visitor to
  // an email application, and on a machine with none configured it
  // produces a dialog about choosing a program rather than an answer
  // to "how do I contact you". The assertions follow the new design
  // rather than being deleted.

  test('the redundant Contact nav link is gone', () => {
    const src = codeOnly(FOOTER)
    assert.ok(!/mailto:/.test(src), 'the footer still contains a mailto')
    assert.ok(!/>\s*Contact\s*</.test(src), 'the Contact nav link survived')
  })

  test('the Get in touch section is mounted in the footer', () => {
    assert.match(codeOnly(FOOTER), /<FooterContact \/>/)
  })

  test('the existing navigation is intact', () => {
    const src = codeOnly(FOOTER)
    for (const label of ['Explore Collectives', 'Log in']) {
      assert.ok(src.includes(label), `${label} is missing from the footer`)
    }
    // The signup entry is no longer a literal here: its wording is
    // shared with the two headers so the three cannot drift apart.
    // See ``publicNavLabel.test.ts``.
    assert.ok(src.includes('PUBLIC_JOIN_LABEL'), 'the signup entry is missing from the footer')
  })

  test('the governance nav is untouched', () => {
    assert.match(codeOnly(FOOTER), /aria-label="Governance and help"/)
  })
})

describe('the Get in touch section', () => {
  test('it is a client component — the clipboard is a browser API', () => {
    assert.match(read(CONTACT_SECTION), /^'use client'/m)
  })

  test('it shows both addresses, each from the shared constant', () => {
    const src = codeOnly(CONTACT_SECTION)
    assert.match(src, /CONTACT_INFO_EMAIL/)
    assert.match(src, /CONTACT_SUPPORT_EMAIL/)
    assert.ok(
      !/@freshcollective\.au/.test(src),
      'an address is spelled inline instead of imported',
    )
  })

  test('both are clearly labelled', () => {
    const src = read(CONTACT_SECTION)
    assert.match(src, /General enquiries/)
    assert.match(src, /Technical & account support/)
  })

  test('nothing navigates — no mailto, no href, no redirect', () => {
    // The whole point of replacing the link. A stray href here would
    // reintroduce exactly what was removed.
    const src = codeOnly(CONTACT_SECTION)
    assert.ok(!/mailto:/.test(src), 'a mailto came back')
    assert.ok(!/href=/.test(src), 'something in the section navigates')
    assert.ok(!/router\.|redirect\(/.test(src), 'the section redirects')
  })

  test('copying uses the clipboard and confirms it', () => {
    const src = codeOnly(CONTACT_SECTION)
    assert.match(src, /navigator\.clipboard/)
    assert.match(src, /writeText\(email\)/)
    assert.match(src, /'Copied!'/)
  })

  test('a clipboard that is unavailable does not claim success', () => {
    // writeText needs a secure context and permission. Where it is
    // missing, the honest answer is "select it yourself" — not a
    // confirmation of something that did not happen.
    const src = codeOnly(CONTACT_SECTION)
    assert.match(src, /writeText\) throw new Error/)
    assert.match(src, /'Select to copy'/)
  })

  test('each button names which address it copies', () => {
    // Two buttons both reading "Copy" are indistinguishable to a
    // screen reader.
    assert.match(
      codeOnly(CONTACT_SECTION),
      /aria-label=\{`Copy \$\{email\} to the clipboard`\}/,
    )
  })

  test('the outcome is announced, not only shown', () => {
    const src = codeOnly(CONTACT_SECTION)
    assert.match(src, /aria-live="polite"/)
    assert.match(src, /copied to the clipboard/)
  })

  test('the confirmation clears itself', () => {
    // A "Copied!" that never resets looks like the button broke.
    assert.match(codeOnly(CONTACT_SECTION), /setTimeout\(/)
    assert.match(codeOnly(CONTACT_SECTION), /'idle'/)
  })

  test('each address keeps its own state', () => {
    // Copying one must not clear the other's confirmation.
    const src = codeOnly(CONTACT_SECTION)
    assert.match(src, /Record<string, Status>/)
    assert.match(src, /\[email\]:/)
  })

  test('the addresses stay readable and hand-selectable', () => {
    // The button is the convenience, not the only route: somebody who
    // prefers to select the text must be able to, and an address
    // truncated with an ellipsis can be neither read nor copied.
    const src = codeOnly(CONTACT_SECTION)
    assert.match(src, /select-all/)
    assert.match(src, /break-all/)
    assert.ok(!/truncate/.test(src), 'the address is truncated')
  })

  test('it uses the footer palette rather than its own', () => {
    const src = read(CONTACT_SECTION)
    assert.match(src, /#FFFFFF/)
    assert.match(src, /rgba\(255,255,255/)
  })

  test('it wraps on a narrow screen instead of overflowing', () => {
    assert.match(codeOnly(CONTACT_SECTION), /flex-wrap/)
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
