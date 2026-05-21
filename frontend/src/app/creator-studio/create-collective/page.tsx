import type { Metadata } from 'next'
import { getCreatorSpaces } from '@/lib/serverApi'
import CreateCollectiveFlow from './CreateCollectiveFlow'

export const metadata: Metadata = {
  title: 'Create a Collective — Fresh Collective',
}

export default async function CreateCollectivePage() {
  const spaces = await getCreatorSpaces()
  return <CreateCollectiveFlow existingCount={spaces.length} />
}
