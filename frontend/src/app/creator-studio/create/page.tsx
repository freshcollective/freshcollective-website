import type { Metadata } from 'next'
import CreateCollectiveForm from './CreateCollectiveForm'

export const metadata: Metadata = {
  title: 'Create a Collective — Fresh Collective',
}

export default function CreateCollectivePage() {
  return <CreateCollectiveForm />
}
