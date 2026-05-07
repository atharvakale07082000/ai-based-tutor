import { useState, useCallback } from 'react'
import toast from 'react-hot-toast'
import { HF_MODELS, type HFModelKey } from '@/lib/hf'
import { useAgentStore } from '@/stores/agentStore'

interface UseHFInferenceResult<T> {
  infer: (...args: unknown[]) => Promise<T | null>
  data: T | null
  isLoading: boolean
  error: string | null
  latencyMs: number | null
  reset: () => void
}

export function useHFInference<T>(
  modelKey: HFModelKey,
  inferFn: (...args: unknown[]) => Promise<T>
): UseHFInferenceResult<T> {
  const [data, setData] = useState<T | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [latencyMs, setLatencyMs] = useState<number | null>(null)

  const { updateHFModel, incrementTokenUsage } = useAgentStore()

  const infer = useCallback(async (...args: unknown[]): Promise<T | null> => {
    setIsLoading(true)
    setError(null)
    updateHFModel(modelKey, { status: 'loading', lastUsed: Date.now() })

    const start = performance.now()
    try {
      const result = await inferFn(...args)
      const elapsed = Math.round(performance.now() - start)
      setLatencyMs(elapsed)
      setData(result)
      updateHFModel(modelKey, { status: 'ok', latencyMs: elapsed, lastUsed: Date.now() })
      // Estimate token usage (rough: 1 token ~ 4 chars for text results)
      if (typeof result === 'string') {
        incrementTokenUsage(modelKey, Math.ceil(result.length / 4))
      }
      return result
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Inference failed'
      setError(msg)
      updateHFModel(modelKey, { status: 'error' })
      toast.error(`${HF_MODELS[modelKey].split('/').pop()} · ${msg}`, {
        id: `hf-error-${modelKey}`,
        duration: 5000,
      })
      return null
    } finally {
      setIsLoading(false)
    }
  }, [modelKey, inferFn, updateHFModel, incrementTokenUsage])

  const reset = useCallback(() => {
    setData(null)
    setError(null)
    setLatencyMs(null)
  }, [])

  return { infer, data, isLoading, error, latencyMs, reset }
}

export default useHFInference
