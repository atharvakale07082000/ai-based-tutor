import { useState } from 'react'
import { useNavigate, Navigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { authAPI, learnerAPI, setAccessToken } from '@/lib/api'
import { useLearnerStore } from '@/stores/learnerStore'
import { Button } from '@/components/ui/Button'
import { AgentPill } from '@/components/ui/AgentPill'
import { Icon } from '@/components/ui/Icon'

type AuthMode = 'signin' | 'signup'

function AuthOverlay({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const setLearner = useLearnerStore((s) => s.setLearner)
  const [mode, setMode]         = useState<AuthMode>('signin')
  const [name, setName]         = useState('')
  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [showPass, setShowPass] = useState(false)
  const [loading, setLoading]   = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email.trim()) { toast.error('Email is required.'); return }
    if (password.length < 6) { toast.error('Password must be at least 6 characters.'); return }
    if (password.length > 128) { toast.error('Password must be under 128 characters.'); return }
    if (mode === 'signup' && name.trim().length > 50) { toast.error('Name must be under 50 characters.'); return }
    setLoading(true)
    try {
      const { data } = await authAPI.login(email.trim().toLowerCase(), password)
      setAccessToken(data.access_token)
      setLearner({ id: data.user.id, name: name.trim() || data.user.name, email: data.user.email })
      onClose()

      if (mode === 'signup') {
        navigate('/onboarding')
        return
      }
      // Sign-in: check if returning user has goals
      try {
        const prof = await learnerAPI.getProfile()
        const hasGoals = (prof.data.goal_vector?.length ?? 0) > 0
        toast.success(`Welcome back, ${data.user.name}!`)
        navigate(hasGoals ? '/dashboard' : '/onboarding')
      } catch {
        navigate('/dashboard')
      }
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(msg ?? 'Could not authenticate. Check your credentials.')
    } finally {
      setLoading(false)
    }
  }

  return (
    // backdrop
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 100,
        background: 'rgba(0,0,0,0.35)', backdropFilter: 'blur(4px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 16,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: '100%', maxWidth: 420,
          background: 'var(--paper-1)',
          border: '1px solid var(--line-2)',
          borderRadius: 'var(--r-4)',
          boxShadow: 'var(--shadow-3)',
          overflow: 'hidden',
        }}
      >
        {/* Tabs */}
        <div style={{ display: 'flex', borderBottom: '1px solid var(--line-1)' }}>
          {(['signin', 'signup'] as AuthMode[]).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              style={{
                flex: 1, padding: '14px 0', fontSize: 13, fontWeight: mode === m ? 600 : 400,
                fontFamily: 'inherit', border: 0, cursor: 'pointer',
                background: mode === m ? 'var(--paper-1)' : 'var(--paper-0)',
                color: mode === m ? 'var(--ink-0)' : 'var(--ink-2)',
                borderBottom: mode === m ? '2px solid var(--ink-0)' : '2px solid transparent',
                transition: 'all var(--dur-fast)',
              }}
            >
              {m === 'signin' ? 'Sign in' : 'Create account'}
            </button>
          ))}
          <button
            onClick={onClose}
            style={{ padding: '14px 16px', background: 'none', border: 0, cursor: 'pointer', color: 'var(--ink-3)' }}
          >
            <Icon name="close" size={14} />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            <h2 className="serif" style={{ fontSize: 22, fontWeight: 400, margin: '0 0 4px', color: 'var(--ink-0)' }}>
              {mode === 'signin' ? 'Welcome back.' : 'Join Atelier.'}
            </h2>
            <p className="t-sm fg-2">
              {mode === 'signin'
                ? 'Enter your credentials to continue learning.'
                : 'Free to start. No card required.'}
            </p>
          </div>

          {mode === 'signup' && (
            <div>
              <label className="caps" style={{ color: 'var(--ink-2)', fontSize: 10 }}>Your name</label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Mira"
                autoFocus
                maxLength={50}
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
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              required
              autoComplete="email"
              autoFocus={mode === 'signin'}
              style={inputStyle}
              onFocus={(e) => (e.target.style.borderColor = 'var(--ink-1)')}
              onBlur={(e)  => (e.target.style.borderColor = 'var(--line-2)')}
            />
          </div>

          <div>
            <label className="caps" style={{ color: 'var(--ink-2)', fontSize: 10 }}>Password</label>
            <div style={{ position: 'relative', marginTop: 5 }}>
              <input
                type={showPass ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Min 6 characters"
                required
                minLength={6}
                maxLength={128}
                autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
                style={{ ...inputStyle, paddingRight: 38, marginTop: 0 }}
                onFocus={(e) => (e.target.style.borderColor = 'var(--ink-1)')}
                onBlur={(e)  => (e.target.style.borderColor = 'var(--line-2)')}
              />
              <button
                type="button"
                tabIndex={-1}
                onClick={() => setShowPass((v) => !v)}
                style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 0, cursor: 'pointer', padding: 2, color: 'var(--ink-3)' }}
              >
                <Icon name={showPass ? 'eye-off' : 'eye'} size={14} />
              </button>
            </div>
          </div>

          <Button type="submit" variant="primary" loading={loading} style={{ width: '100%', marginTop: 4 }}>
            {loading ? (mode === 'signin' ? 'Signing in…' : 'Creating account…') : (mode === 'signin' ? 'Sign in' : 'Create account & continue')}
          </Button>

          <p className="t-xs fg-3" style={{ textAlign: 'center', marginTop: 4 }}>
            {mode === 'signin'
              ? <>No account? <button type="button" onClick={() => setMode('signup')} style={{ color: 'var(--accent)', background: 'none', border: 0, cursor: 'pointer', fontFamily: 'inherit', fontSize: 'inherit', padding: 0 }}>Create one free →</button></>
              : <>Already have one? <button type="button" onClick={() => setMode('signin')} style={{ color: 'var(--accent)', background: 'none', border: 0, cursor: 'pointer', fontFamily: 'inherit', fontSize: 'inherit', padding: 0 }}>Sign in →</button></>
            }
          </p>
        </form>
      </div>
    </div>
  )
}

const inputStyle: React.CSSProperties = {
  display: 'block', width: '100%', marginTop: 5,
  padding: '9px 11px', fontSize: 14,
  background: 'var(--paper-0)', border: '1px solid var(--line-2)',
  borderRadius: 'var(--r-2)', color: 'var(--ink-0)',
  fontFamily: 'inherit', outline: 'none', boxSizing: 'border-box',
}

export default function LandingPage() {
  const navigate = useNavigate()
  const learnerId = useLearnerStore((s) => s.id)
  const [showAuth, setShowAuth]     = useState(false)

  if (learnerId) return <Navigate to="/dashboard" replace />

  return (
    <div style={{ minHeight: '100%', background: 'var(--paper-0)', overflow: 'auto' }}>
      {showAuth && <AuthOverlay onClose={() => setShowAuth(false)} />}

      {/* Nav */}
      <nav style={{ position: 'sticky', top: 0, zIndex: 10, background: 'rgba(250,248,242,0.92)', backdropFilter: 'blur(8px)', borderBottom: '1px solid var(--line-1)' }}>
        <div style={{ maxWidth: 1200, margin: '0 auto', padding: '12px 32px', display: 'flex', alignItems: 'center', gap: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 22, height: 22, borderRadius: 5, background: 'var(--ink-0)', color: 'var(--paper-0)', display: 'grid', placeItems: 'center', fontFamily: 'var(--font-serif)', fontSize: 13, fontStyle: 'italic' }}>æ</div>
            <span className="t-md fg-0" style={{ fontWeight: 600 }}>Atelier</span>
          </div>
          <div style={{ flex: 1, display: 'flex', gap: 18 }}>
            {['Product', 'Agents', 'Pricing'].map((n) => (
              <a key={n} className="t-sm fg-2" style={{ cursor: 'pointer' }}>{n}</a>
            ))}
          </div>
          <Button size="sm" variant="ghost" onClick={() => setShowAuth(true)}>Sign in</Button>
          <Button size="sm" variant="primary" onClick={() => navigate('/onboarding')}>Get started</Button>
        </div>
      </nav>

      {/* Hero */}
      <section style={{ maxWidth: 1100, margin: '0 auto', padding: '80px 32px 60px' }}>
        <div className="caps" style={{ color: 'var(--accent)', marginBottom: 16 }}>Adaptive AI tutoring · Beta 0429</div>
        <h1 className="serif" style={{ fontSize: 'clamp(44px,6vw,80px)', lineHeight: 0.96, margin: 0, fontWeight: 400, color: 'var(--ink-0)', letterSpacing: '-0.03em', maxWidth: 860 }}>
          A tutor that learns<br />
          <span style={{ fontStyle: 'italic', color: 'var(--accent)' }}>how you learn.</span>
        </h1>
        <p className="t-lg fg-2" style={{ maxWidth: 580, marginTop: 24, lineHeight: 1.65 }}>
          Your personalised AI tutor — plans your week, generates practice questions, tracks every concept, and answers your doubts with full context awareness.
        </p>
        <div style={{ marginTop: 28, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <Button size="lg" variant="primary" iconRight="arrow" onClick={() => navigate('/onboarding')}>
            Start your first lesson
          </Button>
          <Button size="lg" variant="ghost" onClick={() => setShowAuth(true)}>
            Sign in
          </Button>
          <span className="t-sm fg-3" style={{ marginLeft: 4 }}>Free · no card · 3-minute setup</span>
        </div>

        {/* Agents row */}
        <div style={{ marginTop: 48, padding: 20, background: 'var(--paper-1)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', maxWidth: 640 }}>
          <div className="caps" style={{ color: 'var(--ink-3)', marginBottom: 12 }}>Agents on call</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            {([
              { kind: 'curr',  name: 'Curriculum Planner', desc: 'Sketches your week, adapts on Sunday.' },
              { kind: 'quiz',  name: 'Quiz Generator',     desc: 'Questions calibrated to your retention.' },
              { kind: 'prog',  name: 'Progress Tracker',   desc: 'Tracks 32 sub-skills. Surfaces gaps.' },
              { kind: 'doubt', name: 'Learning Assistant',  desc: 'Cites your materials when answering.' },
            ] as const).map((a) => (
              <div key={a.kind}>
                <AgentPill kind={a.kind} state="active" />
                <div className="t-sm fg-0" style={{ fontWeight: 500, marginTop: 6 }}>{a.name}</div>
                <div className="t-xs fg-2" style={{ marginTop: 2 }}>{a.desc}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* App preview mockup */}
      <section style={{ maxWidth: 1100, margin: '0 auto', padding: '0 32px 80px' }}>
        <div style={{ border: '1px solid var(--line-2)', borderRadius: 'var(--r-4)', overflow: 'hidden', boxShadow: 'var(--shadow-3)' }}>
          <div style={{ padding: '8px 12px', background: 'var(--paper-1)', borderBottom: '1px solid var(--line-1)', display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ display: 'flex', gap: 5 }}>
              {[0, 1, 2].map((i) => <span key={i} style={{ width: 9, height: 9, borderRadius: '50%', background: 'var(--line-2)' }} />)}
            </div>
            <span className="t-xs fg-3 mono">atelier.app/dashboard</span>
          </div>
          <div style={{ padding: 24, display: 'grid', gridTemplateColumns: '160px 1fr 220px', gap: 20, minHeight: 280, background: 'var(--paper-0)' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {['Dashboard', 'Today', 'Assistant', 'Courses', 'Doubts', 'Progress'].map((it, i) => (
                <div key={it} style={{ padding: '5px 8px', borderRadius: 5, background: i === 0 ? 'var(--paper-3)' : 'transparent', fontSize: 12, color: i === 0 ? 'var(--ink-0)' : 'var(--ink-2)' }}>{it}</div>
              ))}
            </div>
            <div>
              <div className="serif" style={{ fontSize: 28, color: 'var(--ink-0)' }}>Good morning, Mira.</div>
              <div className="t-sm fg-2" style={{ marginTop: 4, marginBottom: 16 }}>3 things on the docket today.</div>
              {['Ridge regression — derivation', 'Bayesian inference quiz', 'Review: derivatives'].map((t) => (
                <div key={t} style={{ padding: 10, border: '1px solid var(--line-1)', borderRadius: 6, display: 'flex', gap: 10, alignItems: 'center', background: 'var(--paper-1)', marginBottom: 6 }}>
                  <Icon name="book" size={13} style={{ color: 'var(--ink-3)' }} />
                  <span className="t-sm fg-0" style={{ flex: 1, fontWeight: 500 }}>{t}</span>
                  <span className="t-xs fg-3">20m</span>
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ padding: 12, background: 'var(--paper-1)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)' }}>
                <div className="caps" style={{ color: 'var(--ink-2)' }}>Streak</div>
                <div className="serif" style={{ fontSize: 28, color: 'var(--ink-0)', marginTop: 4 }}>12 <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>days</span></div>
              </div>
              <div style={{ padding: 12, background: 'var(--accent-soft)', border: '1px solid var(--accent-line)', borderRadius: 'var(--r-3)' }}>
                <div className="caps" style={{ color: 'var(--accent)' }}>Suggested</div>
                <div className="t-sm fg-0" style={{ marginTop: 4, fontWeight: 500 }}>Refresh derivatives</div>
                <div className="t-xs fg-3" style={{ marginTop: 2 }}>9-min · retention dipping</div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer style={{ borderTop: '1px solid var(--line-1)', padding: '28px 32px', background: 'var(--paper-1)' }}>
        <div style={{ maxWidth: 1100, margin: '0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span className="t-sm fg-3">© 2026 Atelier Learning</span>
          <div style={{ display: 'flex', gap: 12 }}>
            {['Privacy', 'Terms', 'Status'].map((l) => <a key={l} className="t-sm fg-2" style={{ cursor: 'pointer' }}>{l}</a>)}
          </div>
        </div>
      </footer>
    </div>
  )
}
