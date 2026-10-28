import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

/**
 * "Create your free account, then find Collectives to join."
 *
 * The header's **Join** button is the reason this line exists. It
 * reads as an invitation to join something in particular, and the
 * signup page is where that has to be settled: an account, free, and
 * not the same thing as joining a Collective.
 *
 * The line is conditional, and that is the part worth protecting. A
 * visitor who arrived from a Pathway or Gathering checkout link is
 * already being told what they are creating an account for, and
 * telling them to go and find a Collective would contradict the
 * screen they are looking at — they arrived through one. So the
 * sentence belongs to the plain-signup branch only.
 *
 * Source is comment-stripped before matching, so the explanation
 * above a line cannot be mistaken for the line itself.
 */

const codeOnly = (src: string) =>
  src
    .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const FORM = codeOnly(readFileSync('src/app/signup/SignupForm.tsx', 'utf8'))
const SENTENCE = 'Create your free account, then find Collectives to join.'

/** The two halves of the heading block: with checkout context, without. */
const CHECKOUT_BRANCH = FORM.slice(
  FORM.indexOf('{checkoutContext ? ('),
  FORM.indexOf(') : ('),
)
const PLAIN_BRANCH = FORM.slice(
  FORM.indexOf(') : ('),
  FORM.indexOf('</div>', FORM.indexOf(') : (')),
)


describe('the signup page says what Join joins', () => {
  test('the sentence is on the page, worded as approved', () => {
    assert.ok(FORM.includes(SENTENCE), 'the clarifying sentence is gone')
  })

  test('it appears once', () => {
    assert.equal(FORM.split(SENTENCE).length - 1, 1)
  })

  test('it sits under the heading and above the form', () => {
    const heading = PLAIN_BRANCH.indexOf('Create your account')
    const sentence = PLAIN_BRANCH.indexOf(SENTENCE)
    assert.ok(heading >= 0 && sentence > heading, 'it is not beneath the heading')
    assert.ok(
      FORM.indexOf(SENTENCE) < FORM.indexOf('<form'),
      'it has drifted below the registration form',
    )
  })

  test('the existing welcome line was kept, not replaced', () => {
    assert.ok(PLAIN_BRANCH.includes('Your world begins here.'))
  })

  test('it says the account is free, and that joining is a separate step', () => {
    assert.match(SENTENCE, /free account/)
    assert.match(SENTENCE, /then find Collectives to join/)
  })
})


describe('a visitor who arrived through a Collective is left alone', () => {
  test('the sentence is not shown in the checkout-context branch', () => {
    assert.ok(
      !CHECKOUT_BRANCH.includes(SENTENCE),
      'the line contradicts a visitor who already arrived through a Collective',
    )
  })

  test('that branch keeps its own explanation of what the account is for', () => {
    assert.ok(CHECKOUT_BRANCH.includes('buildSignupSubcopy(checkoutContext)'))
    assert.ok(FORM.includes('Create a free account to continue with'))
  })

  test('both checkout headings survive', () => {
    assert.ok(CHECKOUT_BRANCH.includes('Create an account to continue to ticket checkout'))
    assert.ok(CHECKOUT_BRANCH.includes('Create your account to continue'))
  })
})


describe('nothing about signing up changed', () => {
  test('the form still posts through the same handler', () => {
    assert.ok(/onSubmit=\{/.test(FORM))
    assert.ok(FORM.includes('<form'))
  })

  test('the next-URL is still carried through to login', () => {
    assert.ok(
      FORM.includes('`/login?next=${encodeURIComponent(nextUrl)}`'),
      'a visitor sent here from somewhere would lose their destination',
    )
  })

  test('the signup page still resolves its checkout context', () => {
    const page = codeOnly(readFileSync('src/app/signup/page.tsx', 'utf8'))
    assert.ok(page.includes('getCheckoutContext(next)'))
    assert.ok(page.includes("redirect(next && next.startsWith('/') ? next : '/dashboard')"))
  })

  test('the header still offers Join, pointing at signup', () => {
    // The desktop header says "Join"; the mobile drawer has room for
    // "Join Fresh Collective" and already says so, which is the
    // ambiguity this sentence exists to settle on the page itself.
    for (const [file, label] of [
      ['src/components/layout/PublicHeader.tsx', 'Join'],
      ['src/components/layout/MobileNav.tsx', 'Join Fresh Collective'],
    ] as const) {
      const src = readFileSync(file, 'utf8')
      assert.ok(src.includes('href="/signup"'), `${file} no longer links to signup`)
      assert.ok(src.includes(label), `${file} no longer says "${label}"`)
    }
  })
})
