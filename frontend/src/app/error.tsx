'use client'

/**
 * Fresh Collective — Route-scoped error boundary.
 *
 * Rendered by Next.js when a segment below the root layout throws during
 * render or data-fetch. This is NOT the fallback for framework or root
 * layout failures (that is `app/global-error.tsx`).
 *
 * @see docs/fresh-design-language.md §18.3
 */

import { useEffect } from 'react'
import Link from 'next/link'
import { Button } from '@/components/platform/Button'
import { Heading } from '@/components/platform/Heading'
import { Text } from '@/components/platform/Text'

interface Props {
  error: Error & { digest?: string }
  reset: () => void
}

export default function RouteError({ error, reset }: Props) {
  useEffect(() => {
    // Surface to the browser console during development; production errors
    // should already flow into whatever monitoring tool is configured.
    if (process.env.NODE_ENV !== 'production') {
      console.error('[Fresh Collective RouteError]', error)
    }
  }, [error])

  return (
    <div className="mx-auto flex min-h-[60vh] w-full max-w-[520px] flex-col items-center justify-center px-6 py-16 text-center">
      <Heading variant="page-title" as="h1">Something went wrong.</Heading>
      <Text variant="body" className="mt-2 max-w-[46ch]">
        The page could not load. Please try again — if this keeps happening,
        head back to the previous page and let us know.
      </Text>
      {error?.digest && (
        <Text variant="meta" muted className="mt-4">
          Reference: <span className="font-mono">{error.digest}</span>
        </Text>
      )}
      <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
        <Button variant="primary" onClick={reset}>Try again</Button>
        <Link href="/" tabIndex={-1}>
          <Button variant="tertiary">Back to home</Button>
        </Link>
      </div>
    </div>
  )
}
