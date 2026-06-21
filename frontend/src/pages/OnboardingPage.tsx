import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { authAPI, learnerAPI, curriculumAPI, setAccessToken, getAccessToken } from '@/lib/api'
import { useLearnerStore } from '@/stores/learnerStore'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'
import { AgentPill } from '@/components/ui/AgentPill'

type AuthMode = 'signin' | 'signup'

const GOAL_OPTIONS = [
  'Machine Learning', 'Statistics', 'Python', 'Linear Algebra',
  'Deep Learning', 'SQL', 'Probability', 'Calculus', 'Data Engineering',
  'NLP', 'Computer Vision', 'Web Development',
]

const PACING = [
  { v: 'gentle',     t: 'Gentle',     d: 'Build deep mastery before advancing. Lower friction, more time.' },
  { v: 'balanced',   t: 'Balanced',   d: 'Push when you\'re ready, ease when you slip. Recommended for most.' },
  { v: 'aggressive', t: 'Aggressive', d: 'Always one step ahead. Comfortable with friction and fast ramp-ups.' },
] as const

const inputStyle: React.CSSProperties = {
  display: 'block', width: '100%', marginTop: 6,
  padding: '10px 12px', fontSize: 14,
  background: 'var(--paper-0)', border: '1px solid var(--line-2)',
  borderRadius: 'var(--r-2)', color: 'var(--ink-0)',
  fontFamily: 'inherit', outline: 'none', boxSizing: 'border-box',
}

// Total steps: 0=Auth, 1=Name, 2=Goals, 3=Hours, 4=Difficulty, 5=Building (loading)
const TOTAL_STEPS = 4   // steps 1–4 (auth is step 0, building is step 5)

export default function OnboardingPage() {
  const navigate   = useNavigate()
  const setLearner = useLearnerStore((s) => s.setLearner)
  const learnerId  = useLearnerStore((s) => s.id)

  // If already authenticated, skip auth step (start at step 1)
  const [step, setStep]   = useState(learnerId ? 1 : 0)
  const [building, setBuilding] = useState(false)

  // Auth state
  const [authMode, setAuthMode]   = useState<AuthMode>('signup')
  const [authName, setAuthName]   = useState('')
  const [authEmail, setAuthEmail] = useState('')
  const [authPass, setAuthPass]   = useState('')
  const [showPass, setShowPass]   = useState(false)
  const [authLoading, setAuthLoading] = useState(false)

  // Onboarding state
  const [name, setNameLocal]  = useState('')
  const [goals, setGoals]     = useState<string[]>(['Machine Learning', 'Python'])
  const [hours, setHours]     = useState(6)
  const [diff, setDiff]       = useState<'gentle' | 'balanced' | 'aggressive'>('balanced')

  // If user navigates here already authenticated, skip to step 1
  useEffect(() => {
    if (learnerId && step === 0) setStep(1)
  }, [learnerId, step])

  const toggleGoal = (g: string) =>
    setGoals((prev) => {
      if (prev.includes(g)) return prev.filter((x) => x !== g)
      if (prev.length >= 10) { toast.error('Maximum 10 topics allowed.'); return prev }
      return [...prev, g]
    })

  // ── Step 0: Auth ─────────────────────────────────────────────────────────────
  const handleAuth = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!authEmail.trim()) { toast.error('Email is required.'); return }
    if (authPass.length < 6) { toast.error('Password must be at least 6 characters.'); return }
    if (authPass.length > 128) { toast.error('Password must be under 128 characters.'); return }
    if (authMode === 'signup' && authName.trim().length > 50) { toast.error('Name must be under 50 characters.'); return }
    setAuthLoading(true)
    try {
      const { data } = await authAPI.login(authEmail.trim().toLowerCase(), authPass)
      setAccessToken(data.access_token)
      const displayName = authMode === 'signup' && authName.trim() ? authName.trim() : data.user.name
      setLearner({ id: data.user.id, name: displayName, email: data.user.email })
      setNameLocal(displayName)

      if (authMode === 'signin') {
        // Returning user — check if already onboarded
        try {
          const prof = await learnerAPI.getProfile()
          if ((prof.data.goal_vector?.length ?? 0) > 0) {
            toast.success(`Welcome back, ${displayName}!`)
            navigate('/dashboard')
            return
          }
        } catch { /* continue onboarding */ }
        toast.success(`Welcome, ${displayName}!`)
      } else {
        toast.success(`Account created! Let's set up your plan.`)
      }
      setStep(1)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(msg ?? 'Authentication failed. Please try again.')
    } finally {
      setAuthLoading(false)
    }
  }

  const handleContinue = () => {
    if (step === 1) {
      const trimmed = name.trim()
      if (trimmed.length < 2) { toast.error('Name must be at least 2 characters.'); return }
      if (trimmed.length > 50) { toast.error('Name must be under 50 characters.'); return }
    }
    if (step === 2 && goals.length < 1) {
      toast.error('Select at least 1 topic to continue.')
      return
    }
    if (step < TOTAL_STEPS) setStep((s) => s + 1)
    else handleComplete()
  }

  // ── Final: build plan (call agents) ──────────────────────────────────────────
  const handleComplete = async () => {
    if (!getAccessToken()) {
      toast.error('Not authenticated. Please sign in first.')
      setStep(0)
      return
    }
    setBuilding(true)
    try {
      // Save onboarding preferences
      await learnerAPI.onboard({
        name:        name.trim() || authName.trim() || 'Learner',
        goals,
        hoursPerWeek: hours,
        difficulty:  diff,
      })
      setLearner({ name: name.trim() || authName.trim() })

      // Kick off curriculum agent in background (don't block navigation)
      curriculumAPI.generate().catch(() => { /* silent */ })

      // Short pause to show "building" screen
      await new Promise((r) => setTimeout(r, 2200))
      navigate('/dashboard')
    } catch (err) {
      toast.error('Could not save your plan. Please try again.')
      setBuilding(false)
    }
  }

  // ── "Building" loading screen ─────────────────────────────────────────────────
  if (building) {
    return (
      <div style={{ minHeight: '100%', background: 'var(--paper-0)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 32, padding: 32 }}>
        <div style={{ textAlign: 'center' }}>
          <div className="serif" style={{ fontSize: 36, color: 'var(--ink-0)', marginBottom: 8 }}>
            Building your plan
            <span style={{ display: 'inline-flex', gap: 3, marginLeft: 6, verticalAlign: 'middle' }}>
              {[0, 1, 2].map((i) => (
                <span key={i} style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--accent)', display: 'inline-block', animation: `blink 1.2s ease-in-out ${i * 0.3}s infinite` }} />
              ))}
            </span>
          </div>
          <p className="t-md fg-2" style={{ maxWidth: 420, lineHeight: 1.6 }}>
            Your agents are preparing a personalised curriculum based on your goals and pace.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', justifyContent: 'center' }}>
          {([
            { kind: 'curr',  label: 'Curriculum Planner', desc: 'Mapping your 8-week journey' },
            { kind: 'quiz',  label: 'Quiz Generator',     desc: 'Calibrating question difficulty' },
            { kind: 'prog',  label: 'Progress Tracker',   desc: 'Setting baseline proficiency' },
            { kind: 'doubt', label: 'Learning Assistant',  desc: 'Loading topic context' },
          ] as const).map((a, i) => (
            <div key={a.kind} style={{ textAlign: 'center', animation: `blink 1.6s ease-in-out ${i * 0.2}s infinite`, padding: '12px 16px', background: 'var(--paper-1)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', minWidth: 160 }}>
              <AgentPill kind={a.kind} state="thinking" />
              <div className="t-sm fg-0" style={{ fontWeight: 500, marginTop: 8 }}>{a.label}</div>
              <div className="t-xs fg-2" style={{ marginTop: 3 }}>{a.desc}</div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  const progress = step === 0 ? 0 : (step / TOTAL_STEPS) * 100

  return (
    <div style={{ minHeight: '100%', display: 'grid', gridTemplateColumns: '1fr 1fr', background: 'var(--paper-0)' }}>
      {/* LEFT — context panel */}
      <div style={{ padding: '64px 56px', borderRight: '1px solid var(--line-1)', background: 'var(--paper-1)', display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 48 }}>
          <div style={{ width: 22, height: 22, borderRadius: 5, background: 'var(--ink-0)', color: 'var(--paper-0)', display: 'grid', placeItems: 'center', fontFamily: 'var(--font-serif)', fontSize: 13, fontStyle: 'italic' }}>æ</div>
          <span className="t-md fg-0" style={{ fontWeight: 600 }}>Atelier</span>
        </div>

        {step > 0 && (
          <div className="caps" style={{ color: 'var(--accent)', marginBottom: 12 }}>
            Step {step} of {TOTAL_STEPS}
          </div>
        )}

        <h1 className="serif" style={{ fontSize: 'clamp(28px,3.5vw,44px)', lineHeight: 1.05, fontWeight: 400, color: 'var(--ink-0)', margin: 0, letterSpacing: '-0.02em' }}>
          {step === 0 && <>{authMode === 'signup' ? <>Create your<br /><span style={{ fontStyle: 'italic', color: 'var(--accent)' }}>free account.</span></> : <>Welcome<br /><span style={{ fontStyle: 'italic', color: 'var(--accent)' }}>back.</span></>}</>}
          {step === 1 && <>Tell us your name.<br /><span style={{ fontStyle: 'italic', color: 'var(--ink-2)' }}>We'll keep it informal.</span></>}
          {step === 2 && <>What do you want<br /><span style={{ fontStyle: 'italic', color: 'var(--accent)' }}>to learn?</span></>}
          {step === 3 && <>How much time<br /><span style={{ fontStyle: 'italic', color: 'var(--accent)' }}>do you have?</span></>}
          {step === 4 && <>Choose your<br /><span style={{ fontStyle: 'italic', color: 'var(--accent)' }}>pacing strategy.</span></>}
        </h1>

        <p className="t-lg fg-2" style={{ marginTop: 20, maxWidth: 380, lineHeight: 1.65 }}>
          {step === 0 && (authMode === 'signup' ? 'No credit card required. Your account is created instantly with your email and password.' : 'Enter your credentials to continue where you left off.')}
          {step === 1 && 'Your tutor addresses you by name. Choose anything you like — change it any time from settings.'}
          {step === 2 && 'Pick three to seven topics. We\'ll weave a personalised learning path around them.'}
          {step === 3 && 'We pace your modules to fit your schedule. You can always do more.'}
          {step === 4 && 'Three strategies, each calibrated to a different appetite for challenge. You can switch any time.'}
        </p>

        {step > 0 && (
          <div style={{ marginTop: 'auto', paddingTop: 40 }}>
            <div style={{ height: 3, background: 'var(--paper-3)', borderRadius: 2, overflow: 'hidden' }}>
              <div style={{ height: '100%', width: `${progress}%`, background: 'var(--ink-0)', borderRadius: 2, transition: 'width 0.4s ease' }} />
            </div>
            <div className="t-xs fg-3" style={{ marginTop: 8 }}>{Math.round(progress)}% complete</div>
          </div>
        )}
      </div>

      {/* RIGHT — input panel */}
      <div style={{ padding: '64px 56px', display: 'flex', flexDirection: 'column', overflowY: 'auto' }}>
        <div style={{ flex: 1, maxWidth: 480 }}>

          {/* Step 0: Auth */}
          {step === 0 && (
            <div>
              {/* Tabs */}
              <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid var(--line-1)', marginBottom: 24 }}>
                {(['signup', 'signin'] as AuthMode[]).map((m) => (
                  <button
                    key={m}
                    onClick={() => setAuthMode(m)}
                    style={{
                      padding: '8px 16px', fontSize: 13, fontWeight: authMode === m ? 600 : 400,
                      fontFamily: 'inherit', border: 0, background: 'none', cursor: 'pointer',
                      color: authMode === m ? 'var(--ink-0)' : 'var(--ink-2)',
                      borderBottom: authMode === m ? '2px solid var(--ink-0)' : '2px solid transparent',
                      marginBottom: -1,
                    }}
                  >
                    {m === 'signup' ? 'Create account' : 'Sign in'}
                  </button>
                ))}
              </div>

              <form onSubmit={handleAuth} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                {authMode === 'signup' && (
                  <div>
                    <label className="caps" style={{ color: 'var(--ink-2)', fontSize: 10 }}>Your name (optional)</label>
                    <input
                      value={authName}
                      onChange={(e) => setAuthName(e.target.value)}
                      placeholder="Mira"
                      autoFocus
                      style={inputStyle}
                      onFocus={(e) => (e.target.style.borderColor = 'var(--ink-1)')}
                      onBlur={(e)  => (e.target.style.borderColor = 'var(--line-2)')}
                    />
                  </div>
                )}
                <div>
                  <label className="caps" style={{ color: 'var(--ink-2)', fontSize: 10 }}>Email</label>
                  <input
                    type="email"
                    value={authEmail}
                    onChange={(e) => setAuthEmail(e.target.value)}
                    placeholder="you@example.com"
                    required
                    autoComplete="email"
                    autoFocus={authMode === 'signin'}
                    style={inputStyle}
                    onFocus={(e) => (e.target.style.borderColor = 'var(--ink-1)')}
                    onBlur={(e)  => (e.target.style.borderColor = 'var(--line-2)')}
                  />
                </div>
                <div>
                  <label className="caps" style={{ color: 'var(--ink-2)', fontSize: 10 }}>Password</label>
                  <div style={{ position: 'relative' }}>
                    <input
                      type={showPass ? 'text' : 'password'}
                      value={authPass}
                      onChange={(e) => setAuthPass(e.target.value)}
                      placeholder="Min 6 characters"
                      required minLength={6}
                      autoComplete={authMode === 'signin' ? 'current-password' : 'new-password'}
                      style={{ ...inputStyle, paddingRight: 38 }}
                      onFocus={(e) => (e.target.style.borderColor = 'var(--ink-1)')}
                      onBlur={(e)  => (e.target.style.borderColor = 'var(--line-2)')}
                    />
                    <button type="button" tabIndex={-1} onClick={() => setShowPass((v) => !v)}
                      style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 0, cursor: 'pointer', padding: 2, color: 'var(--ink-3)' }}>
                      <Icon name={showPass ? 'eye-off' : 'eye'} size={14} />
                    </button>
                  </div>
                </div>
                <Button type="submit" variant="primary" loading={authLoading} style={{ width: '100%', marginTop: 4 }}>
                  {authLoading
                    ? (authMode === 'signup' ? 'Creating account…' : 'Signing in…')
                    : (authMode === 'signup' ? 'Create account & continue' : 'Sign in & continue')}
                </Button>
              </form>

              <p className="t-xs fg-3" style={{ marginTop: 16, textAlign: 'center' }}>
                {authMode === 'signup'
                  ? <>Already have an account? <button type="button" onClick={() => setAuthMode('signin')} style={{ color: 'var(--accent)', background: 'none', border: 0, cursor: 'pointer', fontFamily: 'inherit', fontSize: 'inherit', padding: 0 }}>Sign in →</button></>
                  : <>No account? <button type="button" onClick={() => setAuthMode('signup')} style={{ color: 'var(--accent)', background: 'none', border: 0, cursor: 'pointer', fontFamily: 'inherit', fontSize: 'inherit', padding: 0 }}>Create one free →</button></>
                }
              </p>
            </div>
          )}

          {/* Step 1: Name */}
          {step === 1 && (
            <div>
              <label className="caps" style={{ color: 'var(--ink-2)' }}>Display name</label>
              <input
                value={name}
                onChange={(e) => setNameLocal(e.target.value)}
                autoFocus
                placeholder="Mira"
                style={{ width: '100%', marginTop: 8, padding: '10px 0', fontSize: 32, fontFamily: 'var(--font-serif)', background: 'transparent', border: 0, borderBottom: '1px solid var(--line-2)', color: 'var(--ink-0)', outline: 'none' }}
              />
              <div className="t-xs fg-3" style={{ marginTop: 8 }}>3–24 characters · change it any time</div>
            </div>
          )}

          {/* Step 2: Goals */}
          {step === 2 && (
            <div>
              <label className="caps" style={{ color: 'var(--ink-2)' }}>Topics — pick 3 to 7</label>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 12 }}>
                {GOAL_OPTIONS.map((g) => {
                  const active = goals.includes(g)
                  return (
                    <button key={g} onClick={() => toggleGoal(g)} style={{
                      padding: '6px 14px', fontSize: 13, fontWeight: 500, cursor: 'pointer',
                      background: active ? 'var(--ink-0)' : 'var(--paper-1)',
                      color: active ? 'var(--paper-0)' : 'var(--ink-1)',
                      border: `1px solid ${active ? 'var(--ink-0)' : 'var(--line-2)'}`,
                      borderRadius: 'var(--r-pill)', fontFamily: 'inherit',
                      transition: 'background var(--dur-fast)',
                    }}>{g}</button>
                  )
                })}
              </div>
              {goals.length > 0 && (
                <div style={{ marginTop: 20, padding: 12, background: 'var(--accent-soft)', borderRadius: 'var(--r-2)', display: 'flex', gap: 8, border: '1px solid var(--accent-line)' }}>
                  <Icon name="sparkle" size={13} style={{ color: 'var(--accent)', marginTop: 2, flexShrink: 0 }} />
                  <div className="t-sm fg-1">
                    <strong style={{ color: 'var(--accent)' }}>{goals.length} topic{goals.length > 1 ? 's' : ''} selected.</strong> We'll connect them into a personalised learning path.
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Step 3: Hours */}
          {step === 3 && (
            <div>
              <label className="caps" style={{ color: 'var(--ink-2)' }}>Hours per week</label>
              <div style={{ marginTop: 16, display: 'flex', alignItems: 'baseline', gap: 6 }}>
                <span className="serif" style={{ fontSize: 80, color: 'var(--ink-0)', fontWeight: 400, letterSpacing: '-0.03em' }}>{hours}</span>
                <span className="t-lg fg-2">hours</span>
              </div>
              <input type="range" min={1} max={20} value={hours} onChange={(e) => setHours(+e.target.value)}
                style={{ width: '100%', marginTop: 16, accentColor: 'var(--accent)' }} />
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
                <span className="t-xs fg-3">Casual · 1h</span>
                <span className="t-xs fg-3">Bootcamp · 20h</span>
              </div>
              <div style={{ marginTop: 24, padding: 14, background: 'var(--paper-1)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-2)' }}>
                <div className="t-sm fg-2">At {hours}h/week your plan covers</div>
                <div className="t-md fg-0" style={{ marginTop: 4, fontWeight: 500 }}>{Math.round(hours * 4 * 0.6)} modules over 8 weeks</div>
              </div>
            </div>
          )}

          {/* Step 4: Difficulty — the THREE STRATEGIES */}
          {step === 4 && (
            <div>
              <label className="caps" style={{ color: 'var(--ink-2)' }}>Difficulty pacing — choose one</label>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 14 }}>
                {PACING.map((o) => {
                  const active = diff === o.v
                  return (
                    <button key={o.v} onClick={() => setDiff(o.v)} style={{
                      padding: 16, textAlign: 'left', cursor: 'pointer', fontFamily: 'inherit',
                      border: `1.5px solid ${active ? 'var(--ink-0)' : 'var(--line-1)'}`,
                      background: active ? 'var(--paper-2)' : 'var(--paper-1)',
                      borderRadius: 'var(--r-3)', display: 'flex', alignItems: 'flex-start', gap: 14,
                      transition: 'border-color var(--dur-fast), background var(--dur-fast)',
                    }}>
                      <div style={{ width: 18, height: 18, borderRadius: '50%', border: `2px solid ${active ? 'var(--ink-0)' : 'var(--line-2)'}`, display: 'grid', placeItems: 'center', flexShrink: 0, marginTop: 2 }}>
                        {active && <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--ink-0)' }} />}
                      </div>
                      <div>
                        <div className="t-md fg-0" style={{ fontWeight: 600 }}>{o.t}</div>
                        <div className="t-sm fg-2" style={{ marginTop: 3 }}>{o.d}</div>
                      </div>
                    </button>
                  )
                })}
              </div>
            </div>
          )}
        </div>

        {/* Footer buttons (skip step 0 — it has its own submit button) */}
        {step > 0 && (
          <div style={{ display: 'flex', gap: 8, marginTop: 32, paddingTop: 20, borderTop: '1px solid var(--line-1)' }}>
            <Button variant="ghost" onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 1}>
              Back
            </Button>
            <span style={{ flex: 1 }} />
            {step < TOTAL_STEPS && (
              <Button variant="ghost" onClick={() => setStep((s) => s + 1)}>Skip</Button>
            )}
            <Button
              variant="primary"
              iconRight={step < TOTAL_STEPS ? 'arrow' : 'check'}
              onClick={handleContinue}
              loading={false}
            >
              {step < TOTAL_STEPS ? 'Continue' : 'Build my plan'}
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
