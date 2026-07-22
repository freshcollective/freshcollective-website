import { getAdminCollectives } from '@/lib/serverApi'
import CollectivesShell from './CollectivesShell'

/**
 * Collectives — the World Management view of every community alive in
 * Fresh Collective. Server-fetches the list once; the interactive Gallery /
 * List shell handles search, filters, sort, and view preference.
 *
 * The card and list-row treatments live inside CollectivesShell so both
 * views share one query state and one render tree.
 */
export default async function CollectivesPage() {
  const rows = await getAdminCollectives()
  return <CollectivesShell rows={rows} />
}
