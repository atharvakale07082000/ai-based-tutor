import { useState, useEffect, useRef, useCallback } from 'react'
import { useMutation } from '@tanstack/react-query'
import { progressAPI } from '@/lib/api'
import { Icon } from '@/components/ui/Icon'
import { useLocation } from 'react-router-dom'

const SESSIONS = [
  { label: '25m', minutes: 25 },
  { label: '15m', minutes: 15 },
  { label: '5m',  minutes: 5  },
]

const STUDY_ROUTES = ['/learn', '/quiz', '/doubts', '/assistant', '/courses']

export function PomodoroTimer() {
  const location = useLocation()
  const isStudyPage = STUDY_ROUTES.some((r) => location.pathname.startsWith(r))

  const [expanded, setExpanded] = useState(false)
  const [sessionMinutes, setSessionMinutes] = useState(25)
  const [secondsLeft, setSecondsLeft] = useState(25 * 60)
  const [running, setRunning] = useState(false)
  const [completed, setCompleted] = useState(false)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const startedRef = useRef<number | null>(null)   // epoch ms when timer started
  const totalSeconds = sessionMinutes * 60

  const recordMut = useMutation({
    mutationFn: ({ minutes, topic }: { minutes: number; topic: string }) =>
      progressAPI.recordStudySession({ minutes, topic: topic, activity: 'pomodoro' }),
  })

  const reset = useCallback(() => {
    if (intervalRef.current) clearInterval(intervalRef.current)
    setRunning(false)
    setCompleted(false)
    setSecondsLeft(sessionMinutes * 60)
    startedRef.current = null
  }, [sessionMinutes])

  // Reset when session length changes
  useEffect(() => { reset() }, [sessionMinutes])

  useEffect(() => {
    if (!running) return
    startedRef.current ??= Date.now()
    intervalRef.current = setInterval(() => {
      setSecondsLeft((s) => {
        if (s <= 1) {
          clearInterval(intervalRef.current!)
          setRunning(false)
          setCompleted(true)
          const elapsed = Math.round((Date.now() - (startedRef.current ?? Date.now())) / 60000)
          recordMut.mutate({ minutes: elapsed, topic: location.pathname.split('/')[2] ?? 'study' })
          // Browser notification if supported
          if ('Notification' in window && Notification.permission === 'granted') {
            new Notification('Pomodoro complete!', { body: `${sessionMinutes}m session done. Time for a break.`, icon: '/icon.png' })
          }
          return 0
        }
        return s - 1
      })
    }, 1000)
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [running])

  const mins = String(Math.floor(secondsLeft / 60)).padStart(2, '0')
  const secs = String(secondsLeft % 60).padStart(2, '0')
  const progress = 1 - secondsLeft / totalSeconds

  if (!isStudyPage) return null

  return (
    <div
      style={{
        position: 'fixed', bottom: 20, right: 20, zIndex: 500,
        display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 8,
      }}
    >
      {expanded && (
        <div
          style={{
            background: 'var(--paper-1)', border: '1px solid var(--line-1)',
            borderRadius: 'var(--r-3)', padding: '14px 16px', width: 220,
            boxShadow: 'var(--shadow-lg)',
          }}
        >
          {/* Session picker */}
          <div className="caps fg-3" style={{ marginBottom: 8 }}>Session length</div>
          <div style={{ display: 'flex', gap: 4, marginBottom: 12 }}>
            {SESSIONS.map((s) => (
              <button
                key={s.label}
                onClick={() => setSessionMinutes(s.minutes)}
                disabled={running}
                style={{
                  flex: 1, padding: '4px 0', borderRadius: 'var(--r-1)',
                  border: '1px solid var(--line-1)',
                  background: sessionMinutes === s.minutes ? 'var(--ink-0)' : 'none',
                  color: sessionMinutes === s.minutes ? 'var(--paper-0)' : 'var(--ink-1)',
                  fontSize: 12, cursor: running ? 'default' : 'pointer',
                  fontFamily: 'inherit',
                }}
              >
                {s.label}
              </button>
            ))}
          </div>

          {/* Timer display */}
          <div style={{ textAlign: 'center', marginBottom: 10 }}>
            <div
              className="mono"
              style={{
                fontSize: 32, fontWeight: 600, letterSpacing: '-0.02em',
                color: completed ? 'var(--pos)' : running ? 'var(--ink-0)' : 'var(--ink-2)',
              }}
            >
              {mins}:{secs}
            </div>
            {/* Progress arc (simple bar) */}
            <div style={{ height: 3, background: 'var(--paper-3)', borderRadius: 2, marginTop: 6, overflow: 'hidden' }}>
              <div
                style={{
                  width: `${progress * 100}%`, height: '100%', borderRadius: 2,
                  background: completed ? 'var(--pos)' : 'var(--accent)',
                  transition: 'width 1s linear',
                }}
              />
            </div>
            {completed && (
              <div className="t-xs" style={{ color: 'var(--pos)', marginTop: 6 }}>
                Session complete! Take a break.
              </div>
            )}
          </div>

          {/* Controls */}
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              onClick={() => running ? setRunning(false) : setRunning(true)}
              style={{
                flex: 1, padding: '6px 0', borderRadius: 'var(--r-2)',
                border: '1px solid var(--line-1)',
                background: running ? 'var(--paper-2)' : 'var(--ink-0)',
                color: running ? 'var(--ink-0)' : 'var(--paper-0)',
                fontSize: 12, cursor: 'pointer', fontFamily: 'inherit',
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4,
              }}
            >
              <Icon name={running ? 'pause' : 'play'} size={12} />
              {running ? 'Pause' : completed ? 'Again' : 'Start'}
            </button>
            <button
              onClick={reset}
              style={{
                padding: '6px 10px', borderRadius: 'var(--r-2)',
                border: '1px solid var(--line-1)', background: 'none',
                color: 'var(--ink-2)', fontSize: 12, cursor: 'pointer',
              }}
              title="Reset"
            >
              <Icon name="refresh" size={12} />
            </button>
          </div>
        </div>
      )}

      {/* Floating pill */}
      <button
        onClick={() => setExpanded((e) => !e)}
        title="Study timer"
        style={{
          display: 'flex', alignItems: 'center', gap: 6,
          padding: '6px 12px', borderRadius: 'var(--r-pill)',
          background: running ? 'var(--ink-0)' : 'var(--paper-1)',
          border: '1px solid var(--line-1)',
          color: running ? 'var(--paper-0)' : 'var(--ink-1)',
          fontSize: 12, cursor: 'pointer', fontFamily: 'inherit',
          boxShadow: 'var(--shadow-2)',
          transition: 'all 0.2s',
        }}
      >
        <Icon name={running ? 'pause' : 'clock'} size={13} />
        <span className="mono">{running || completed ? `${mins}:${secs}` : `${sessionMinutes}m`}</span>
        {completed && <Icon name="check" size={12} style={{ color: 'var(--pos)' }} />}
      </button>
    </div>
  )
}
