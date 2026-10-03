/**
 * Fresh Collective — 404 Not Found page.
 *
 * Rendered by Next.js when `notFound()` is thrown or a route does not
 * resolve. Uses the primitives for typography and buttons; no
 * illustration per §16.
 *
 * @see docs/fresh-design-language.md §18.3
 */

import Link from 'next/link'
import { Button } from '@/components/platform/Button'
import { Heading } from '@/components/platform/Heading'
import { Text } from '@/components/platform/Text'

export default function NotFound() {
  return (
    <div className="mx-auto flex min-h-[60vh] w-full max-w-[520px] flex-col items-center justify-center px-6 py-16 text-center">
      <Text variant="eyebrow" muted className="mb-2">404</Text>
      <Heading variant="page-title" as="h1">Page not found.</Heading>
      <Text variant="body" className="mt-2 max-w-[42ch]">
        We couldn&apos;t find what you were looking for. It may have moved, or
        the link may be out of date.
      </Text>
      {/* Three ways onward rather than two. Discover Places was the
          missing one, and an old Wix link is the likeliest way to
          arrive here with no idea what Fresh Collective now is.

          Deliberately NOT legacy-specific copy. "This page belonged to
          an earlier version of Fresh Collective" would be wrong for the
          ordinary reasons people reach a 404 — a typo, a stale
          in-product link, a signed-out member — and this is the one 404
          for the whole app. The honest version says the link may be out
          of date, which covers both. */}
      <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
        <Link href="/" tabIndex={-1}>
          <Button variant="primary">Back to home</Button>
        </Link>
        <Link href="/spaces" tabIndex={-1}>
          <Button variant="tertiary">Explore collectives</Button>
        </Link>
        <Link href="/discover-places" tabIndex={-1}>
          <Button variant="tertiary">Discover places</Button>
        </Link>
      </div>
    </div>
  )
}
