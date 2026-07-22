import { redirect } from 'next/navigation'

/**
 * Legacy route → the guided ritual at `/build-your-collective` (Atlas v1.2).
 */
export default function CreateRedirect() {
  redirect('/build-your-collective')
}
