import { getAdminCreators } from '@/lib/serverApi'
import CreatorsShell from './CreatorsShell'

/**
 * Creators — the World Management view of the people building the
 * platform. Server-fetches once; the client shell handles search,
 * filters, sort, and view preference.
 *
 * Sibling of /admin/collectives: Collectives shows communities, Creators
 * shows the humans behind them. Same design language, same infrastructure
 * pattern, different subject.
 */
export default async function CreatorsPage() {
  const rows = await getAdminCreators()
  return <CreatorsShell rows={rows} />
}
