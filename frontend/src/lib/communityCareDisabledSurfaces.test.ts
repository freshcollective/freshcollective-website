import { strict as assert } from 'node:assert'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

/**
 * What a member sees while Community Care is disabled.
 *
 * Two things had to change. A conversation offered "Report Maya",
 * which posted to an endpoint that refused — so somebody trying to
 * report harassment discovered the feature was off by filling in a
 * form and submitting it. And when any report was refused, the modal
 * rendered the API's own `detail` straight into the error slot, so a
 * member read *"Community Care is not yet enabled on this
 * deployment."* — a sentence about our infrastructure, shown to
 * someone asking for help.
 *
 * Asserted against source: these are React components and the harness
 * is node:test with no DOM. Comment-stripped for absence checks,
 * because the new comments quote the string being removed.
 */

const SRC = join(process.cwd(), 'src')
const THREAD = join(SRC, 'app', 'messages', '[threadId]', 'PeerConversationClient.tsx')
const REPORT_MODAL = join(SRC, 'components', 'community', 'ReportModal.tsx')
const SUPPORT_FORM = join(SRC, 'app', 'creator', 'support', 'CreatorSupportForm.tsx')
const TYPES = join(SRC, 'lib', 'peerMessages.ts')

const read = (p: string) => readFileSync(p, 'utf8')

/** Source with comments removed, so an absence check reads the code. */
function code(p: string): string {
  return read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/^\s*\/\/.*$/gm, '')
}

const SUPPORT_EMAIL = 'support@freshcollective.au'

// ---------------------------------------------------------------------------

describe('the conversation asks the backend whether reporting is open', () => {
  it('the thread type carries the answer', () => {
    assert.match(read(TYPES), /can_report: boolean/)
  })

  it('and the menu branches on it rather than on a frontend flag', () => {
    // A mirrored env var would be a second source of truth that can
    // lag the real one — which is exactly how a member gets offered a
    // door that is shut.
    const src = code(THREAD)
    assert.match(src, /thread\.can_report/)
    assert.ok(
      !/COMMUNITY_CARE_ENABLED/i.test(src),
      'the client re-derives the flag instead of asking',
    )
  })

  it('Report is offered only when reporting is open', () => {
    const src = code(THREAD)
    const i = src.indexOf('thread.can_report')
    assert.ok(i > 0)
    const branch = src.slice(i, i + 700)
    assert.match(branch, /label: `Report \$\{firstName\}`/)
    assert.match(branch, /Contact Fresh Collective/)
  })

  it('and the alternative names the support address', () => {
    assert.ok(read(THREAD).includes(SUPPORT_EMAIL))
  })

  it('the alternative is not a second reporting system', () => {
    // No form, no category list, no case number — just the address.
    const src = code(THREAD)
    const i = src.indexOf('contacting && (')
    assert.ok(i > 0, 'no contact panel')
    // Bounded at the next panel, not by a character count — the
    // reporting form follows immediately and a generous slice would
    // read it as part of this one.
    const end = src.indexOf('{reporting && (', i)
    assert.ok(end > i, 'could not find the end of the contact panel')
    const panel = src.slice(i, end)
    assert.ok(!/<form/.test(panel), 'the alternative renders a form')
    assert.ok(!/<select/.test(panel), 'the alternative renders a category picker')
    assert.ok(!/case_number/.test(panel), 'the alternative invents a case number')
    assert.ok(!/fetch\(/.test(panel), 'the alternative calls an endpoint')
  })

  it('and it tells the member what does work', () => {
    const src = read(THREAD)
    const i = src.indexOf('contacting && (')
    const end = src.indexOf('{reporting && (', i)
    assert.match(src.slice(i, end), /block/i)
  })
})

describe('blocking is untouched', () => {
  it('Block is still offered, and not conditional on reporting', () => {
    const src = code(THREAD)
    assert.match(src, /label: `Block \$\{firstName\}`/)
    // The Block item must not sit inside the can_report branch.
    const blockAt = src.indexOf('label: `Block ${firstName}`')
    const reportBranchAt = src.indexOf('thread.can_report')
    assert.ok(
      blockAt < reportBranchAt,
      'Block was moved inside the reporting branch',
    )
  })

  it('and the block confirmation flow is intact', () => {
    const src = code(THREAD)
    assert.match(src, /setConfirmBlock\(true\)/)
    assert.match(src, /confirmBlock && \(/)
  })
})

describe('no member is shown our deployment state', () => {
  for (const [name, path] of [
    ['the Conversations report modal', REPORT_MODAL],
    ['the creator support form', SUPPORT_FORM],
  ] as const) {
    it(`${name} handles 503 with its own copy`, () => {
      const src = code(path)
      const i = src.indexOf('res.status === 503')
      assert.ok(i > 0, `${name} does not special-case 503`)
      // Bounded at the generic fallback below it, for the same reason
      // as the panel above: a fixed window would swallow the branch
      // this one exists to pre-empt.
      const end = src.indexOf('body.detail', i)
      assert.ok(end > i, `${name}: could not bound the 503 branch`)
      const branch = src.slice(i, end)
      assert.ok(
        branch.includes(SUPPORT_EMAIL),
        `${name} does not offer the support address`,
      )
      // The raw detail must not be the 503 path's message.
      assert.ok(
        !/extractErrorMessage/.test(branch),
        `${name} still renders the API detail on a 503`,
      )
    })

    it(`${name} checks 503 before falling back to the detail`, () => {
      // Order matters: the generic `body.detail` branch below would
      // otherwise win and print the deployment sentence.
      const src = code(path)
      const at503 = src.indexOf('res.status === 503')
      const atDetail = src.indexOf('body.detail')
      assert.ok(at503 > 0 && atDetail > 0)
      assert.ok(at503 < atDetail, `${name}: the 503 branch is unreachable`)
    })

    it(`${name} keeps its other error handling`, () => {
      const src = code(path)
      assert.match(src, /res\.status === 429/)
      assert.match(src, /body\.detail/)
    })
  }

  it('and the deployment sentence appears nowhere in member copy', () => {
    for (const path of [THREAD, REPORT_MODAL, SUPPORT_FORM]) {
      const rendered = code(path)
      assert.ok(
        !rendered.includes('not yet enabled on this deployment'),
        `${path} renders the deployment sentence`,
      )
    }
  })
})
