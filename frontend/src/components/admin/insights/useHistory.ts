'use client'

import { useEffect, useState } from 'react'

import {
  type Grouping,
  type HistoryRangeKey,
  type HistoryResult,
  type PopulationKey,
  fetchHistory,
} from '@/lib/insights-history'

/**
 * Fetch a set of metrics as time series, keeping the last chart on
 * screen while the next one arrives.
 *
 * Same shape as `useMetrics`, and for the same two reasons: several
 * panels need it, and `loading` is *derived* by comparing what was
 * asked for against what came back rather than set inside the effect,
 * which would cascade a render. Blanking a chart to a spinner on every
 * control change makes comparing two groupings feel like two visits.
 */
export function useHistory(
  keys: string[],
  range: HistoryRangeKey,
  grouping: Grouping,
  population: PopulationKey,
) {
  const [state, setState] = useState<{
    data: HistoryResult | null
    for: string | null
    error: string | null
  }>({ data: null, for: null, error: null })

  const keyList = keys.join(',')
  const asked = `${keyList}|${range}|${grouping}|${population}`

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false
    fetchHistory(
      keyList.split(','),
      range,
      grouping,
      population,
      controller.signal,
    )
      .then((data) => {
        if (!cancelled) setState({ data, for: asked, error: null })
      })
      .catch((e: Error) => {
        if (cancelled || e.name === 'AbortError') return
        setState((prev) => ({ ...prev, for: asked, error: e.message }))
      })
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [keyList, range, grouping, population, asked])

  return {
    data: state.error ? null : state.data,
    error: state.error,
    loading: state.for !== asked,
  }
}
