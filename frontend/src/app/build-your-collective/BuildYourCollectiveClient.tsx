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
import ConfirmationStep, {
  type OpenDestination,
} from '@/components/build/steps/ConfirmationStep'
import OpeningTransition from '@/components/build/OpeningTransition'

export interface BuildYourCollectiveHeroArt {
  atmosphere: string | null
  identity: string | null
  welcomeMessage: string | null
  practical: string | null
}

const EMPTY_HERO_ART: BuildYourCollectiveHeroArt = {
  atmosphere: null,
  identity: null,
  welcomeMessage: null,
  practical: null,
}

interface Props {
  options: BuildYourCollectiveOptions
  initialDraft: DraftData
  mode: BuildMode
  slug: string | null
  heroArt?: BuildYourCollectiveHeroArt
}

/**
 * Orchestrator for Build Your Collective (Atlas v1.2).
 *
 * Steps 0..7:
 *   0 welcome  1 atmosphere  2 location  3 colour_palette
 *   4 identity  5 welcome_message  6 practical  7 confirmation
 *
 * The feeling of a collective is chosen before its island: the creator
 * names the atmosphere first, then picks the island that embodies it.
 *
 * Modes:
 *   create           — start at 0, autosave draft, POST /open at end
 *   change-location  — start at 2 (Location), seed from existing collective, PATCH at end
 *   edit-identity    — start at 1 (Atmosphere), keep existing location, PATCH at end
 *
 * In create mode step 7 is the combined arrival + World Builders
 * invitation. The two CTAs both trigger POST /open exactly once (guarded
 * by the busy flag) and route the creator to either World Builders or
 * their new collective's Creator Studio. In edit modes step 7 keeps the
 * simpler "Save your collective" reveal.
 */
export default function BuildYourCollectiveClient({
  options, initialDraft, mode, slug, heroArt = EMPTY_HERO_ART,
}: Props) {
  const router = useRouter()

  const startStep = mode === 'change-location' ? 2 : mode === 'edit-identity' ? 1 : 0
  const [draft, setDraft] = useState<DraftData>(initialDraft)
  const [step, setStep] = useState<number>(initialDraft.step ?? startStep)
  const [busy, setBusy] = useState(false)
  const [openError, setOpenError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [interlude, setInterlude] = useState(false)

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

  // Back-navigation guards. Each edit mode has a start step it should
  // never rewind past (there's nothing sensible before it — the creator
  // arrived directly).
  const backFrom = useCallback((current: number) => {
    if (mode === 'change-location' && current === 2) return  // Location is the start
    if (mode === 'edit-identity' && current === 1) return    // Atmosphere is the start
    if (mode === 'edit-identity' && current === 3) {         // Palette → back skips Location
      goTo(1)
      return
    }
    if (mode !== 'create' && current === 1) return           // any edit: never rewind to Welcome
    goTo(current - 1)
  }, [goTo, mode])

  // Atmosphere → next depends on mode: edit-identity keeps its existing
  // island and jumps to Colour Palette; every other mode continues to
  // Location as the natural next choice.
  const goFromAtmosphere = useCallback(() => {
    if (mode === 'edit-identity') goTo(3)
    else goTo(2)
  }, [goTo, mode])

  // Save current progress (create mode only — edit modes have no draft
  // table entry) and return the creator to My World inside Creator
  // Studio. The empty-state on /creator-studio surfaces a "Continue
  // setting up your collective →" affordance when a draft exists; the
  // same /build-your-collective link resumes from the saved step.
  const skip = useCallback(async () => {
    if (mode === 'create') {
      await saveDraft(step)
    }
    router.push('/creator-studio')
  }, [mode, saveDraft, step, router])

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

  // Selected location resolved for the reveal
  const selectedLocation: LocationOption | null =
    options.locations.find((l) => l.id === draft.location_id) ?? null

  const finishOrOpen = useCallback(async (destination?: OpenDestination) => {
    // Double-click / rapid re-entry guard: if a create/save is already
    // in flight, ignore any further clicks. Both primary and secondary
    // CTAs share the same busy flag so neither can trigger a duplicate.
    if (busy) return

    setBusy(true)
    setOpenError(null)

    const identity = (draftRef.current.identity_statement ?? '').trim()
    const welcome = (draftRef.current.welcome_message ?? '').trim()
    const paletteKey = draftRef.current.colour_palette_key
    const locationId = draftRef.current.location_id
    const atmos = draftRef.current.atmosphere_keys ?? []

    if (mode === 'create') {
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
          setBusy(false)
          return
        }
        const { slug: newSlug, world_builders_slug } = await res.json() as {
          slug: string
          name: string
          world_builders_slug: string | null
        }
        // Route based on which CTA the creator clicked. World Builders
        // routes into the Pathways area — that's where the guided
        // Creator experience lives. Creator Studio routes to the new
        // collective's Overview via the switch route, which sets the
        // active-space cookie so the whole sidebar + shell reflect
        // this collective from the very next render. Overview is the
        // natural home for a brand-new collective: it surfaces the
        // next actions (add pathway, add resource, invite people)
        // without dropping the creator into any single tool.
        if (destination === 'world_builders' && world_builders_slug) {
          router.push(`/spaces/${world_builders_slug}/pathways`)
        } else if (destination === 'creator_studio') {
          router.push(`/creator-studio/collective/switch/${newSlug}`)
        } else if (world_builders_slug) {
          router.push(`/spaces/${world_builders_slug}/pathways`)
        } else {
          router.push(`/creator-studio/collective/switch/${newSlug}`)
        }
        // Deliberately leave busy=true — the navigation is in flight,
        // and we don't want the CTAs re-enabling before the next page
        // takes over.
      } catch {
        setOpenError('Something got in the way. Please try again in a moment.')
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
  }, [busy, mode, slug, router])

  if (interlude) {
    return <OpeningTransition onDone={finishInterlude} />
  }

  switch (step) {
    case 0:
      return <WelcomeStep onBegin={() => goTo(1)} />

    case 1:
      return (
        <AtmosphereStep
          atmospheres={options.atmospheres}
          value={draft.atmosphere_keys ?? []}
          onChange={(keys) => patch({ atmosphere_keys: keys })}
          onContinue={goFromAtmosphere}
          onBack={() => backFrom(1)}
          onSkip={skip}
          heroUrl={heroArt.atmosphere}
        />
      )

    case 2:
      return (
        <LocationStep
          locations={options.locations}
          value={draft.location_id ?? null}
          onChange={(id) => patch({ location_id: id })}
          onContinue={() => goTo(3)}
          onBack={() => backFrom(2)}
          onSkip={skip}
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
          onSkip={skip}
        />
      )

    case 4:
      return (
        <IdentityStep
          value={draft.identity_statement ?? ''}
          onChange={(v) => patch({ identity_statement: v })}
          onContinue={() => goTo(5)}
          onBack={() => backFrom(4)}
          onSkip={skip}
          heroUrl={heroArt.identity}
        />
      )

    case 5:
      return (
        <WelcomeMessageStep
          value={draft.welcome_message ?? ''}
          onChange={(v) => patch({ welcome_message: v })}
          onContinue={goToRevealFromWelcomeMessage}
          onBack={() => backFrom(5)}
          onSkip={skip}
          heroUrl={heroArt.welcomeMessage}
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
          onSkip={skip}
          heroUrl={heroArt.practical}
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
          opening={busy}
          error={openError ?? saveError}
        />
      )

    default:
      return null
  }

  // Suppress unused warning for the derived helper.
  void stepAfterWelcomeMessage
}
