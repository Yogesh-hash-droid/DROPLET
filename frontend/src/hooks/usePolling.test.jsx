import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { usePolling } from './usePolling.js'

afterEach(() => {
  vi.useRealTimers()
})

describe('usePolling', () => {
  it('polls on an interval and stops cleanly after unmount (no leaked timers)', async () => {
    vi.useFakeTimers()
    const fetcher = vi.fn(async () => ({ ok: true }))

    const { unmount } = renderHook(() => usePolling(fetcher, 100))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(fetcher).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(250)
    })
    expect(fetcher).toHaveBeenCalledTimes(3) // initial + t=100 + t=200

    unmount()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(fetcher).toHaveBeenCalledTimes(3) // no further calls after unmount
  })

  it('keeps the previous data and surfaces the error when a poll fails', async () => {
    vi.useFakeTimers()
    let shouldFail = false
    const fetcher = vi.fn(async () => {
      if (shouldFail) throw new Error('boom')
      return { value: 42 }
    })

    const { result, unmount } = renderHook(() => usePolling(fetcher, 100))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(result.current.data).toEqual({ value: 42 })
    expect(result.current.error).toBeNull()

    shouldFail = true
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100)
    })
    expect(result.current.error).toBe('boom')
    expect(result.current.data).toEqual({ value: 42 }) // stale data retained, not blanked

    unmount()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500)
    })
    expect(fetcher).toHaveBeenCalledTimes(2)
  })
})
