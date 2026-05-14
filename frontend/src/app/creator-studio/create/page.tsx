import type { Metadata } from 'next'
import { getCreatorSpaces } from '@/lib/serverApi'
import CreateCollectiveForm from './CreateCollectiveForm'

export const metadata: Metadata = {
  title: 'Create a Collective — Fresh Collective',
}

export default async function CreateCollectivePage() {
  const spaces = await getCreatorSpaces()
  return <CreateCollectiveForm existingCount={spaces.length} />
}
