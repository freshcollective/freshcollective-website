import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { PUBLIC_JOIN_LABEL } from './publicNav.ts'

/**
 * "Join Fresh Collective", in every navigation surface.
 *
 * Three places offer signup from navigation — the desktop header in
 * two variants, the mobile drawer and the footer — and for a while
 * they disagreed: the drawer said the whole thing, the other two said
 * "Join". That is the drift this file exists to prevent, so the
 * assertions are about *sharing the constant*, not about each file
 * happening to contain the right string today.
 *
 * The contextual signup links inside a purchase or an invitation are
 * deliberately excluded and asserted to stay that way.
 */

const read = (p: string) => readFileSync(p, 'utf8')

const codeOnly = (src: string) =>
  src
    .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const HEADER = 'src/components/layout/PublicHeader.tsx'
const MOBILE = 'src/components/layout/MobileNav.tsx'
const FOOTER = 'src/components/layout/PublicFooter.tsx'
const NAV_SURFACES = [HEADER, MOBILE, FOOTER]


describe('the label itself', () => {
  test('it is the approved wording', () => {
    assert.equal(PUBLIC_JOIN_LABEL, 'Join Fresh Collective')
  })
})


describe('every navigation surface shares it', () => {
  for (const file of NAV_SURFACES) {
    test(`${file.split('/').pop()} imports the constant`, () => {
      const src = codeOnly(read(file))
      assert.match(src, /import \{ PUBLIC_JOIN_LABEL \} from '@\/lib\/publicNav'/)
      assert.ok(src.includes('PUBLIC_JOIN_LABEL'), 'imported but never used')
    })

    test(`${file.split('/').pop()} spells no label of its own`, () => {
      const src = codeOnly(read(file))
      assert.ok(
        !/'Join Fresh Collective'|>\s*Join Fresh Collective\s*</.test(src),
        'the wording is duplicated here and can now drift',
      )
      assert.ok(
        !/>\s*Join\s*<|label: 'Join'/.test(src),
        'a bare "Join" survived',
      )
    })
  }

  test('the desktop header uses it in both variants', () => {
    // One for the dark overlay header, one for the light one.
    assert.equal(codeOnly(read(HEADER)).split('{PUBLIC_JOIN_LABEL}').length - 1, 2)
  })

  test('every one of them still points at signup', () => {
    for (const file of NAV_SURFACES) {
      assert.match(codeOnly(read(file)), /\/signup/)
    }
  })
})


describe('the button is otherwise untouched', () => {
  const header = codeOnly(read(HEADER))

  test('the dark variant keeps its glass styling', () => {
    assert.match(header, /background: 'rgba\(255,255,255,0\.10\)'/)
    assert.match(header, /backdropFilter: 'blur\(8px\)'/)
  })

  test('the light variant keeps its teal gradient', () => {
    assert.match(header, /linear-gradient\(135deg, #38A09E 0%, #55B8B6 100%\)/)
    assert.match(header, /boxShadow: '0 2px 12px rgba\(56,160,158,0\.30\)'/)
  })

  test('both keep the same shape and weight', () => {
    assert.equal(
      header.split('rounded-xl px-5 py-2 text-[13px] font-semibold text-white').length - 1,
      2,
    )
  })

  test('neither button can wrap', () => {
    assert.equal(header.split('whitespace-nowrap rounded-xl px-5').length - 1, 2)
  })

  test('the header row is given back the width the longer label needs', () => {
    // Measured: with the two centre nav items production ships, the
    // one-line header needs 773px at the old 32px row gap — five
    // pixels more than the 768px breakpoint has, so the nav items
    // wrapped onto two lines. A 24px gap in that band brings the
    // requirement to 757px, an 11px surplus. Restored to 32px from
    // lg up, where there was never a shortage.
    assert.equal(header.split('items-center justify-between gap-6 lg:gap-8').length - 1, 2)
    assert.ok(
      !/items-center justify-between gap-8"/.test(header),
      'a header row went back to a flat gap-8 and will wrap at 768px',
    )
  })

  test('the mobile drawer button is unchanged', () => {
    assert.match(codeOnly(read(MOBILE)), /linear-gradient\(135deg, #38A09E 0%, #55B8B6 100%\)/)
  })
})


describe('authenticated navigation is untouched', () => {
  const header = codeOnly(read(HEADER))

  test('signed-in visitors still get Your World and a logout', () => {
    assert.ok(header.includes('Your World'))
    assert.ok(header.includes('<LogoutButton'))
  })

  test('the signup button is still only offered when signed out', () => {
    // It lives in the `user ? … : …` else-branch; if it escaped that,
    // a signed-in visitor would be invited to join again.
    const elseBranch = header.slice(header.indexOf('{user ? ('))
    assert.ok(elseBranch.includes('PUBLIC_JOIN_LABEL'))
    const firstUse = header.indexOf('PUBLIC_JOIN_LABEL', header.indexOf('{user ? ('))
    const firstLogin = header.indexOf('href="/login"', header.indexOf('{user ? ('))
    assert.ok(firstLogin > 0 && firstLogin < firstUse, 'the signed-out cluster changed shape')
  })
})


describe('contextual signup links are deliberately left alone', () => {
  const CONTEXTUAL: [string, string][] = [
    ['src/components/offerings/AcquireOffering.tsx', 'Create account to continue'],
    ['src/components/checkout/PaymentOptionSelector.tsx', 'Create account to continue'],
    ['src/components/checkout/CheckoutButton.tsx', 'Create account to continue'],
    ['src/app/invites/[token]/InviteAcceptClient.tsx', 'Create an account'],
  ]

  for (const [file, label] of CONTEXTUAL) {
    test(`${file.split('/').pop()} still says "${label}"`, () => {
      // A visitor here has already found a Collective. Telling them to
      // join Fresh Collective would describe the wrong step.
      const src = read(file)
      assert.ok(src.includes(label), `${file} lost its contextual wording`)
      assert.ok(!src.includes('PUBLIC_JOIN_LABEL'), `${file} took the navigation label`)
    })
  }
})
