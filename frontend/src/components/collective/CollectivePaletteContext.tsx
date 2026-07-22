'use client'

import React from 'react'
import type { CollectivePaletteMeta } from '@/lib/collectivePalette'

/**
 * Client-side React context carrying the currently-active collective
 * palette. Two mount points:
 *
 *   1. ``CollectiveThemeProvider`` (member routes) composes this so
 *      every descendant inside ``/spaces/[slug]/*`` sees the space's
 *      palette in addition to the CSS custom properties.
 *
 *   2. The creator-studio root layout composes this with the active
 *      space's palette so every editor mounted under
 *      ``/creator-studio/*`` sees the same palette when the writer
 *      opens the shared colour picker.
 *
 * The context value is nullable — when no palette is active
 * (unauthenticated, no active space, or a very new collective that
 * hasn't picked a colour story yet) the picker falls back to a
 * gracefully-empty "Your palette" row and the "More colours…" hex
 * flow still works.
 */

export const CollectivePaletteContext = React.createContext<CollectivePaletteMeta | null>(null)


interface ProviderProps {
  palette: CollectivePaletteMeta | null | undefined
  children: React.ReactNode
}

export function CollectivePaletteContextProvider({ palette, children }: ProviderProps) {
  return (
    <CollectivePaletteContext.Provider value={palette ?? null}>
      {children}
    </CollectivePaletteContext.Provider>
  )
}


/** Read the currently-active collective palette, or ``null`` when
 *  no palette is in scope (unmounted provider, unset colour story). */
export function useCollectivePalette(): CollectivePaletteMeta | null {
  return React.useContext(CollectivePaletteContext)
}
