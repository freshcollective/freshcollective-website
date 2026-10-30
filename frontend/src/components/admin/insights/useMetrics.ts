'use client'

import { useEffect, useState } from 'react'

import { type MetricResult, type PeriodKey, fetchMetrics } from '@/lib/insights'

/**
 * Fetch a set of metrics for a period, keeping the previous figures on
 * screen while the next ones arrive.
 *
 * Two reasons this is a hook rather than an effect per page. The obvious
 * one is that both pages need it. The less obvious one is that the naive
 * version calls `setLoading(true)` synchronously inside the effect,
 * which triggers a cascading render — so `loading` here is *derived* by
 * comparing the period that was asked for against the one the data came
 * back for. No state is set in the effect body; only in its callbacks.
 *
 * Keeping the old figures visible during a period change matters more
 * than it sounds: blanking the page to a spinner on every click makes
 * comparing two periods feel like two separate visits.
 */
export function useMetrics(keys: string[], period: PeriodKey) {
  const [result, setResult] = useState<{
    data: MetricResult | null
    forPeriod: PeriodKey | null
    error: string | null
  }>({ data: null, forPeriod: null, error: null })

  // Stable across renders so the effect does not re-run on every paint
  // because an inline array literal is a new object each time.
  const keyList = keys.join(',')

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false
    fetchMetrics(keyList.split(','), period, controller.signal)
      .then((data) => {
        if (!cancelled) setResult({ data, forPeriod: period, error: null })
      })
      .catch((e: Error) => {
        if (cancelled || e.name === 'AbortError') return
        setResult((prev) => ({ ...prev, forPeriod: period, error: e.message }))
      })
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [keyList, period])

  return {
    data: result.error ? null : result.data,
    error: result.error,
    /** True until the figures for the requested period have arrived. */
    loading: result.forPeriod !== period,
  }
}
