import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

/**
 * Inviting a Collective's members from a spreadsheet, and getting the
 * member list back out of one.
 *
 * The parsing, the classification and the escaping all live in
 * `backend/app/services/member_csv.py` and `app/creator/routes.py`,
 * tested there. What is left for this file is the half a backend test
 * cannot see: that the screen asks before it sends, that it never puts
 * an address back on the page, and that the download link is a link
 * rather than a fetch into memory.
 */

const codeOnly = (src: string) =>
  src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const PEOPLE = codeOnly(
  readFileSync('src/app/creator-studio/people/PeopleClient.tsx', 'utf8'),
)
const PROXY = codeOnly(readFileSync('src/app/api/[...path]/route.ts', 'utf8'))

/** The import modal on its own, so a match elsewhere cannot pass for it. */
const MODAL = (() => {
  const start = PEOPLE.indexOf('function ImportMembersModal')
  assert.ok(start > 0, 'ImportMembersModal is missing')
  const end = PEOPLE.indexOf('\nfunction ', start + 10)
  return PEOPLE.slice(start, end > 0 ? end : undefined)
})()


describe('exporting the member list', () => {
  test('it is a link to the export route, not a fetch', () => {
    // A fetch would hold the whole file in the tab's memory and then
    // need a blob URL to hand it over; the browser already downloads.
    assert.match(PEOPLE, /href=\{apiUrl\(`\/api\/creator\/spaces\/\$\{spaceSlug\}\/members\/export\.csv`\)\}/)
    assert.match(PEOPLE, />\s*Export CSV\s*</)
  })

  test('the filename the server chose survives the proxy', () => {
    // Without this the download is called "export.csv" whatever the
    // Collective is.
    const allowlist = PROXY.match(
      /RESPONSE_HEADERS_ALLOWLIST[^]*?new Set\(\[([^\]]*)\]/,
    )
    assert.ok(allowlist, 'expected RESPONSE_HEADERS_ALLOWLIST in the proxy')
    assert.match(allowlist[1], /'content-disposition'/)
  })
})


describe('importing a member list', () => {
  test('a file is previewed before anything is sent', () => {
    assert.match(MODAL, /members\/import\/preview/)
    assert.match(MODAL, /if \(chosen\) void runPreview\(chosen, '', ''\)/)
  })

  test('the confirm button is the only thing that imports', () => {
    const confirm = MODAL.slice(MODAL.indexOf('async function confirm'))
    const body = confirm.slice(0, confirm.indexOf('\n  }'))
    assert.match(body, /members\/import`/)
    // The import endpoint must not be reachable from anywhere else in
    // the modal — choosing a file must not send invitations.
    const imports = MODAL.match(/members\/import`/g) ?? []
    assert.equal(imports.length, 1)
  })

  test('nothing can be confirmed until a preview says it can', () => {
    assert.match(
      MODAL,
      /disabled=\{busy \|\| !preview \|\| preview\.needs_email_column \|\| preview\.invitable === 0\}/,
    )
  })

  test('the button says how many people it would invite', () => {
    assert.match(MODAL, /Invite \$\{preview\.invitable\}/)
  })

  test('an unrecognised file asks which column, rather than failing', () => {
    assert.match(MODAL, /preview\.needs_email_column/)
    assert.match(MODAL, /Which column holds the email addresses\?/)
    assert.match(MODAL, /preview\.headings\.map/)
  })

  test('a recognised guess can still be overridden', () => {
    assert.match(MODAL, /Email column/)
    assert.match(MODAL, /Name column/)
    assert.match(MODAL, /No name column/)
  })

  test('a sample file is offered', () => {
    assert.match(MODAL, /members\/import-template\.csv/)
    assert.match(MODAL, /Download a sample file/)
  })

  test('it says plainly that an import invites and nothing more', () => {
    assert.match(MODAL, /does not add anyone to this Collective/)
    assert.match(MODAL, /they choose whether to accept/i)
  })

  test('unreadable rows are reported by line, never by value', () => {
    assert.match(MODAL, /preview\.invalid_lines/)
    assert.match(MODAL, /preview\.duplicate_lines/)
    // Nothing in the modal reads a row back out of a response: the
    // preview carries counts and line numbers and no addresses, and
    // rendering one would put somebody's contact list on the screen
    // of a feature whose job is to handle it carefully.
    assert.ok(!/\.rows\b/.test(MODAL), 'the modal must not render file rows')
    assert.ok(!/preview\.emails/.test(MODAL))
  })

  test('a file longer than one import says so', () => {
    assert.match(MODAL, /preview\.truncated/)
    assert.match(MODAL, /import the rest as a second file/i)
  })

  test('a new file clears the previous answer', () => {
    const choose = MODAL.slice(MODAL.indexOf('function chooseFile'))
    const body = choose.slice(0, choose.indexOf('\n  }'))
    assert.match(body, /setResult\(null\)/)
    assert.match(body, /setPreview\(null\)/)
    assert.match(body, /setEmailColumn\(''\)/)
  })

  test('the pending-invites list refreshes once people are invited', () => {
    assert.match(PEOPLE, /onImported=\{handleInviteCancelled\}/)
  })
})


describe('where the two sit on the page', () => {
  test('the import opens from Pending invites, where its results land', () => {
    const section = PEOPLE.slice(PEOPLE.indexOf('title="Pending invites"'))
    assert.match(section.slice(0, 800), /Invite from CSV/)
  })

  test('both are reachable without a mouse', () => {
    assert.match(PEOPLE, /Export CSV/)
    const exportLink = PEOPLE.slice(PEOPLE.indexOf('members/export.csv'))
    assert.match(exportLink.slice(0, 400), /focus-visible:outline-\[#246B6A\]/)
  })

  test('the file input is labelled', () => {
    assert.match(MODAL, /htmlFor="member-import-file"/)
    assert.match(MODAL, /id="member-import-file"/)
    assert.match(MODAL, /accept="\.csv,text\/csv"/)
  })

  test('the modal fits a phone', () => {
    // Full-bleed sheet on a small screen, centred card from sm up —
    // the same shape every other modal on this page uses.
    assert.match(MODAL, /items-end justify-center/)
    assert.match(MODAL, /sm:items-center/)
    assert.match(MODAL, /max-h-\[92vh\] w-full overflow-y-auto/)
  })
})
