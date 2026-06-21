import { useState, useRef, useCallback, useEffect } from 'react'
import toast from 'react-hot-toast'

// Browser Speech Recognition types (not in all lib.dom.d.ts versions)
interface ISpeechRecognition extends EventTarget {
  continuous: boolean
  interimResults: boolean
  lang: string
  maxAlternatives: number
  start(): void
  stop(): void
  abort(): void
  onresult: ((e: ISpeechRecognitionEvent) => void) | null
  onerror: ((e: ISpeechRecognitionErrorEvent) => void) | null
  onend: (() => void) | null
}
interface ISpeechRecognitionEvent extends Event {
  resultIndex: number
  results: { [i: number]: { isFinal: boolean; [j: number]: { transcript: string } }; length: number }
}
interface ISpeechRecognitionErrorEvent extends Event {
  error: string
}
type SpeechRecognitionCtor = new () => ISpeechRecognition

function getRecognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === 'undefined') return null
  return (
    (window as unknown as { SpeechRecognition?: SpeechRecognitionCtor }).SpeechRecognition ??
    (window as unknown as { webkitSpeechRecognition?: SpeechRecognitionCtor }).webkitSpeechRecognition ??
    null
  )
}

export interface UseSpeechInputOptions {
  /** Called with the interim (partial) transcript while the user is still speaking. */
  onInterim?: (text: string) => void
  /** Called once with the final transcript when the user stops speaking. */
  onFinal: (text: string) => void
  lang?: string
}

export interface UseSpeechInputReturn {
  isListening: boolean
  isSupported: boolean
  toggle: () => void
}

export function useSpeechInput({
  onInterim,
  onFinal,
  lang = 'en-US',
}: UseSpeechInputOptions): UseSpeechInputReturn {
  const [isListening, setIsListening] = useState(false)
  const isSupported = !!getRecognitionCtor()
  const recRef = useRef<ISpeechRecognition | null>(null)
  const finalAccRef = useRef('')   // accumulates final segments within one session

  const stop = useCallback(() => {
    recRef.current?.stop()
  }, [])

  const start = useCallback(() => {
    const Ctor = getRecognitionCtor()
    if (!Ctor) {
      toast.error('Voice input is not supported in this browser. Try Chrome or Edge.')
      return
    }

    const rec = new Ctor()
    rec.continuous = true      // keep listening until explicitly stopped
    rec.interimResults = true  // stream partial results
    rec.lang = lang
    rec.maxAlternatives = 1

    finalAccRef.current = ''
    recRef.current = rec

    rec.onresult = (e: ISpeechRecognitionEvent) => {
      let interim = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i]
        if (r.isFinal) {
          finalAccRef.current += r[0].transcript
        } else {
          interim += r[0].transcript
        }
      }
      // Show interim text in the input while the user speaks
      if (interim) onInterim?.(finalAccRef.current + interim)
    }

    rec.onerror = (e: ISpeechRecognitionErrorEvent) => {
      if (e.error === 'not-allowed' || e.error === 'permission-denied') {
        toast.error('Microphone access denied — please allow it in your browser settings.')
      } else if (e.error !== 'no-speech' && e.error !== 'aborted') {
        toast.error('Voice input stopped unexpectedly.')
      }
      setIsListening(false)
    }

    rec.onend = () => {
      setIsListening(false)
      const final = finalAccRef.current.trim()
      if (final) onFinal(final)
    }

    rec.start()
    setIsListening(true)
  }, [lang, onInterim, onFinal])

  const toggle = useCallback(() => {
    if (isListening) {
      stop()
    } else {
      start()
    }
  }, [isListening, start, stop])

  // Abort on unmount
  useEffect(() => () => { recRef.current?.abort() }, [])

  return { isListening, isSupported, toggle }
}
