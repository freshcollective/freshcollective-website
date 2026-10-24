import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

/**
 * The form explains the destination rule in its own comments, so a raw
 * substring search would match the explanation and pass vacuously.
 * Every source assertion below runs against comment-stripped text — the
 * use is banned, not the word.
 */
const codeOnly = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const FORM = 'app/creator-studio/settings/WelcomeEmailForm.tsx'
const SHELL = 'app/creator-studio/settings/SettingsTabbedShell.tsx'

/**
 * What a creator may change about their welcome email.
 *
 * Five slots of voice and a switch. The button's destination is
 * generated from the Collective's slug server-side and is deliberately
 * not editable — a slot carries wording, never a link. These pin that
 * boundary in the UI, because a destination field added here would
 * quietly defeat the server's guarantee by giving a creator somewhere
 * to type one.
 */
describe('the Welcome Email form edits voice, not destinations', () => {

  test('it offers no field for the button destination', () => {
    const src = codeOnly(FORM)
    // The URL is rendered as text, never bound to an input.
    assert.ok(
      !/<input[^>]*collective_url/.test(src),
      'the destination must never be bound to an input',
    )
    assert.ok(
      !/<textarea[^>]*collective_url/.test(src),
      'the destination must never be bound to a textarea',
    )
  })

  test('it shows the destination read-only so it is visible', () => {
    const src = codeOnly(FORM)
    assert.match(
      src, /detail\.collective_url/,
      'a creator should be able to see where the button goes',
    )
  })

  test('it renders whatever slots the server declares', () => {
    // Not a hardcoded list: the declaration is the single source of
    // truth for which slots exist, and a UI that enumerated them
    // itself would drift the first time one was added.
    const src = codeOnly(FORM)
    assert.match(src, /detail\.slots\.map/)
  })

  test('it sends drafts to the real preview endpoint', () => {
    const src = codeOnly(FORM)
    assert.match(src, /welcome-email/)
    assert.match(src, /\/preview/)
    assert.match(src, /mode: 'effective'/)
  })

  test('restore default is offered only when customised', () => {
    const src = codeOnly(FORM)
    assert.match(
      src, /detail\.customised\s*&&/,
      'offering "restore default" on an uncustomised Collective would '
      + 'suggest a change that does not exist',
    )
  })

  test('the enable toggle is wired to the save payload', () => {
    const src = codeOnly(FORM)
    assert.match(src, /enabled,\s*overrides: drafts/)
  })
})

describe('the form is reachable, and only where it makes sense', () => {

  test('it is mounted in Collective Settings', () => {
    const src = codeOnly(SHELL)
    assert.match(src, /<WelcomeEmailForm\s+slug=/)
  })

  /**
   * WHICH tab, not merely "somewhere in the shell".
   *
   * The two tests around this one both passed while the release note
   * claimed the form lived under a tab that does not exist by that
   * name — they assert the form is mounted and guarded, and neither
   * can tell one tab from another. A creator looking in the wrong
   * place finds nothing and reasonably concludes the feature did not
   * ship, so the tab is part of the contract and is pinned here.
   *
   * Access & Visibility is the right home: the welcome is about the
   * moment somebody gets in, which is what that tab is for, and it
   * sits with the joining policy that decides who gets in at all.
   */
  test('it sits in the Access & Visibility tab, beside the joining policy', () => {
    const src = codeOnly(SHELL)
    const block = src.match(
      /\{tab === 'visibility'[\s\S]*?\n      \)\}/,
    )
    assert.ok(block, "no `tab === 'visibility'` block found in the shell")
    assert.ok(
      block[0].includes('<WelcomeEmailForm'),
      'the welcome form must render inside the Access & Visibility tab',
    )
    assert.ok(
      block[0].includes('<JoinPolicyForm'),
      'it belongs beside the joining policy, not alone on a tab',
    )
  })

  /**
   * The tab keys are internal; the labels are what a creator reads.
   * `members` is labelled "Collective Home" — naming either one after
   * the other in a report sends somebody hunting for a tab that is not
   * there, which is exactly what happened. This pins the pairing so
   * the mismatch is visible in the test output rather than discovered
   * in production.
   */
  test('the visibility tab is the one labelled Access & Visibility', () => {
    const src = codeOnly(SHELL)
    assert.match(
      src,
      /key: 'visibility',\s*label: 'Access & Visibility'/,
      "the 'visibility' key must still be the Access & Visibility tab",
    )
    assert.match(
      src,
      /key: 'members',\s*label: 'Collective Home'/,
      "the 'members' key is labelled Collective Home — it is NOT a Members tab",
    )
  })

  test('the welcome form is not on the Collective Home tab', () => {
    const src = codeOnly(SHELL)
    const home = src.match(/\{tab === 'members' &&[^\n]*/)
    assert.ok(home, "no `tab === 'members'` branch found")
    assert.ok(
      !home[0].includes('WelcomeEmailForm'),
      'the welcome form belongs with joining, not with Collective Home',
    )
  })

  test('auto-managed Collectives do not get one', () => {
    // Membership there is computed from platform eligibility rather
    // than chosen, so nobody joins and nobody is welcomed. The server
    // refuses too; this keeps the UI from offering a control that
    // would do nothing.
    const src = codeOnly(SHELL)
    assert.match(
      src,
      /!spaceDetail\.auto_grant_role\s*&&[\s\S]{0,600}?<WelcomeEmailForm/,
      'the welcome form must sit inside the auto_grant_role guard',
    )
  })
})


/**
 * The member's own control, in Stay Connected.
 *
 * Every other control on that page is per-Collective and writes
 * ``/api/spaces/{slug}/notification-settings``. This one cannot be:
 * it governs Collectives not yet joined. These pin that it reads the
 * communications matrix instead, and that it touches exactly one cell
 * of it.
 */
const PREF = 'app/settings/stay-connected/WelcomeEmailPreference.tsx'
const SHELL2 = 'app/settings/stay-connected/StayConnectedClient.tsx'

describe('the member can switch Collective welcome emails off', () => {

  test('it is mounted in Stay Connected', () => {
    const src = codeOnly(SHELL2)
    assert.match(src, /<WelcomeEmailPreference\s*\/>/)
  })

  test('it is shown even to somebody with no memberships', () => {
    // They are exactly who the setting is about — it governs the
    // Collectives they have not joined yet.
    const src = codeOnly(SHELL2)
    const empty = src.slice(
      src.indexOf('collectives.length === 0'),
      src.indexOf('return (\n    <div className="space-y-4">'),
    )
    assert.ok(
      empty.includes('<WelcomeEmailPreference'),
      'the empty state must still offer the welcome-email control',
    )
  })

  test('it reads and writes the communications matrix', () => {
    const src = codeOnly(PREF)
    assert.match(src, /\/api\/comms\/preferences\/me/)
    assert.match(src, /'PATCH'/)
  })

  test('it never writes the per-Collective notification endpoint', () => {
    // That endpoint is keyed by space slug; this setting has no space.
    const src = codeOnly(PREF)
    assert.ok(
      !src.includes('notification-settings'),
      'the welcome preference is not per-Collective',
    )
  })

  test('it touches exactly one category and one channel', () => {
    const src = codeOnly(PREF)
    assert.match(src, /CATEGORY = 'collective_welcome'/)
    assert.match(src, /CHANNEL = 'email_transactional'/)
    // Exactly one category is WRITTEN, and it is written through the
    // constant. A second one here, or an inline string, would make
    // this control silently govern unrelated email.
    const written = src.match(/category_key:\s*CATEGORY/g) ?? []
    assert.equal(written.length, 1)
    assert.ok(
      !/category_key:\s*'/.test(src),
      'the category must come from the constant, never an inline string',
    )
  })

  test('on and off are the only two priorities it sends', () => {
    const src = codeOnly(PREF)
    assert.match(src, /ON = 'immediate'/)
    assert.match(src, /OFF = 'silent'/)
    assert.ok(
      !/'daily_digest'|'weekly_digest'|'scheduled'/.test(src),
      'a digest priority here would promise a cadence nothing delivers',
    )
  })

  test('it hides itself rather than guessing when the read fails', () => {
    // Showing "off" because a request failed is a lie a member might
    // act on; the server holds the truth.
    const src = codeOnly(PREF)
    assert.match(src, /setPresent\(false\)/)
    assert.match(src, /if \(!present\) return null/)
  })
})
