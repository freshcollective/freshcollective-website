import { strict as assert } from 'node:assert'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

import {
  ARCHIVED_STATUS,
  PATHWAYS_HREF,
  PATHWAY_ARCHIVE_HREF,
  RESTORED_STATUS,
  RESTORE_CONFIRM_PARAGRAPHS,
  activePathways,
  archivedPathways,
  isActivePathway,
  isRestorableStatus,
} from './pathwayLifecycle.ts'

const SRC = join(process.cwd(), 'src')
const MAIN = join(SRC, 'app', 'creator-studio', 'pathways', 'PathwaysClient.tsx')
const ARCHIVE_PAGE = join(
  SRC, 'app', 'creator-studio', 'pathways', 'archive', 'page.tsx',
)
const ARCHIVE_CLIENT = join(
  SRC, 'app', 'creator-studio', 'pathways', 'archive', 'PathwayArchiveClient.tsx',
)

function pathway(id: string, status: string, updated?: string | null) {
  return { id, status, updated_at: updated ?? null, created_at: '2026-01-01T00:00:00' }
}

describe('splitting active from archived', () => {
  it('only the archived status is archived', () => {
    // Archiving a Pathway is always a deliberate creator action —
    // nothing is derived from dates and nothing ages into it.
    for (const status of ['draft', 'active', 'coming_soon']) {
      assert.equal(isActivePathway({ status }), true, status)
    }
    assert.equal(isActivePathway({ status: ARCHIVED_STATUS }), false)
  })

  it('an unknown status stays on the main page', () => {
    // A status added later must not silently vanish into the archive.
    assert.equal(isActivePathway({ status: 'something_new' }), true)
  })

  it('splits a mixed list', () => {
    const all = [
      pathway('a', 'active'), pathway('b', 'archived'),
      pathway('c', 'draft'), pathway('d', 'archived'),
    ]
    assert.deepEqual(activePathways(all).map((p) => p.id), ['a', 'c'])
    assert.deepEqual(
      archivedPathways(all).map((p) => p.id).sort(), ['b', 'd'],
    )
  })

  it('handles an empty list', () => {
    assert.deepEqual(activePathways([]), [])
    assert.deepEqual(archivedPathways([]), [])
  })

  it('every pathway is in exactly one of the two', () => {
    const all = [
      pathway('a', 'active'), pathway('b', 'archived'),
      pathway('c', 'draft'), pathway('d', 'coming_soon'),
    ]
    assert.equal(
      activePathways(all).length + archivedPathways(all).length, all.length,
    )
  })
})

describe('archive ordering', () => {
  it('most recently touched first', () => {
    const all = [
      pathway('old', 'archived', '2026-01-05T00:00:00'),
      pathway('new', 'archived', '2026-09-20T00:00:00'),
      pathway('mid', 'archived', '2026-05-10T00:00:00'),
    ]
    assert.deepEqual(
      archivedPathways(all).map((p) => p.id), ['new', 'mid', 'old'],
    )
  })

  it('falls back to created_at when there is no updated_at', () => {
    const all = [
      { id: 'a', status: 'archived', updated_at: null, created_at: '2026-01-01T00:00:00' },
      { id: 'b', status: 'archived', updated_at: null, created_at: '2026-06-01T00:00:00' },
    ]
    assert.deepEqual(archivedPathways(all).map((p) => p.id), ['b', 'a'])
  })

  it('is stable when timestamps match', () => {
    // Two pathways archived in the same minute must not swap places
    // between renders.
    const same = '2026-05-10T00:00:00'
    const all = ['e', 'c', 'a', 'd', 'b'].map((id) => pathway(id, 'archived', same))
    const first = archivedPathways(all).map((p) => p.id)
    for (let i = 0; i < 5; i += 1) {
      assert.deepEqual(archivedPathways(all).map((p) => p.id), first)
    }
    assert.deepEqual(first, ['a', 'b', 'c', 'd', 'e'])
  })

  it('a pathway with no timestamps at all still appears', () => {
    const all = [
      { id: 'z', status: 'archived' },
      pathway('a', 'archived', '2026-05-10T00:00:00'),
    ]
    assert.deepEqual(archivedPathways(all).map((p) => p.id), ['a', 'z'])
  })
})

describe('restore returns a Pathway to Draft', () => {
  it('never to Live', () => {
    // The creator decides when it goes back in front of members.
    assert.equal(RESTORED_STATUS, 'draft')
    assert.notEqual(RESTORED_STATUS, 'active')
  })

  it('only an archived Pathway can be restored', () => {
    assert.equal(isRestorableStatus('archived'), true)
    for (const status of ['draft', 'active', 'coming_soon']) {
      assert.equal(isRestorableStatus(status), false, status)
    }
  })

  it('the confirmation says where it goes and what does not happen', () => {
    const copy = RESTORE_CONFIRM_PARAGRAPHS.join(' ')
    assert.ok(/Building/.test(copy))
    assert.ok(/review and edit/.test(copy))
    assert.ok(/Nothing is published/.test(copy))
    // Nothing that could read as "this goes live".
    assert.ok(!/publish(ed)? (it|now|immediately)/i.test(copy))
  })
})

describe('the main Pathways page', () => {
  const main = () => readFileSync(MAIN, 'utf8')

  it('no longer has an Archived group', () => {
    const source = main()
    const order = source.slice(
      source.indexOf('const STATUS_ORDER'),
      source.indexOf('// Component'),
    )
    assert.ok(/key: 'live'/.test(order))
    assert.ok(/key: 'building'/.test(order))
    assert.ok(
      !/key: 'archived'/.test(order),
      'the Archived group is back on the main page',
    )
  })

  it('filters archived pathways out rather than relying on the groups', () => {
    // So a status added later cannot quietly reappear in the gallery.
    assert.ok(/const visiblePathways = activePathways\(pathways\)/.test(main()))
  })

  it('keeps Live, Coming soon and Building', () => {
    const source = main()
    for (const label of ["label: 'Live'", "label: 'Coming soon'", "label: 'Building'"]) {
      assert.ok(source.includes(label), `missing ${label}`)
    }
  })

  it('offers the archive button, matching the Gathering archive pill', () => {
    const source = main()
    assert.ok(/View Pathway archive/.test(source))
    const link = source.slice(source.indexOf('function ArchiveLink'))
    assert.ok(/href=\{PATHWAY_ARCHIVE_HREF\}/.test(link))
    // The Gathering archive's own pill, so Creator Studio reads the same.
    const gathering = readFileSync(
      join(SRC, 'app', 'creator-studio', 'gatherings', 'page.tsx'), 'utf8',
    )
    assert.ok(gathering.includes('rounded-full px-4 py-2 text-[13px] font-medium'))
    assert.ok(link.includes('rounded-full px-4 py-2 text-[13px] font-medium'))
  })

  it('shows the button even with nothing archived', () => {
    // A door a creator can only find once they have used it is not a
    // door — so it is not conditional on the count.
    const source = main()
    const foot = source.slice(source.indexOf('<div className="mt-10 flex justify-center">'))
    assert.ok(/<ArchiveLink count=\{archivedCount\} \/>/.test(foot))
    assert.ok(
      !/archivedCount > 0 &&[\s\S]{0,60}<ArchiveLink/.test(source),
      'the archive link is hidden when nothing is archived',
    )
  })

  it('offers it from the empty state too', () => {
    // A collective whose only pathways are archived would otherwise
    // read as having none, with no way to the ones it has.
    const source = main()
    const empty = source.slice(
      source.indexOf('Your first pathway begins here.'),
      source.indexOf('// ── Grouped gallery'),
    )
    assert.ok(/<ArchiveLink count=\{archivedCount\} \/>/.test(empty))
  })
})

describe('the archive page', () => {
  it('exists at the route the button points at', () => {
    assert.ok(existsSync(ARCHIVE_PAGE), ARCHIVE_PAGE)
    assert.equal(PATHWAY_ARCHIVE_HREF, '/creator-studio/pathways/archive')
  })

  it('uses the agreed heading and copy', () => {
    const page = readFileSync(ARCHIVE_PAGE, 'utf8')
    assert.ok(/sectionTitle="Archived Pathways"/.test(page))
    assert.ok(/Their content and history are/.test(page))
    assert.ok(/restore them whenever you/.test(page))
  })

  it('reuses the existing Pathway card', () => {
    const client = readFileSync(ARCHIVE_CLIENT, 'utf8')
    assert.ok(/<PathwayCard/.test(client))
    assert.ok(/from '\.\.\/PathwaysClient'/.test(client))
  })

  it('needs no new endpoint', () => {
    // The list endpoint returns every status and always has, which is
    // why an archived Pathway was never lost — only hard to find.
    const page = readFileSync(ARCHIVE_PAGE, 'utf8')
    assert.ok(/getCreatorPathways\(activeSpace\.slug\)/.test(page))
    assert.ok(!/scope=/.test(page))
  })

  it('restores through the status the Settings dropdown has always used', () => {
    const client = readFileSync(ARCHIVE_CLIENT, 'utf8')
    assert.ok(/method: 'PATCH'/.test(client))
    assert.ok(/JSON\.stringify\(\{ status: RESTORED_STATUS \}\)/.test(client))
    assert.ok(
      !/'active'/.test(client),
      'the archive page can set a pathway live',
    )
  })

  it('confirms before restoring', () => {
    const client = readFileSync(ARCHIVE_CLIENT, 'utf8')
    assert.ok(/<LifecycleConfirmDialog/.test(client))
    assert.ok(/action="restore"/.test(client))
    assert.ok(/onConfirm=\{\(\) => restore\(confirming\)\}/.test(client))
  })

  it('cannot be double-submitted', () => {
    assert.ok(/if \(!activeSpace \|\| busyId\) return/.test(
      readFileSync(ARCHIVE_CLIENT, 'utf8'),
    ))
  })

  it('drops the restored pathway from the list', () => {
    const client = readFileSync(ARCHIVE_CLIENT, 'utf8')
    assert.ok(/prev\.filter\(\(p\) => p\.id !== pathway\.id\)/.test(client))
  })

  it('surfaces a refusal verbatim', () => {
    // The server's 409 names the record it is protecting; "try again"
    // would invite an action that can never succeed.
    const client = readFileSync(ARCHIVE_CLIENT, 'utf8')
    assert.ok(/actionErrorMessage\(/.test(client))
    assert.ok(/role="alert"/.test(client))
  })

  it('has an empty state that leads back', () => {
    const client = readFileSync(ARCHIVE_CLIENT, 'utf8')
    assert.ok(/Nothing archived yet\./.test(client))
    assert.ok(/will appear here/.test(client))
    assert.ok(/href=\{PATHWAYS_HREF\}/.test(client))
    assert.equal(PATHWAYS_HREF, '/creator-studio/pathways')
  })

  it('is the same responsive grid as the gallery', () => {
    const client = readFileSync(ARCHIVE_CLIENT, 'utf8')
    const main = readFileSync(MAIN, 'utf8')
    const grid = 'grid gap-6 sm:grid-cols-2 lg:grid-cols-3'
    assert.ok(client.includes(grid), 'the archive grid differs from the gallery')
    assert.ok(main.includes(grid))
  })
})

describe('the confirmation dialog serves all three actions', () => {
  const main = () => readFileSync(MAIN, 'utf8')

  it('restore is one of them', () => {
    const source = main()
    assert.ok(/'delete' \| 'archive' \| 'restore'/.test(source))
    assert.ok(/if \(action === 'restore'\)/.test(source))
    assert.ok(/confirm: 'Restore to Draft'/.test(source))
  })

  it('restore is not styled as destructive', () => {
    const source = main()
    const branch = source.slice(
      source.indexOf("if (action === 'restore')"),
      source.indexOf("if (action === 'archive')"),
    )
    assert.ok(/danger: false/.test(branch))
  })

  it('escape still cancels, so it stays keyboard-dismissable', () => {
    assert.ok(/e\.key === 'Escape'\) onCancel\(\)/.test(main()))
  })

  it('the menu item says Restore to Draft', () => {
    assert.ok(/Restore to Draft\n/.test(main()))
  })
})
