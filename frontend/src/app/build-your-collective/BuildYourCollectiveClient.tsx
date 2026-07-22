'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import type {
  BuildYourCollectiveOptions,
  DraftData,
  BuildMode,
  LocationOption,
} from '@/lib/build-your-collective/types'

import WelcomeStep from '@/components/build/steps/WelcomeStep'
import LocationStep from '@/components/build/steps/LocationStep'
import AtmosphereStep from '@/components/build/steps/AtmosphereStep'
import ColourPaletteStep from '@/components/build/steps/ColourPaletteStep'
import IdentityStep from '@/components/build/steps/IdentityStep'
import WelcomeMessageStep from '@/components/build/steps/WelcomeMessageStep'
import PracticalDetailsStep from '@/components/build/steps/PracticalDetailsStep'
import ConfirmationStep from '@/components/build/steps/ConfirmationStep'
import OpeningTransition from '@/components/build/OpeningTransition'
import PortalTransition from '@/components/build/PortalTransition'

interface Props {
  options: BuildYourCollectiveOptions
  initialDraft: DraftData
  mode: BuildMode
  slug: string | null
}

/**
 * Orchestrator for Build Your Collective (Atlas v1.2).
 *
 * Steps 0..7:
 *   0 welcome  1 location  2 atmosphere  3 colour_palette
 *   4 identity  5 welcome_message  6 practical  7 confirmation
 *
 * Modes:
 *   create           — start at 0, autosave draft, POST /open at end
 *   change-location  — start at 1, seed from existing collective, PATCH at end
 *   edit-identity    — start at 2, keep existing location, PATCH at end
 *
 * The opening interlude and portal transition play only in create mode.
 * In edit modes we return the creator straight to Creator Studio on save.
 */
export default function BuildYourCollectiveClient({
  options, initialDraft, mode, slug,
}: Props) {
  const router = useRouter()

  const startStep = mode === 'change-location' ? 1 : mode === 'edit-identity' ? 2 : 0
  const [draft, setDraft] = useState<DraftData>(initialDraft)
  const [step, setStep] = useState<number>(initialDraft.step ?? startStep)
  const [busy, setBusy] = useState(false)
  const [openError, setOpenError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [interlude, setInterlude] = useState(false)
  const [portal, setPortal] = useState(false)
  const [portalPhase, setPortalPhase] = useState<'idle' | 'travelling' | 'arriving'>('idle')
  const openedSlugRef = useRef<string | null>(null)

  const draftRef = useRef(draft)
  useEffect(() => { draftRef.current = draft }, [draft])

  const patch = useCallback((p: Partial<DraftData>) => {
    setDraft((d) => ({ ...d, ...p }))
  }, [])

  const saveDraft = useCallback(async (nextStep: number) => {
    if (mode !== 'create') return  // edit modes don't touch the draft table
    setSaveError(null)
    try {
      const payload = { ...draftRef.current, step: nextStep }
      await fetch(apiUrl('/api/creator/build-your-collective/draft'), {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data: payload }),
      })
    } catch {
      setSaveError('Could not save your draft. Your choices are safe here — try continuing again.')
    }
  }, [mode])

  const goTo = useCallback((next: number) => {
    if (next < 0 || next > 7) return
    saveDraft(next)
    setStep(next)
  }, [saveDraft])

  // Edit-identity mode: skip the Location step even when the creator hits Back.
  const backFrom = useCallback((current: number) => {
    if (mode === 'edit-identity' && current === 2) return  // don't go back to Location
    if (mode !== 'create' && current === 1) return          // don't go back to Welcome in edit
    goTo(current - 1)
  }, [goTo, mode])

  // In edit modes we skip Practical Details (name/description/pricing).
  const stepAfterWelcomeMessage = mode === 'create' ? 6 : 7  // create → practical; edit → confirmation

  // Create mode plays an opening interlude before the reveal. Edit modes go
  // straight to the reveal.
  const goFromPractical = useCallback(() => {
    saveDraft(7)
    setInterlude(true)
  }, [saveDraft])

  const finishInterlude = useCallback(() => {
    setInterlude(false)
    setStep(7)
  }, [])

  const goToRevealFromWelcomeMessage = useCallback(() => {
    if (mode === 'create') {
      goTo(6) // → Practical
    } else {
      setStep(7) // → Confirmation directly
    }
  }, [goTo, mode])

  // Selected location resolved for the reveal / portal
  const selectedLocation: LocationOption | null =
    options.locations.find((l) => l.id === draft.location_id) ?? null

  const finishOrOpen = useCallback(async () => {
    setBusy(true)
    setOpenError(null)

    const identity = (draftRef.current.identity_statement ?? '').trim()
    const welcome = (draftRef.current.welcome_message ?? '').trim()
    const paletteKey = draftRef.current.colour_palette_key
    const locationId = draftRef.current.location_id
    const atmos = draftRef.current.atmosphere_keys ?? []

    if (mode === 'create') {
      // Play portal alongside the API call
      setPortal(true)
      setPortalPhase('travelling')
      const body = {
        name: (draftRef.current.name ?? '').trim(),
        description: draftRef.current.description?.trim() || null,
        location_id: locationId,
        atmosphere_keys: atmos,
        colour_palette_key: paletteKey,
        identity_statement: identity,
        welcome_message: welcome,
        visibility: draftRef.current.visibility ?? 'public',
        pricing_type: draftRef.current.pricing_type ?? 'free',
        pricing_amount_cents:
          draftRef.current.pricing_type === 'contribution'
            ? (draftRef.current.pricing_amount_cents ?? null)
            : null,
        pricing_note: draftRef.current.pricing_note?.trim() || null,
      }
      try {
        const res = await fetch(apiUrl('/api/creator/build-your-collective/open'), {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
        if (!res.ok) {
          const data = await res.json().catch(() => ({}))
          const detail = (data as { detail?: unknown }).detail
          setOpenError(typeof detail === 'string' ? detail : 'We could not open your collective. Please check your choices.')
          setPortal(false)
          setPortalPhase('idle')
          setBusy(false)
          return
        }
        const { slug: newSlug } = await res.json() as { slug: string }
        openedSlugRef.current = newSlug
        if (typeof window !== 'undefined') {
          window.sessionStorage.setItem('fc.justOpenedCollective', newSlug)
        }
      } catch {
        setOpenError('Something got in the way. Please try again in a moment.')
        setPortal(false)
        setPortalPhase('idle')
        setBusy(false)
      }
      return
    }

    // Edit modes — PATCH the existing collective, then return to Creator Studio.
    const patchBody: Record<string, unknown> = {
      atmosphere_keys: atmos,
      colour_palette_key: paletteKey,
      identity_statement: identity,
      welcome_message: welcome,
    }
    if (mode === 'change-location') {
      patchBody.location_id = locationId
    }
    try {
      const res = await fetch(apiUrl(`/api/creator/build-your-collective/${slug}`), {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patchBody),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        const detail = (data as { detail?: unknown }).detail
        setOpenError(typeof detail === 'string' ? detail : 'We could not save your changes. Please try again.')
        setBusy(false)
        return
      }
      // Return the creator to Creator Studio for the same collective.
      router.push('/creator-studio/settings')
    } catch {
      setOpenError('Something got in the way. Please try again in a moment.')
      setBusy(false)
    }
  }, [mode, slug, router])

  const finishPortal = useCallback(() => {
    setPortalPhase('arriving')
    const s = openedSlugRef.current
    if (s) router.push(`/creator/spaces/${s}`)
  }, [router])

  if (portal) {
    return (
      <PortalTransition
        artworkUrl={selectedLocation?.hero_artwork_url ?? null}
        locationName={selectedLocation?.name ?? null}
        onDone={finishPortal}
      />
    )
  }

  if (interlude) {
    return <OpeningTransition onDone={finishInterlude} />
  }

  switch (step) {
    case 0:
      return <WelcomeStep onBegin={() => goTo(1)} />

    case 1:
      return (
        <LocationStep
          locations={options.locations}
          value={draft.location_id ?? null}
          onChange={(id) => patch({ location_id: id })}
          onContinue={() => goTo(2)}
          onBack={() => backFrom(1)}
        />
      )

    case 2:
      return (
        <AtmosphereStep
          atmospheres={options.atmospheres}
          value={draft.atmosphere_keys ?? []}
          onChange={(keys) => patch({ atmosphere_keys: keys })}
          onContinue={() => goTo(3)}
          onBack={() => backFrom(2)}
        />
      )

    case 3:
      return (
        <ColourPaletteStep
          palettes={options.colour_palettes}
          value={draft.colour_palette_key ?? null}
          onChange={(k) => patch({ colour_palette_key: k })}
          onContinue={() => goTo(4)}
          onBack={() => backFrom(3)}
        />
      )

    case 4:
      return (
        <IdentityStep
          value={draft.identity_statement ?? ''}
          onChange={(v) => patch({ identity_statement: v })}
          onContinue={() => goTo(5)}
          onBack={() => backFrom(4)}
        />
      )

    case 5:
      return (
        <WelcomeMessageStep
          value={draft.welcome_message ?? ''}
          onChange={(v) => patch({ welcome_message: v })}
          onContinue={goToRevealFromWelcomeMessage}
          onBack={() => backFrom(5)}
        />
      )

    case 6:
      // Only reachable in create mode.
      return (
        <PracticalDetailsStep
          value={draft}
          onChange={patch}
          onContinue={goFromPractical}
          onBack={() => backFrom(6)}
        />
      )

    case 7:
      return (
        <ConfirmationStep
          draft={draft}
          location={selectedLocation}
          mode={mode}
          onOpen={finishOrOpen}
          onBack={() => setStep(mode === 'create' ? 6 : 5)}
          opening={busy || portalPhase !== 'idle'}
          error={openError ?? saveError}
        />
      )

    default:
      return null
  }

  // Suppress unused warning for the derived helper.
  void stepAfterWelcomeMessage
}
