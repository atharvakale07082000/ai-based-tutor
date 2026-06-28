import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { authAPI, learnerAPI, curriculumAPI, setAccessToken, getAccessToken } from '@/lib/api'
import { useLearnerStore } from '@/stores/learnerStore'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'
import { AgentPill } from '@/components/ui/AgentPill'

type AuthMode = 'signin' | 'signup'

const URGENCY_OPTIONS = [
  { v: 'actively_looking', t: 'Actively looking',   d: 'I\'m applying now and want to move fast.' },
  { v: 'exploring',        t: 'Exploring options',   d: 'Open to opportunities but not rushing.' },
  { v: 'not_yet',          t: 'Preparing for later', d: 'Building skills for a future search.' },
] as const

const PREFERRED_COMPANIES = [
  'Google', 'Meta', 'Apple', 'Amazon', 'Microsoft', 'Netflix', 'Stripe', 'Airbnb',
  'Uber', 'Lyft', 'Coinbase', 'Figma', 'Notion', 'Linear', 'Vercel', 'Anthropic',
  'OpenAI', 'DeepMind', 'Palantir', 'Databricks',
]

const inputStyle: React.CSSProperties = {
  display: 'block', width: '100%', marginTop: 6,
  padding: '10px 12px', fontSize: 14,
  background: 'var(--paper-0)', border: '1px solid var(--line-2)',
  borderRadius: 'var(--r-2)', color: 'var(--ink-0)',
  fontFamily: 'inherit', outline: 'none', boxSizing: 'border-box',
}

// Total user-visible steps: 1=Name, 2=Target Role, 3=Urgency, 4=Experience
const TOTAL_STEPS = 4

export default function OnboardingPage() {
  const navigate   = useNavigate()
  const setLearner = useLearnerStore((s) => s.setLearner)
  const learnerId  = useLearnerStore((s) => s.id)

  const [step, setStep]         = useState(learnerId ? 1 : 0)
  const [building, setBuilding] = useState(false)

  // Auth state
  const [authMode, setAuthMode]   = useState<AuthMode>('signup')
  const [authName, setAuthName]   = useState('')
  const [authEmail, setAuthEmail] = useState('')
  const [authPass, setAuthPass]   = useState('')
  const [showPass, setShowPass]   = useState(false)
  const [authLoading, setAuthLoading] = useState(false)

  // Onboarding state
  const [name, setNameLocal]          = useState('')
  const [targetRole, setTargetRole]   = useState('')
  const [currentRole, setCurrentRole] = useState('')
  const [yearsExp, setYearsExp]       = useState(0)
  const [urgency, setUrgency]         = useState<'actively_looking' | 'exploring' | 'not_yet'>('exploring')
  const [preferredCompanies, setPreferredCompanies] = useState<string[]>([])
  const [roleQuery, setRoleQuery]     = useState('')
  const [roleSuggestions, setRoleSuggestions] = useState<string[]>([])
  const [allRoles, setAllRoles]       = useState<string[]>([])
  const roleInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (learnerId && step === 0) setStep(1)
  }, [learnerId, step])

  // Fetch canonical role list for autocomplete
  useEffect(() => {
    learnerAPI.getRoles().then((r) => setAllRoles(r.data.roles)).catch(() => { /* silent */ })
  }, [])

  // Role autocomplete
  useEffect(() => {
    if (!roleQuery.trim()) { setRoleSuggestions([]); return }
    const q = roleQuery.toLowerCase()
    setRoleSuggestions(allRoles.filter((r) => r.toLowerCase().includes(q)).slice(0, 5))
  }, [roleQuery, allRoles])

  const toggleCompany = (c: string) =>
    setPreferredCompanies((prev) => {
      if (prev.includes(c)) return prev.filter((x) => x !== c)
      if (prev.length >= 5) { toast.error('Maximum 5 companies.'); return prev }
      return [...prev, c]
    })

  // ── Step 0: Auth ─────────────────────────────────────────────────────────────
  const handleAuth = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!authEmail.trim()) { toast.error('Email is required.'); return }
    if (authPass.length < 6) { toast.error('Password must be at least 6 characters.'); return }
    if (authPass.length > 128) { toast.error('Password must be under 128 characters.'); return }
    setAuthLoading(true)
    try {
      const { data } = await authAPI.login(authEmail.trim().toLowerCase(), authPass)
      setAccessToken(data.access_token)
      const displayName = authMode === 'signup' && authName.trim() ? authName.trim() : data.user.name
      setLearner({ id: data.user.id, name: displayName, email: data.user.email, role: data.user.role })
      setNameLocal(displayName)

      if (authMode === 'signin') {
        try {
          const prof = await learnerAPI.getProfile()
          if (prof.data.target_role || (prof.data.goal_vector?.length ?? 0) > 0) {
            toast.success(`Welcome back, ${displayName}!`)
            navigate('/dashboard')
            return
          }
        } catch { /* continue */ }
        toast.success(`Welcome, ${displayName}!`)
      } else {
        toast.success('Account created! Let\'s set up your profile.')
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
    }
    if (step === 2 && !targetRole.trim()) {
      toast.error('Enter your target job role to continue.')
      return
    }
    if (step < TOTAL_STEPS) setStep((s) => s + 1)
    else handleComplete()
  }

  // ── Final: save profile & launch career path ─────────────────────────────────
  const handleComplete = async () => {
    if (!getAccessToken()) { toast.error('Not authenticated.'); setStep(0); return }
    setBuilding(true)
    try {
      await learnerAPI.onboard({
        name: name.trim() || authName.trim() || 'Job Seeker',
        goals: [targetRole].filter(Boolean),
        target_role: targetRole.trim(),
        current_role: currentRole.trim(),
        years_of_experience: yearsExp,
        job_search_urgency: urgency,
        preferred_companies: preferredCompanies,
      })
      setLearner({ name: name.trim() || authName.trim() })
      curriculumAPI.generate().catch(() => { /* non-critical, retry on dashboard */ })
      await new Promise((r) => setTimeout(r, 2200))
      toast('Building your personalised curriculum in the background…', { icon: '⚙️', duration: 4000 })
      navigate('/dashboard')
    } catch {
      toast.error('Could not save your profile. Please try again.')
      setBuilding(false)
    }
  }

  // ── Building screen ──────────────────────────────────────────────────────────
  if (building) {
    return (
      <div style={{ minHeight: '100%', background: 'var(--paper-0)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 32, padding: 32 }}>
        <div style={{ textAlign: 'center' }}>
          <div className="serif" style={{ fontSize: 36, color: 'var(--ink-0)', marginBottom: 8 }}>
            Building your career plan
            <span style={{ display: 'inline-flex', gap: 3, marginLeft: 6, verticalAlign: 'middle' }}>
              {[0, 1, 2].map((i) => (
                <span key={i} style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--accent)', display: 'inline-block', animation: `blink 1.2s ease-in-out ${i * 0.3}s infinite` }} />
              ))}
            </span>
          </div>
          <p className="t-md fg-2" style={{ maxWidth: 420, lineHeight: 1.6 }}>
            Mapping the skills for <strong>{targetRole || 'your target role'}</strong> and preparing your personalised roadmap.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', justifyContent: 'center' }}>
          {([
            { kind: 'curr',  label: 'Career Planner',    desc: 'Mapping role requirements' },
            { kind: 'quiz',  label: 'Interview Coach',   desc: 'Loading question banks' },
            { kind: 'prog',  label: 'Readiness Tracker', desc: 'Setting skill baseline' },
            { kind: 'doubt', label: 'Career Assistant',  desc: 'Preparing coaching context' },
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

  const leftHeadings: Record<number, React.ReactNode> = {
    0: authMode === 'signup'
      ? <><span>Land your next</span><br /><span style={{ fontStyle: 'italic', color: 'var(--accent)' }}>dream role.</span></>
      : <><span>Welcome</span><br /><span style={{ fontStyle: 'italic', color: 'var(--accent)' }}>back.</span></>,
    1: <><span>What should we</span><br /><span style={{ fontStyle: 'italic', color: 'var(--ink-2)' }}>call you?</span></>,
    2: <><span>What role are</span><br /><span style={{ fontStyle: 'italic', color: 'var(--accent)' }}>you targeting?</span></>,
    3: <><span>How urgently are</span><br /><span style={{ fontStyle: 'italic', color: 'var(--accent)' }}>you searching?</span></>,
    4: <><span>Tell us about</span><br /><span style={{ fontStyle: 'italic', color: 'var(--accent)' }}>your background.</span></>,
  }

  const leftSubtext: Record<number, string> = {
    0: authMode === 'signup'
      ? 'AI-powered interview prep, skill gap analysis, and a personalised career roadmap — free to start.'
      : 'Enter your credentials to continue your job search preparation.',
    1: 'Your career coach addresses you by name. You can change it any time from your profile.',
    2: 'We\'ll map the exact skills required for this role and build a gap-closing study plan around them.',
    3: 'This sets your prep intensity and pacing. You can change it any time.',
    4: 'We use your current background to focus prep on the skills that will move your readiness score the most.',
  }

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
          {leftHeadings[step]}
        </h1>

        <p className="t-lg fg-2" style={{ marginTop: 20, maxWidth: 380, lineHeight: 1.65 }}>
          {leftSubtext[step]}
        </p>

        {step === 2 && targetRole && (
          <div style={{ marginTop: 24, padding: '12px 16px', background: 'var(--accent-soft)', borderRadius: 'var(--r-2)', border: '1px solid var(--accent-line)' }}>
            <div className="caps" style={{ color: 'var(--accent)', fontSize: 10, marginBottom: 4 }}>Target role</div>
            <div className="t-md fg-0" style={{ fontWeight: 500 }}>{targetRole}</div>
          </div>
        )}

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
              <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid var(--line-1)', marginBottom: 24 }}>
                {(['signup', 'signin'] as AuthMode[]).map((m) => (
                  <button key={m} onClick={() => setAuthMode(m)} style={{
                    padding: '8px 16px', fontSize: 13, fontWeight: authMode === m ? 600 : 400,
                    fontFamily: 'inherit', border: 0, background: 'none', cursor: 'pointer',
                    color: authMode === m ? 'var(--ink-0)' : 'var(--ink-2)',
                    borderBottom: authMode === m ? '2px solid var(--ink-0)' : '2px solid transparent',
                    marginBottom: -1,
                  }}>
                    {m === 'signup' ? 'Create account' : 'Sign in'}
                  </button>
                ))}
              </div>

              <form onSubmit={handleAuth} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                {authMode === 'signup' && (
                  <div>
                    <label className="caps" style={{ color: 'var(--ink-2)', fontSize: 10 }}>Your name (optional)</label>
                    <input value={authName} onChange={(e) => setAuthName(e.target.value)} placeholder="Mira" autoFocus style={inputStyle}
                      onFocus={(e) => (e.target.style.borderColor = 'var(--ink-1)')}
                      onBlur={(e)  => (e.target.style.borderColor = 'var(--line-2)')} />
                  </div>
                )}
                <div>
                  <label className="caps" style={{ color: 'var(--ink-2)', fontSize: 10 }}>Email</label>
                  <input type="email" value={authEmail} onChange={(e) => setAuthEmail(e.target.value)} placeholder="you@example.com"
                    required autoComplete="email" autoFocus={authMode === 'signin'} style={inputStyle}
                    onFocus={(e) => (e.target.style.borderColor = 'var(--ink-1)')}
                    onBlur={(e)  => (e.target.style.borderColor = 'var(--line-2)')} />
                </div>
                <div>
                  <label className="caps" style={{ color: 'var(--ink-2)', fontSize: 10 }}>Password</label>
                  <div style={{ position: 'relative' }}>
                    <input type={showPass ? 'text' : 'password'} value={authPass} onChange={(e) => setAuthPass(e.target.value)}
                      placeholder="Min 6 characters" required minLength={6}
                      autoComplete={authMode === 'signin' ? 'current-password' : 'new-password'}
                      style={{ ...inputStyle, paddingRight: 38 }}
                      onFocus={(e) => (e.target.style.borderColor = 'var(--ink-1)')}
                      onBlur={(e)  => (e.target.style.borderColor = 'var(--line-2)')} />
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
                  : <>No account? <button type="button" onClick={() => setAuthMode('signup')} style={{ color: 'var(--accent)', background: 'none', border: 0, cursor: 'pointer', fontFamily: 'inherit', fontSize: 'inherit', padding: 0 }}>Create one free →</button></>}
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
              <div className="t-xs fg-3" style={{ marginTop: 8 }}>2–50 characters · change it any time from your profile</div>
            </div>
          )}

          {/* Step 2: Target Role */}
          {step === 2 && (
            <div>
              <label className="caps" style={{ color: 'var(--ink-2)' }}>Target role</label>
              <div style={{ position: 'relative', marginTop: 8 }}>
                <input
                  ref={roleInputRef}
                  value={roleQuery || targetRole}
                  onChange={(e) => { setRoleQuery(e.target.value); setTargetRole(e.target.value) }}
                  autoFocus
                  placeholder="e.g. Senior Software Engineer"
                  style={{ ...inputStyle, marginTop: 0 }}
                  onFocus={(e) => { e.target.style.borderColor = 'var(--ink-1)'; setRoleQuery(targetRole) }}
                  onBlur={(e)  => { setTimeout(() => setRoleSuggestions([]), 150); e.target.style.borderColor = 'var(--line-2)' }}
                />
                {roleSuggestions.length > 0 && (
                  <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 10, background: 'var(--paper-1)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-2)', overflow: 'hidden', boxShadow: 'var(--shadow-md)', marginTop: 2 }}>
                    {roleSuggestions.map((r) => (
                      <button key={r} onMouseDown={() => { setTargetRole(r); setRoleQuery(''); setRoleSuggestions([]) }}
                        style={{ display: 'block', width: '100%', padding: '10px 14px', textAlign: 'left', background: 'none', border: 0, cursor: 'pointer', fontFamily: 'inherit', fontSize: 14, color: 'var(--ink-0)' }}
                        onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--paper-2)')}
                        onMouseLeave={(e) => (e.currentTarget.style.background = 'none')}>
                        {r}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <div style={{ marginTop: 24 }}>
                <label className="caps" style={{ color: 'var(--ink-2)', fontSize: 10 }}>Dream companies (optional, max 5)</label>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10 }}>
                  {PREFERRED_COMPANIES.map((c) => {
                    const active = preferredCompanies.includes(c)
                    return (
                      <button key={c} onClick={() => toggleCompany(c)} style={{
                        padding: '5px 12px', fontSize: 12, cursor: 'pointer',
                        background: active ? 'var(--ink-0)' : 'var(--paper-1)',
                        color: active ? 'var(--paper-0)' : 'var(--ink-1)',
                        border: `1px solid ${active ? 'var(--ink-0)' : 'var(--line-2)'}`,
                        borderRadius: 'var(--r-pill)', fontFamily: 'inherit',
                        transition: 'background var(--dur-fast)',
                      }}>{c}</button>
                    )
                  })}
                </div>
              </div>
            </div>
          )}

          {/* Step 3: Urgency */}
          {step === 3 && (
            <div>
              <label className="caps" style={{ color: 'var(--ink-2)' }}>Job search urgency</label>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 14 }}>
                {URGENCY_OPTIONS.map((o) => {
                  const active = urgency === o.v
                  return (
                    <button key={o.v} onClick={() => setUrgency(o.v)} style={{
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

          {/* Step 4: Background (current role + years) */}
          {step === 4 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
              <div>
                <label className="caps" style={{ color: 'var(--ink-2)' }}>Current role (optional)</label>
                <input
                  value={currentRole}
                  onChange={(e) => setCurrentRole(e.target.value)}
                  autoFocus
                  placeholder="e.g. Junior Developer, Student, Career changer"
                  style={inputStyle}
                  onFocus={(e) => (e.target.style.borderColor = 'var(--ink-1)')}
                  onBlur={(e)  => (e.target.style.borderColor = 'var(--line-2)')}
                />
              </div>

              <div>
                <label className="caps" style={{ color: 'var(--ink-2)' }}>Years of experience</label>
                <div style={{ marginTop: 16, display: 'flex', alignItems: 'baseline', gap: 6 }}>
                  <span className="serif" style={{ fontSize: 72, color: 'var(--ink-0)', fontWeight: 400, letterSpacing: '-0.03em' }}>{yearsExp}</span>
                  <span className="t-lg fg-2">{yearsExp === 1 ? 'year' : 'years'}</span>
                </div>
                <input type="range" min={0} max={20} value={yearsExp} onChange={(e) => setYearsExp(+e.target.value)}
                  style={{ width: '100%', marginTop: 12, accentColor: 'var(--accent)' }} />
                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
                  <span className="t-xs fg-3">Student / Career changer</span>
                  <span className="t-xs fg-3">20+ years</span>
                </div>
              </div>

              <div style={{ padding: 14, background: 'var(--accent-soft)', borderRadius: 'var(--r-2)', border: '1px solid var(--accent-line)', display: 'flex', gap: 10 }}>
                <Icon name="sparkle" size={13} style={{ color: 'var(--accent)', marginTop: 2, flexShrink: 0 }} />
                <div className="t-sm fg-1">
                  We'll focus your prep on the{' '}
                  <strong style={{ color: 'var(--accent)' }}>highest-impact skill gaps</strong>{' '}
                  for {targetRole || 'your target role'} at your experience level.
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer buttons */}
        {step > 0 && (
          <div style={{ display: 'flex', gap: 8, marginTop: 32, paddingTop: 20, borderTop: '1px solid var(--line-1)' }}>
            <Button variant="ghost" onClick={() => setStep((s) => Math.max(1, s - 1))} disabled={step === 1}>
              Back
            </Button>
            <span style={{ flex: 1 }} />
            {step < TOTAL_STEPS && step !== 2 && (
              <Button variant="ghost" onClick={() => setStep((s) => s + 1)}>Skip</Button>
            )}
            <Button
              variant="primary"
              iconRight={step < TOTAL_STEPS ? 'arrow' : 'check'}
              onClick={handleContinue}
            >
              {step < TOTAL_STEPS ? 'Continue' : 'Build my career plan'}
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
