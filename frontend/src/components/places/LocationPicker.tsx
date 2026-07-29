'use client'

/**
 * LocationPicker — a searchable Geographic Location field for the
 * Place & Feel tab in Creator Studio.
 *
 * The Creator types a city name; the picker proxies /api/places/lookup
 * (server-side, currently Nominatim), shows a small list of
 * suggestions, and on selection posts to /api/places/resolve which
 * returns a persisted Place row. The parent form receives just the
 * Place id + a compact display object so it can render the current
 * value without a second round trip.
 *
 * Kept deliberately simple: no map, no marker, no coordinates
 * exposed to the Creator. See
 * docs/foundations/discovery-connection-belonging-location-model.md
 * — Creators think in terms of places, not geographic data.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { apiUrl } from '@/lib/api'

export interface PickedPlace {
  id: string
  slug: string
  name: string
  region: string | null
  country_code: string
}

interface LookupResult {
  provider_place_id: string
  display: string
  name: string
  region: string
  country: string
  country_code: string
  latitude: number
  longitude: number
}

interface ResolveResponse {
  id: string
  slug: string
  name: string
  region: string | null
  country_code: string
}

interface Props {
  value: PickedPlace | null
  onChange: (place: PickedPlace | null) => void
  /** Rendered above the search input as a subtle helper. */
  helperText?: string
  disabled?: boolean
}

const MIN_QUERY = 2
const DEBOUNCE_MS = 250

export default function LocationPicker({
  value,
  onChange,
  helperText,
  disabled = false,
}: Props) {
  const [query, setQuery]         = useState('')
  const [results, setResults]     = useState<LookupResult[]>([])
  const [open, setOpen]           = useState(false)
  const [loading, setLoading]     = useState(false)
  const [resolving, setResolving] = useState(false)
  const [error, setError]         = useState<string | null>(null)
  const [focused, setFocused]     = useState<number>(-1)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  // Close on click outside.
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (!containerRef.current) return
      if (!containerRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  const runSearch = useCallback(async (q: string) => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(apiUrl('/api/places/lookup'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ query: q }),
      })
      if (!res.ok) {
        setResults([])
        setError('Location search is unavailable right now. Please try again.')
        return
      }
      const body = (await res.json()) as { results: LookupResult[] }
      setResults(body.results)
      setFocused(body.results.length > 0 ? 0 : -1)
    } catch {
      setResults([])
      setError('Location search is unavailable right now. Please try again.')
    } finally {
      setLoading(false)
    }
  }, [])

  function onInput(next: string) {
    setQuery(next)
    setOpen(true)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (next.trim().length < MIN_QUERY) {
      setResults([])
      return
    }
    debounceRef.current = setTimeout(() => runSearch(next.trim()), DEBOUNCE_MS)
  }

  async function selectResult(row: LookupResult) {
    setResolving(true)
    setError(null)
    try {
      const res = await fetch(apiUrl('/api/places/resolve'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ provider_place_id: row.provider_place_id }),
      })
      if (!res.ok) {
        setError('That place could not be saved. Please try picking again.')
        return
      }
      const body = (await res.json()) as ResolveResponse
      onChange({
        id: body.id,
        slug: body.slug,
        name: body.name,
        region: body.region,
        country_code: body.country_code,
      })
      setQuery('')
      setResults([])
      setOpen(false)
    } catch {
      setError('That place could not be saved. Please try picking again.')
    } finally {
      setResolving(false)
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!open || results.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setFocused((i) => (i + 1) % results.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setFocused((i) => (i - 1 + results.length) % results.length)
    } else if (e.key === 'Enter' && focused >= 0) {
      e.preventDefault()
      void selectResult(results[focused])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div ref={containerRef} className="max-w-md">
      {helperText && (
        <p className="mb-1.5 text-[13px] text-black">{helperText}</p>
      )}

      {/* Current value chip */}
      {value && (
        <div className="mb-2 flex items-start justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50/70 px-4 py-3">
          <div>
            <p className="font-serif text-[16px] text-navy-900">{value.name}</p>
            {value.region && (
              <p className="text-[13px] text-navy-500">
                {value.region}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={() => onChange(null)}
            disabled={disabled}
            className="text-[13px] text-navy-500 underline underline-offset-2 hover:text-navy-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 rounded"
          >
            Change
          </button>
        </div>
      )}

      {/* Search input — hidden when a value is set unless the Creator
          clicked Change (which clears value, so the picker reappears). */}
      {!value && (
        <div className="relative">
          <label htmlFor="place-picker" className="sr-only">
            Search for a city or region
          </label>
          <input
            id="place-picker"
            type="search"
            value={query}
            onChange={(e) => onInput(e.target.value)}
            onFocus={() => query.length >= MIN_QUERY && setOpen(true)}
            onKeyDown={onKeyDown}
            disabled={disabled || resolving}
            placeholder="Start typing a city…"
            autoComplete="off"
            aria-autocomplete="list"
            aria-controls="place-picker-list"
            aria-expanded={open && results.length > 0}
            className="w-full rounded-xl border border-slate-200 bg-white/70 px-4 py-2.5 text-[14px] text-navy-900 placeholder:text-slate-400 transition-colors focus:border-teal-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-teal-400/20"
          />

          {open && (query.trim().length >= MIN_QUERY) && (
            <div
              id="place-picker-list"
              role="listbox"
              className="absolute z-50 mt-1 w-full overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg"
            >
              {loading && (
                <p className="px-4 py-3 text-[13px] italic text-slate-500">
                  Searching…
                </p>
              )}
              {!loading && results.length === 0 && (
                <p className="px-4 py-3 text-[13px] italic text-slate-500">
                  No matches. Try another spelling or a nearby city.
                </p>
              )}
              {!loading && results.map((row, i) => {
                const active = i === focused
                return (
                  <button
                    key={row.provider_place_id}
                    type="button"
                    role="option"
                    aria-selected={active}
                    onMouseEnter={() => setFocused(i)}
                    onClick={() => selectResult(row)}
                    className={
                      'block w-full px-4 py-3 text-left text-[14px] transition-colors ' +
                      (active
                        ? 'bg-teal-50 text-navy-900'
                        : 'text-navy-700 hover:bg-slate-50')
                    }
                  >
                    {row.display}
                  </button>
                )
              })}
            </div>
          )}
        </div>
      )}

      {error && (
        <p role="alert" className="mt-2 text-[13px] text-[#A64526]">
          {error}
        </p>
      )}

      {resolving && (
        <p aria-live="polite" className="mt-2 text-[13px] italic text-slate-500">
          Saving…
        </p>
      )}
    </div>
  )
}
