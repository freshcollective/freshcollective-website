'use client'

import { createContext, useContext, type ReactNode } from 'react'

import type { BrandOverrides } from '@/lib/brand'

/**
 * Admin brand overrides for one request, read by every brand component
 * below it.
 *
 * Mounted once, in the root layout. The alternative — each header,
 * footer and sidebar resolving its own artwork — would issue a request
 * per chrome element and give each one its own chance to disagree with
 * the others.
 *
 * An empty context is a valid, complete state rather than a loading
 * one: the approved defaults are compile-time constants, so a brand
 * component renders the right artwork on the server, in the first
 * paint, with nothing to hydrate into. Overrides layer on top of that
 * and never replace a rendered default with a different one mid-life,
 * so there is no flicker to avoid.
 */
const BrandOverridesContext = createContext<BrandOverrides>({})

export function BrandProvider({
  overrides, children,
}: {
  overrides: BrandOverrides
  children: ReactNode
}) {
  return (
    <BrandOverridesContext.Provider value={overrides}>
      {children}
    </BrandOverridesContext.Provider>
  )
}

export function useBrandOverrides(): BrandOverrides {
  return useContext(BrandOverridesContext)
}
