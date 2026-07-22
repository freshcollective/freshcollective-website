'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * useAutosave — debounced save-on-change for inline editors.
 *
 * Callers wrap their save function with the hook and drive it via
 * ``schedule(payload)``. The hook debounces the call, tracks a
 * user-visible status, and always flushes any pending save on unmount
 * so a fast writer never loses their last change to a route transition.
 *
 * Status values:
 *   - ``idle``   — no pending or in-flight save
 *   - ``dirty``  — a debounced save is scheduled
 *   - ``saving`` — the save is in flight
 *   - ``saved``  — the save just completed (auto-returns to idle)
 *   - ``error``  — the last save threw
 */

export type AutosaveStatus = 'idle' | 'dirty' | 'saving' | 'saved' | 'error'


export interface UseAutosaveOptions<T> {
  /** How long to wait after the most recent ``schedule()`` call before
   *  firing the save. Defaults to 600ms — comfortable for a writer. */
  delayMs?: number
  /** Called to perform the save. Should reject or throw on failure. */
  save: (payload: T) => Promise<void>
  /** Called after a save resolves. */
  onSaved?: () => void
  /** Called if a save throws. */
  onError?: (err: unknown) => void
}


export function useAutosave<T>({ delayMs = 600, save, onSaved, onError }: UseAutosaveOptions<T>) {
  const [status, setStatus] = useState<AutosaveStatus>('idle')
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pending = useRef<T | null>(null)
  const inFlight = useRef<Promise<void> | null>(null)
  // Latest ``save`` closure so a re-render doesn't strand an older save
  // function in the timer.
  const saveRef = useRef(save)
  saveRef.current = save

  /** Fire the save immediately with whatever the latest pending value is. */
  const flush = useCallback(async () => {
    if (timer.current) {
      clearTimeout(timer.current)
      timer.current = null
    }
    if (pending.current === null) return
    const payload = pending.current
    pending.current = null
    setStatus('saving')
    inFlight.current = (async () => {
      try {
        await saveRef.current(payload)
        setStatus('saved')
        onSaved?.()
        // Fade the "Saved" indicator after a couple of seconds.
        window.setTimeout(() => {
          setStatus((s) => (s === 'saved' ? 'idle' : s))
        }, 1500)
      } catch (err) {
        setStatus('error')
        onError?.(err)
      } finally {
        inFlight.current = null
      }
    })()
    return inFlight.current
  }, [onSaved, onError])

  const schedule = useCallback((payload: T) => {
    pending.current = payload
    setStatus('dirty')
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => { void flush() }, delayMs)
  }, [delayMs, flush])

  // Flush pending saves on unmount so writers never lose their last edit.
  useEffect(() => {
    return () => {
      if (timer.current) {
        clearTimeout(timer.current)
        timer.current = null
      }
      // Best-effort: fire whatever is pending. The Promise here will
      // resolve after unmount but the request is already in flight.
      if (pending.current !== null) {
        const payload = pending.current
        pending.current = null
        void saveRef.current(payload).catch(() => { /* swallowed — component gone */ })
      }
    }
  }, [])

  return { status, schedule, flush }
}
