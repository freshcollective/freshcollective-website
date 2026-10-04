import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')
const codeOnly = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const CONVO = 'app/messages/[threadId]/PeerConversationClient.tsx'
const MENU = 'components/ui/OverflowMenu.tsx'

/** The menu's props as written in the conversation header. */
function menuProps() {
  const src = codeOnly(CONVO)
  const i = src.indexOf('<OverflowMenu')
  assert.ok(i > 0, 'the header does not render the shared menu')
  return src.slice(i, src.indexOf('/>', i) + 2)
}

describe('the safety menu is recognisable as a control', () => {
  const src = codeOnly(CONVO)

  test('it is the shared menu, not a bespoke trigger', () => {
    assert.match(src, /import OverflowMenu from '@\/components\/ui\/OverflowMenu'/)
    assert.match(src, /<OverflowMenu/)
  })

  test('the bare punctuation trigger is gone', () => {
    // Three grey dots with no border, no surface and no icon read as
    // decoration. Lindsey could not find how to block anyone.
    assert.ok(!src.includes('···'), 'literal dots as text')
    assert.ok(!src.includes('⋯'), 'literal ellipsis as text')
    assert.ok(!/safetyOpen/.test(src), 'the hand-rolled panel state is gone')
  })

  test('it asks for the appearance that has an outline at rest', () => {
    assert.match(menuProps(), /appearance="outlined"/)
  })

  test('it carries the agreed accessible name', () => {
    assert.match(menuProps(), /ariaLabel="Conversation options"/)
  })

  test('it shows a word as well as an icon where there is room', () => {
    assert.match(menuProps(), /triggerLabel="More"/)
  })

  test('block and report are not promoted into the conversation body', () => {
    // Still behind the menu. Discoverable is not the same as dominant.
    const body = src.slice(src.indexOf('</OverflowMenu>') + 1)
    assert.ok(
      !/>\s*Block \$\{/.test(body),
      'Block must not sit loose in the conversation',
    )
  })
})

describe('what the menu offers depends on the state', () => {
  const src = codeOnly(CONVO)

  test('not blocked: block and report, both naming the person', () => {
    const props = menuProps()
    assert.match(props, /label: `Block \$\{firstName\}`/)
    assert.match(props, /label: `Report \$\{firstName\}`/)
  })

  test('it branches on blocked_by_me', () => {
    assert.match(menuProps(), /thread\.blocked_by_me/)
  })

  test('blocked: block is not offered again', () => {
    // The first branch of the conditional is the blocked one.
    const props = menuProps()
    const blocked = props.slice(props.indexOf('?'), props.indexOf(': ['))
    assert.ok(
      blocked.includes('Report '),
      'report must stay available to somebody already blocked',
    )
    assert.ok(
      !blocked.includes('Block '),
      'offering Block to somebody already blocked says nothing',
    )
  })

  test('the first name is derived, not the full display name', () => {
    assert.match(src, /const firstName = name\.split\(\/\\s\+\/\)\[0\] \|\| name/)
  })

  test('the blocked state keeps its history, its notice and unblock', () => {
    assert.match(src, /thread\.blocked_by_me \?/)
    assert.match(src, /Unblock \$\{name\}/)
    // No composer while blocked — the existing rule, unchanged.
    assert.match(src, /\{!thread\.blocked_by_me && \(/)
  })

  test('nobody is told they were blocked or reported', () => {
    assert.match(read(CONVO), /won.{1,8}t be told/)
    for (const smell of ['notifyBlock', 'notify(', 'sendNotification']) {
      assert.ok(!codeOnly(CONVO).includes(smell), `must not notify: ${smell}`)
    }
  })
})

describe('the menu itself', () => {
  const src = codeOnly(MENU)

  test('the outlined trigger is a real target with real states', () => {
    assert.match(src, /h-9 min-w-9/, '36px tall, usable on a phone')
    assert.match(src, /border bg-white/, 'legible before hover')
    assert.match(src, /hover:border-teal-300/)
    assert.match(src, /focus-visible:ring-2/)
  })

  test('the label is hidden on small screens, not dropped', () => {
    assert.match(src, /hidden text-\[13px\] font-medium sm:inline/)
  })

  test('it announces itself as a menu', () => {
    assert.match(src, /aria-haspopup="menu"/)
    assert.match(src, /aria-expanded=\{open\}/)
    assert.match(src, /role="menu"/)
    assert.match(src, /role="menuitem"/)
  })

  test('it closes on Escape and on an outside click', () => {
    assert.match(src, /e\.key === 'Escape'/)
    assert.match(src, /wrapRef\.current\?\.contains/)
  })

  test('the default appearance is unchanged for existing callers', () => {
    // PathwaysClient renders this too and was not part of this task.
    assert.match(src, /appearance = 'bare'/)
    assert.match(src, /defaultOpen = false/)
    assert.match(src, /h-8 w-8 items-center justify-center rounded-full/)
  })

  test('the existing caller did not have to change', () => {
    const caller = codeOnly('app/creator-studio/pathways/PathwaysClient.tsx')
    assert.ok(
      !/appearance=/.test(caller),
      'the bare default must still serve it',
    )
  })
})

describe('the preview still mutates nothing', () => {
  const src = codeOnly(CONVO)

  test('the menu can be opened for review without a click', () => {
    assert.match(menuProps(), /defaultOpen=\{previewOpen === 'menu'\}/)
  })

  test('opening the menu only sets local state', () => {
    // Both rows flip a panel open. Neither reaches the network.
    const props = menuProps()
    assert.match(props, /onClick: \(\) => \{ setConfirmBlock\(true\); setReporting\(false\) \}/)
    assert.match(props, /onClick: \(\) => \{ setReporting\(true\); setConfirmBlock\(false\) \}/)
    for (const call of ['blockPeer(', 'reportPeer(', 'unblockPeer(']) {
      assert.ok(!props.includes(call), `menu must not call ${call}`)
    }
  })

  test('the mutation guards are still in place', () => {
    assert.match(src, /if \(!previewOnly\) await blockPeer/)
    assert.match(src, /if \(!previewOnly\) await unblockPeer/)
    assert.match(src, /previewOnly\s*\?\s*'FC-PREVIEW'/)
  })

  test('the harness can reach all three conversation states', () => {
    const page = codeOnly('app/dev/connection-preview/page.tsx')
    assert.match(page, /CONVO_STATES: ConversationState\[\] = \['normal', 'blocked', 'report'\]/)
    assert.match(page, /previewOpen/)
  })
})
