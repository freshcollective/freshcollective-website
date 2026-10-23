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
