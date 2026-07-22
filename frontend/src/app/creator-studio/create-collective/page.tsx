import { redirect } from 'next/navigation'

/**
 * Legacy route → the guided ritual at `/build-your-collective` (Atlas v1.2).
 */
export default function CreateCollectiveRedirect() {
  redirect('/build-your-collective')
}
