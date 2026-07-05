import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, Navigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { authAPI, learnerAPI, systemAPI, setAccessToken } from '@/lib/api'
import { useLearnerStore } from '@/stores/learnerStore'

/* ============================================================================
   "THE RATING" — Atelier landing page.
   Its own visual identity (deep ink-blue instrument panel), scoped to this page
   via the .bp-root wrapper so the app's cream design system stays untouched.
   Amber = your mastery (signature). Teal = the agents working for you.
   ========================================================================== */

// ── Small helpers ────────────────────────────────────────────────────────────

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false)
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    setReduced(mq.matches)
    const on = () => setReduced(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return reduced
}

// Count from 0 → target whenever `target` changes. The one orchestrated motion.
function useCountUp(target: number, reduced: boolean) {
  const [value, setValue] = useState(reduced ? target : 0)
  const raf = useRef<number>()
  useEffect(() => {
    if (reduced) { setValue(target); return }
    const start = performance.now()
    const from = 0
    const dur = 900
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / dur)
      const eased = 1 - Math.pow(1 - t, 3) // easeOutCubic
      setValue(Math.round(from + (target - from) * eased))
      if (t < 1) raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
    return () => { if (raf.current) cancelAnimationFrame(raf.current) }
  }, [target, reduced])
  return value
}

// Deterministic "interview-ready" rating band per role — grounded in the real
// per-concept ELO mechanic, used here as the target you climb toward.
function targetRating(role: string): number {
  if (!role) return 1600
  let h = 0
  for (let i = 0; i < role.length; i++) h = (h * 31 + role.charCodeAt(i)) >>> 0
  return 1560 + (h % 8) * 40 // 1560–1840, in tidy 40-pt steps
}

const AGENTS = [
  { sign: 'PLAN',   name: 'Curriculum Planner',  duty: 'Drafts your week toward the target role; adapts every Sunday.' },
  { sign: 'QUIZ',   name: 'Quiz Generator',      duty: 'Questions calibrated to your current rating on each concept.' },
  { sign: 'TRACK',  name: 'Progress Tracker',    duty: 'Rates 32 sub-skills and surfaces the ones slipping.' },
  { sign: 'ASSIST', name: 'Learning Assistant',  duty: 'Answers doubts and cites the material it drew from.' },
  { sign: 'INTV',   name: 'Interview Coach',     duty: 'Interviews you to unlock the next module — no coasting.' },
  { sign: 'JOBS',   name: 'Job Tracker',         duty: 'Maps every listing against your skills and closes the gaps.' },
] as const

const LOOP = [
  { k: 'Plan',      d: 'The planner lays out the week aimed squarely at your target role.' },
  { k: 'Learn',     d: 'You work through modules and a feed tuned to what you need next.' },
  { k: 'Quiz',      d: 'Calibrated questions move your rating on each concept, up or down.' },
  { k: 'Interview', d: 'A coach interviews you on the module. Pass to unlock the next one.' },
  { k: 'Re-rate',   d: 'Your rating settles, gaps resurface, and the plan rewrites itself.' },
] as const

// ── Auth overlay (logic preserved; restyled to the instrument palette) ────────

type AuthMode = 'signin' | 'signup' | 'forgot'

function AuthOverlay({ onClose, initialMode = 'signin' }: { onClose: () => void; initialMode?: AuthMode }) {
  const navigate = useNavigate()
  const setLearner = useLearnerStore((s) => s.setLearner)
  const [mode, setMode]         = useState<AuthMode>(initialMode)
  const [name, setName]         = useState('')
  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [showPass, setShowPass] = useState(false)
  const [loading, setLoading]   = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (mode === 'forgot') {
      if (!email.trim()) { toast.error('Email is required.'); return }
      setLoading(true)
      try {
        await authAPI.resetRequest(email.trim().toLowerCase())
        toast.success('Reset link sent — check your inbox.')
        setMode('signin')
      } catch {
        toast.error('Could not send reset link. Try again.')
      } finally { setLoading(false) }
      return
    }

    if (!email.trim()) { toast.error('Email is required.'); return }
    if (password.length < 6) { toast.error('Password must be at least 6 characters.'); return }
    if (password.length > 128) { toast.error('Password must be under 128 characters.'); return }
    if (mode === 'signup' && name.trim().length > 50) { toast.error('Name must be under 50 characters.'); return }
    setLoading(true)
    try {
      const { data } = await authAPI.login(email.trim().toLowerCase(), password)
      setAccessToken(data.access_token)
      setLearner({ id: data.user.id, name: name.trim() || data.user.name, email: data.user.email, role: data.user.role })
      onClose()
      if (mode === 'signup') { navigate('/onboarding'); return }
      toast.success(`Welcome back, ${data.user.name}!`)
      navigate('/dashboard')
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(msg ?? 'Could not authenticate. Check your credentials.')
    } finally { setLoading(false) }
  }

  return (
    <div className="bp-backdrop" onClick={onClose}>
      <div className="bp-modal" onClick={(e) => e.stopPropagation()}>
        <div className="bp-modal-tabs">
          {mode === 'forgot' ? (
            <button className="bp-tab" onClick={() => setMode('signin')}>← Back to sign in</button>
          ) : (
            (['signin', 'signup'] as AuthMode[]).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className="bp-tab"
                data-active={mode === m}
              >
                {m === 'signin' ? 'Sign in' : 'Create account'}
              </button>
            ))
          )}
          <button className="bp-tab bp-tab-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <form onSubmit={handleSubmit} className="bp-form">
          <div>
            <h2 className="bp-modal-title">
              {mode === 'signin' ? 'Welcome back.' : mode === 'signup' ? 'Open an account.' : 'Reset password.'}
            </h2>
            <p className="bp-modal-sub">
              {mode === 'signin'
                ? 'Sign in to pick up where your rating left off.'
                : mode === 'signup'
                  ? 'Free to start. No card. Three-minute setup.'
                  : "Enter your email and we'll send a reset link."}
            </p>
          </div>

          {mode === 'signup' && (
            <label className="bp-field">
              <span className="bp-label">Your name</span>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Mira" autoFocus maxLength={50} className="bp-input" />
            </label>
          )}

          <label className="bp-field">
            <span className="bp-label">Email</span>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com"
              required autoComplete="email" autoFocus={mode === 'signin'} className="bp-input" />
          </label>

          {mode !== 'forgot' && (
            <label className="bp-field">
              <span className="bp-label-row">
                <span className="bp-label">Password</span>
                {mode === 'signin' && (
                  <button type="button" onClick={() => setMode('forgot')} className="bp-link-btn">Forgot password?</button>
                )}
              </span>
              <span className="bp-input-wrap">
                <input type={showPass ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)}
                  placeholder="Min 6 characters" required minLength={6} maxLength={128}
                  autoComplete={mode === 'signin' ? 'current-password' : 'new-password'} className="bp-input" />
                <button type="button" tabIndex={-1} onClick={() => setShowPass((v) => !v)} className="bp-reveal">
                  {showPass ? 'hide' : 'show'}
                </button>
              </span>
            </label>
          )}

          <button type="submit" disabled={loading} className="bp-btn bp-btn-amber" style={{ width: '100%', marginTop: 4 }}>
            {loading
              ? (mode === 'forgot' ? 'Sending…' : mode === 'signin' ? 'Signing in…' : 'Creating account…')
              : (mode === 'forgot' ? 'Send reset link' : mode === 'signin' ? 'Sign in' : 'Create account & continue')}
          </button>

          <p className="bp-modal-foot">
            {mode === 'signin'
              ? <>No account? <button type="button" onClick={() => setMode('signup')} className="bp-link-inline">Create one free →</button></>
              : mode === 'signup'
                ? <>Already have one? <button type="button" onClick={() => setMode('signin')} className="bp-link-inline">Sign in →</button></>
                : null}
          </p>
        </form>
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function LandingPage() {
  const navigate = useNavigate()
  const learnerId = useLearnerStore((s) => s.id)
  const reduced = usePrefersReducedMotion()

  const [showAuth, setShowAuth] = useState(false)
  const [authMode, setAuthMode] = useState<AuthMode>('signin')
  const [roles, setRoles]       = useState<string[]>([])
  const [role, setRole]         = useState('Backend Engineer')
  const [version, setVersion]   = useState<string | null>(null)
  const [online, setOnline]     = useState<boolean | null>(null)

  // Real API — canonical target roles (public endpoint) power the readout.
  useEffect(() => {
    learnerAPI.getRoles()
      .then((r) => {
        const list = r.data.roles ?? []
        setRoles(list)
        if (list.length && !list.includes('Backend Engineer')) setRole(list[0])
      })
      .catch(() => { /* keep the sensible default role */ })
  }, [])

  // Real API — honest backend status line in the footer.
  useEffect(() => {
    systemAPI.health()
      .then((r) => { setOnline(r.data.status === 'ok'); setVersion(r.data.version) })
      .catch(() => setOnline(false))
  }, [])

  const target = useMemo(() => targetRating(role), [role])
  const shown = useCountUp(target, reduced)

  const openAuth = (m: AuthMode) => { setAuthMode(m); setShowAuth(true) }
  const startClimbing = () =>
    navigate(`/onboarding${role ? `?role=${encodeURIComponent(role)}` : ''}`)

  if (learnerId) return <Navigate to="/dashboard" replace />

  // Ladder rungs — the marker sits near the top (target), current is unrated (floor).
  const RUNGS = 11
  const markerRung = Math.round(RUNGS * 0.82)

  return (
    <div className="bp-root">
      <style>{BP_STYLES}</style>
      {showAuth && <AuthOverlay onClose={() => setShowAuth(false)} initialMode={authMode} />}

      {/* Nav */}
      <nav className="bp-nav">
        <div className="bp-nav-inner">
          <a className="bp-brand" onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}>
            <span className="bp-mark">◈</span>
            <span className="bp-brand-name">Atelier</span>
          </a>
          <div className="bp-nav-links">
            <a onClick={() => document.getElementById('agents')?.scrollIntoView({ behavior: 'smooth' })}>Agents</a>
            <a onClick={() => document.getElementById('loop')?.scrollIntoView({ behavior: 'smooth' })}>The loop</a>
          </div>
          <div className="bp-nav-cta">
            <button className="bp-btn bp-btn-ghost" onClick={() => openAuth('signin')}>Sign in</button>
            <button className="bp-btn bp-btn-amber" onClick={startClimbing}>Start climbing</button>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="bp-hero">
        <div className="bp-hero-copy">
          <div className="bp-eyebrow"><span className="bp-eyebrow-tick" />A rating for what you know</div>
          <h1 className="bp-headline">
            Learn like<br />it&rsquo;s <span className="bp-amber-text">measured.</span>
          </h1>
          <p className="bp-lede">
            Most courses hand you a checklist and hope. Atelier puts a live rating on every
            concept you touch — and runs six agents that plan, quiz, and interview you until
            the number moves. You always know exactly where you stand.
          </p>
          <div className="bp-hero-actions">
            <button className="bp-btn bp-btn-amber bp-btn-lg" onClick={startClimbing}>
              Start climbing →
            </button>
            <button className="bp-btn bp-btn-outline bp-btn-lg" onClick={() => openAuth('signin')}>
              Sign in
            </button>
          </div>
          <div className="bp-hero-facts">
            <span><b>32</b> sub-skills rated</span>
            <span className="bp-dot">·</span>
            <span><b>6</b> agents on call</span>
            <span className="bp-dot">·</span>
            <span>spaced-repetition built in</span>
          </div>
        </div>

        {/* Signature: the instrument readout */}
        <div className="bp-readout" role="group" aria-label="Rating readout">
          <div className="bp-readout-head">
            <span className="bp-readout-tag">RATING READOUT</span>
            <span className="bp-readout-live"><span className="bp-live-dot" />live</span>
          </div>

          <div className="bp-readout-body">
            <div className="bp-readout-cols">
              <div className="bp-col">
                <div className="bp-col-label">CURRENT</div>
                <div className="bp-col-value bp-muted-num">——</div>
                <div className="bp-col-note">unrated</div>
              </div>
              <div className="bp-col-arrow">→</div>
              <div className="bp-col">
                <div className="bp-col-label">TARGET</div>
                <div className="bp-col-value bp-amber-text">{shown}</div>
                <div className="bp-col-note">interview-ready</div>
              </div>
            </div>

            {/* Ladder */}
            <div className="bp-ladder" aria-hidden="true">
              {Array.from({ length: RUNGS }).map((_, i) => {
                const rungFromBottom = RUNGS - 1 - i
                const isMarker = rungFromBottom === markerRung
                return (
                  <div key={i} className="bp-rung-row">
                    <span className="bp-rung-tick">{String(1800 - i * 30).padStart(4, '0')}</span>
                    <span className={`bp-rung ${rungFromBottom <= markerRung ? 'bp-rung-lit' : ''}`} />
                    {isMarker && <span className="bp-marker">▸ you, ready</span>}
                  </div>
                )
              })}
            </div>

            {/* Real API: choose your target role */}
            <label className="bp-role">
              <span className="bp-role-label">Target role</span>
              <div className="bp-select-wrap">
                <select
                  className="bp-select"
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                >
                  {(roles.length ? roles : [role]).map((r) => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </select>
                <span className="bp-select-caret">▾</span>
              </div>
            </label>
            <p className="bp-readout-foot">
              Rating you&rsquo;re climbing toward to clear <b>{role}</b> interviews.
            </p>
          </div>
        </div>
      </section>

      {/* Agents rack */}
      <section id="agents" className="bp-section">
        <div className="bp-section-head">
          <span className="bp-section-tag bp-teal-text">// agents on call</span>
          <h2 className="bp-section-title">A studio, not a chatbot.</h2>
          <p className="bp-section-lede">
            Six specialists share the work. Each has one job and does it with your rating in view.
          </p>
        </div>
        <div className="bp-rack">
          {AGENTS.map((a) => (
            <article key={a.sign} className="bp-agent">
              <div className="bp-agent-sign">{a.sign}</div>
              <div className="bp-agent-name">{a.name}</div>
              <p className="bp-agent-duty">{a.duty}</p>
            </article>
          ))}
        </div>
      </section>

      {/* The loop */}
      <section id="loop" className="bp-section bp-section-loop">
        <div className="bp-section-head">
          <span className="bp-section-tag bp-amber-text">// how a rating climbs</span>
          <h2 className="bp-section-title">The loop.</h2>
          <p className="bp-section-lede">
            Not a syllabus you finish — a cycle you repeat until the number is where it needs to be.
          </p>
        </div>
        <ol className="bp-loop">
          {LOOP.map((s, i) => (
            <li key={s.k} className="bp-loop-step">
              <span className="bp-loop-num">{String(i + 1).padStart(2, '0')}</span>
              <div>
                <div className="bp-loop-k">{s.k}</div>
                <p className="bp-loop-d">{s.d}</p>
              </div>
            </li>
          ))}
          <li className="bp-loop-return">
            <span>↻</span> and the plan rewrites for the next climb
          </li>
        </ol>
      </section>

      {/* Closing CTA */}
      <section className="bp-close">
        <h2 className="bp-close-title">Find out your number.</h2>
        <p className="bp-close-sub">Three minutes to set a target. From there, the agents take the load.</p>
        <button className="bp-btn bp-btn-amber bp-btn-lg" onClick={startClimbing}>Start climbing →</button>
      </section>

      {/* Footer with real system status */}
      <footer className="bp-footer">
        <span className="bp-footer-brand"><span className="bp-mark">◈</span> Atelier Learning · © 2026</span>
        <span className="bp-status">
          <span className={`bp-status-dot ${online ? 'ok' : online === false ? 'down' : ''}`} />
          {online == null ? 'checking system…' : online ? 'system online' : 'system unreachable'}
          {version && <span className="bp-status-ver"> · {version}</span>}
        </span>
      </footer>
    </div>
  )
}

// ── Scoped styles ─────────────────────────────────────────────────────────────

const BP_STYLES = `
.bp-root {
  /* Mapped to the app's theme tokens so the landing matches what you see after
     login — warm cream in light mode, ink-blue instrument in dark mode. */
  --bp-ground:var(--paper-0); --bp-panel:var(--paper-1); --bp-panel-2:var(--paper-2);
  --bp-line:var(--line-2); --bp-line-soft:var(--line-1);
  --bp-ivory:var(--ink-0); --bp-muted:var(--ink-2); --bp-faint:var(--ink-3);
  --bp-amber:var(--signal); --bp-amber-dim:var(--signal-hover); --bp-teal:var(--info);
  --bp-sans:'Geist',system-ui,sans-serif;
  --bp-display:'Space Grotesk','Geist',sans-serif;
  --bp-mono:'Geist Mono',ui-monospace,monospace;
  min-height:100%; background:var(--bp-ground); color:var(--bp-ivory);
  font-family:var(--bp-sans); overflow-x:hidden;
  background-image:
    radial-gradient(1100px 520px at 78% -8%, color-mix(in srgb, var(--signal) 9%, transparent), transparent 60%),
    radial-gradient(900px 500px at 8% 8%, color-mix(in srgb, var(--info) 7%, transparent), transparent 55%);
}
.bp-root ::selection { background:color-mix(in srgb, var(--signal) 26%, transparent); color:var(--bp-ivory); }
.bp-root a { cursor:pointer; }
.bp-amber-text { color:var(--bp-amber); }
.bp-teal-text { color:var(--bp-teal); }
.bp-muted-num { color:var(--bp-faint); }

/* Buttons */
.bp-btn {
  display:inline-flex; align-items:center; justify-content:center; gap:8px;
  font-family:var(--bp-sans); font-size:13px; font-weight:600; line-height:1;
  height:34px; padding:0 15px; border-radius:7px; border:1px solid transparent;
  cursor:pointer; white-space:nowrap;
  transition:transform .12s ease, background .16s ease, border-color .16s ease, color .16s ease;
}
.bp-btn:active { transform:scale(0.97); }
.bp-btn-lg { height:44px; padding:0 22px; font-size:14px; border-radius:8px; }
.bp-btn-amber { background:var(--signal-btn); color:var(--on-signal); border-color:var(--signal-btn); }
.bp-btn-amber:hover { background:var(--signal-btn-hover); border-color:var(--signal-btn-hover); box-shadow:0 6px 22px color-mix(in srgb, var(--signal) 30%, transparent); }
.bp-btn-amber:disabled { opacity:.6; cursor:default; }
.bp-btn-outline { background:transparent; color:var(--bp-ivory); border-color:var(--bp-line); }
.bp-btn-outline:hover { border-color:var(--bp-amber); color:var(--bp-amber); }
.bp-btn-ghost { background:transparent; color:var(--bp-muted); }
.bp-btn-ghost:hover { color:var(--bp-ivory); }
.bp-btn:focus-visible { outline:none; box-shadow:0 0 0 2px var(--bp-ground), 0 0 0 4px var(--bp-amber); }

/* Nav */
.bp-nav {
  position:sticky; top:0; z-index:20;
  background:color-mix(in srgb, var(--paper-0) 85%, transparent); backdrop-filter:blur(10px);
  border-bottom:1px solid var(--bp-line-soft);
}
.bp-nav-inner {
  max-width:1180px; margin:0 auto; padding:14px 32px;
  display:flex; align-items:center; gap:28px;
}
.bp-brand { display:flex; align-items:center; gap:9px; }
.bp-mark { color:var(--bp-amber); font-size:15px; }
.bp-brand-name { font-family:var(--bp-display); font-weight:600; font-size:16px; letter-spacing:-0.01em; }
.bp-nav-links { flex:1; display:flex; gap:24px; }
.bp-nav-links a { font-size:13px; color:var(--bp-muted); transition:color .15s ease; }
.bp-nav-links a:hover { color:var(--bp-ivory); }
.bp-nav-cta { display:flex; gap:10px; align-items:center; }

/* Hero */
.bp-hero {
  max-width:1180px; margin:0 auto; padding:76px 32px 64px;
  display:grid; grid-template-columns:1.05fr 0.95fr; gap:56px; align-items:center;
}
.bp-eyebrow {
  display:inline-flex; align-items:center; gap:9px;
  font-family:var(--bp-mono); font-size:11px; letter-spacing:0.16em; text-transform:uppercase;
  color:var(--bp-teal); margin-bottom:24px;
}
.bp-eyebrow-tick { width:20px; height:1px; background:var(--bp-teal); display:inline-block; }
.bp-headline {
  font-family:var(--bp-display); font-weight:600;
  font-size:clamp(46px,6.4vw,84px); line-height:0.98; letter-spacing:-0.03em;
  margin:0; color:var(--bp-ivory);
}
.bp-lede {
  max-width:490px; margin:26px 0 0; color:var(--bp-muted);
  font-size:16px; line-height:1.62;
}
.bp-hero-actions { display:flex; gap:12px; margin-top:30px; flex-wrap:wrap; }
.bp-hero-facts {
  display:flex; align-items:center; gap:12px; margin-top:26px;
  font-family:var(--bp-mono); font-size:12px; color:var(--bp-faint); flex-wrap:wrap;
}
.bp-hero-facts b { color:var(--bp-ivory); font-weight:500; }
.bp-dot { color:var(--bp-line); }

/* Readout (signature) */
.bp-readout {
  background:linear-gradient(180deg, var(--bp-panel), var(--bp-panel-2));
  border:1px solid var(--bp-line); border-radius:16px; overflow:hidden;
  box-shadow:var(--shadow-3);
}
.bp-readout-head {
  display:flex; align-items:center; justify-content:space-between;
  padding:13px 18px; border-bottom:1px solid var(--bp-line-soft); background:var(--bp-panel-2);
}
.bp-readout-tag { font-family:var(--bp-mono); font-size:11px; letter-spacing:0.16em; color:var(--bp-muted); }
.bp-readout-live { display:inline-flex; align-items:center; gap:6px; font-family:var(--bp-mono); font-size:11px; color:var(--bp-teal); }
.bp-live-dot { width:6px; height:6px; border-radius:50%; background:var(--bp-teal); animation:bpPulse 2s ease-out infinite; }
@keyframes bpPulse { 0%{box-shadow:0 0 0 0 color-mix(in srgb, var(--info) 50%, transparent);} 70%{box-shadow:0 0 0 7px transparent;} 100%{box-shadow:0 0 0 0 transparent;} }
.bp-readout-body { padding:22px 20px 20px; }
.bp-readout-cols { display:flex; align-items:flex-end; justify-content:space-between; gap:14px; }
.bp-col { display:flex; flex-direction:column; gap:5px; }
.bp-col-label { font-family:var(--bp-mono); font-size:10px; letter-spacing:0.16em; color:var(--bp-faint); }
.bp-col-value { font-family:var(--bp-display); font-weight:600; font-size:52px; line-height:1; letter-spacing:-0.02em; font-variant-numeric:tabular-nums; }
.bp-col-note { font-size:11px; color:var(--bp-muted); }
.bp-col-arrow { font-size:22px; color:var(--bp-faint); padding-bottom:16px; }

.bp-ladder { margin:22px 0 20px; display:flex; flex-direction:column; gap:5px; }
.bp-rung-row { display:flex; align-items:center; gap:10px; height:11px; }
.bp-rung-tick { font-family:var(--bp-mono); font-size:9px; color:var(--bp-faint); width:30px; text-align:right; }
.bp-rung { flex:1; height:2px; border-radius:2px; background:var(--bp-line); transition:background .4s ease; }
.bp-rung-lit { background:linear-gradient(90deg, var(--bp-amber-dim), var(--bp-amber)); }
.bp-marker { font-family:var(--bp-mono); font-size:10px; color:var(--bp-amber); white-space:nowrap; }

.bp-role { display:block; margin-top:4px; }
.bp-role-label { display:block; font-family:var(--bp-mono); font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--bp-faint); margin-bottom:7px; }
.bp-select-wrap { position:relative; }
.bp-select {
  width:100%; appearance:none; font-family:var(--bp-sans); font-size:14px; font-weight:500;
  color:var(--bp-ivory); background:var(--bp-panel-2); border:1px solid var(--bp-line);
  border-radius:8px; padding:11px 34px 11px 13px; cursor:pointer; transition:border-color .15s ease;
}
.bp-select:hover { border-color:var(--bp-faint); }
.bp-select:focus-visible { outline:none; border-color:var(--bp-amber); box-shadow:0 0 0 3px color-mix(in srgb, var(--signal) 20%, transparent); }
.bp-select option { background:var(--paper-0); color:var(--bp-ivory); }
.bp-select-caret { position:absolute; right:13px; top:50%; transform:translateY(-50%); color:var(--bp-muted); pointer-events:none; font-size:11px; }
.bp-readout-foot { margin:12px 0 0; font-size:12px; color:var(--bp-muted); line-height:1.5; }
.bp-readout-foot b { color:var(--bp-ivory); font-weight:500; }

/* Sections */
.bp-section { max-width:1180px; margin:0 auto; padding:72px 32px; border-top:1px solid var(--bp-line-soft); }
.bp-section-head { max-width:620px; margin-bottom:40px; }
.bp-section-tag { font-family:var(--bp-mono); font-size:12px; letter-spacing:0.05em; }
.bp-section-title { font-family:var(--bp-display); font-weight:600; font-size:clamp(30px,3.6vw,44px); line-height:1.02; letter-spacing:-0.025em; margin:14px 0 0; }
.bp-section-lede { margin:14px 0 0; color:var(--bp-muted); font-size:15px; line-height:1.6; }

/* Agent rack */
.bp-rack { display:grid; grid-template-columns:repeat(3,1fr); gap:1px; background:var(--bp-line-soft); border:1px solid var(--bp-line-soft); border-radius:14px; overflow:hidden; }
.bp-agent { background:var(--bp-ground); padding:24px 22px; transition:background .18s ease; }
.bp-agent:hover { background:var(--bp-panel); }
.bp-agent-sign { font-family:var(--bp-mono); font-size:11px; letter-spacing:0.12em; color:var(--bp-teal); padding:3px 8px; border:1px solid var(--bp-line); border-radius:5px; display:inline-block; }
.bp-agent-name { font-family:var(--bp-display); font-weight:500; font-size:18px; margin-top:16px; letter-spacing:-0.01em; }
.bp-agent-duty { margin:8px 0 0; color:var(--bp-muted); font-size:13.5px; line-height:1.58; }

/* Loop */
.bp-section-loop { border-top:1px solid var(--bp-line-soft); }
.bp-loop { list-style:none; margin:0; padding:0; display:grid; grid-template-columns:repeat(5,1fr); gap:0; border:1px solid var(--bp-line-soft); border-radius:14px; overflow:hidden; }
.bp-loop-step { padding:26px 20px; border-right:1px solid var(--bp-line-soft); background:var(--bp-ground); }
.bp-loop-step:last-of-type { border-right:none; }
.bp-loop-num { font-family:var(--bp-mono); font-size:12px; color:var(--bp-amber); }
.bp-loop-k { font-family:var(--bp-display); font-weight:600; font-size:19px; margin-top:14px; letter-spacing:-0.01em; }
.bp-loop-d { margin:8px 0 0; color:var(--bp-muted); font-size:13px; line-height:1.55; }
.bp-loop-return { grid-column:1 / -1; border-top:1px solid var(--bp-line-soft); padding:14px 20px; font-family:var(--bp-mono); font-size:12px; color:var(--bp-faint); display:flex; align-items:center; gap:10px; }
.bp-loop-return span { color:var(--bp-amber); font-size:16px; }

/* Close */
.bp-close { max-width:1180px; margin:0 auto; padding:88px 32px 96px; text-align:center; border-top:1px solid var(--bp-line-soft); }
.bp-close-title { font-family:var(--bp-display); font-weight:600; font-size:clamp(34px,4.5vw,56px); letter-spacing:-0.03em; margin:0; }
.bp-close-sub { color:var(--bp-muted); font-size:16px; margin:16px 0 30px; }

/* Footer */
.bp-footer { max-width:1180px; margin:0 auto; padding:26px 32px 48px; display:flex; align-items:center; justify-content:space-between; border-top:1px solid var(--bp-line-soft); flex-wrap:wrap; gap:12px; }
.bp-footer-brand { font-size:13px; color:var(--bp-muted); display:inline-flex; align-items:center; gap:8px; }
.bp-status { display:inline-flex; align-items:center; gap:8px; font-family:var(--bp-mono); font-size:11px; color:var(--bp-muted); }
.bp-status-dot { width:7px; height:7px; border-radius:50%; background:var(--bp-faint); }
.bp-status-dot.ok { background:var(--bp-teal); box-shadow:0 0 8px color-mix(in srgb, var(--info) 55%, transparent); }
.bp-status-dot.down { background:var(--neg); }
.bp-status-ver { color:var(--bp-faint); }

/* Auth modal */
.bp-backdrop { position:fixed; inset:0; z-index:100; background:rgba(6,10,15,0.62); backdrop-filter:blur(5px); display:flex; align-items:center; justify-content:center; padding:16px; }
.bp-modal { width:100%; max-width:410px; background:var(--bp-panel); border:1px solid var(--bp-line); border-radius:14px; overflow:hidden; box-shadow:0 40px 90px -20px rgba(0,0,0,0.8); }
.bp-modal-tabs { display:flex; border-bottom:1px solid var(--bp-line-soft); }
.bp-tab { flex:1; padding:14px 12px; font-family:var(--bp-sans); font-size:13px; color:var(--bp-muted); background:transparent; border:0; border-bottom:2px solid transparent; cursor:pointer; transition:color .15s ease, border-color .15s ease; }
.bp-tab[data-active="true"] { color:var(--bp-ivory); border-bottom-color:var(--bp-amber); font-weight:600; }
.bp-tab-close { flex:0 0 auto; width:46px; color:var(--bp-faint); }
.bp-tab-close:hover { color:var(--bp-ivory); }
.bp-form { padding:24px; display:flex; flex-direction:column; gap:15px; }
.bp-modal-title { font-family:var(--bp-display); font-weight:600; font-size:23px; margin:0 0 4px; letter-spacing:-0.02em; color:var(--bp-ivory); }
.bp-modal-sub { margin:0; font-size:13px; color:var(--bp-muted); line-height:1.5; }
.bp-field { display:block; }
.bp-label { font-family:var(--bp-mono); font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--bp-faint); }
.bp-label-row { display:flex; align-items:baseline; justify-content:space-between; }
.bp-input { display:block; width:100%; margin-top:6px; padding:10px 12px; font-size:14px; font-family:var(--bp-sans); background:var(--bp-panel-2); border:1px solid var(--bp-line); border-radius:7px; color:var(--bp-ivory); outline:none; box-sizing:border-box; transition:border-color .15s ease; }
.bp-input::placeholder { color:var(--bp-faint); }
.bp-input:focus { border-color:var(--bp-amber); }
.bp-input-wrap { position:relative; display:block; margin-top:6px; }
.bp-input-wrap .bp-input { margin-top:0; padding-right:52px; }
.bp-reveal { position:absolute; right:10px; top:50%; transform:translateY(-50%); font-family:var(--bp-mono); font-size:11px; color:var(--bp-faint); background:none; border:0; cursor:pointer; }
.bp-reveal:hover { color:var(--bp-ivory); }
.bp-link-btn { font-size:11px; color:var(--bp-faint); background:none; border:0; cursor:pointer; font-family:var(--bp-sans); padding:0; }
.bp-link-btn:hover { color:var(--bp-amber); }
.bp-link-inline { color:var(--bp-amber); background:none; border:0; cursor:pointer; font-family:inherit; font-size:inherit; padding:0; }
.bp-modal-foot { text-align:center; font-size:12px; color:var(--bp-faint); margin:4px 0 0; }

@media (max-width:900px) {
  .bp-hero { grid-template-columns:1fr; gap:40px; padding-top:56px; }
  .bp-rack { grid-template-columns:1fr 1fr; }
  .bp-loop { grid-template-columns:1fr 1fr; }
  .bp-loop-step { border-right:1px solid var(--bp-line-soft); border-bottom:1px solid var(--bp-line-soft); }
}
@media (max-width:560px) {
  .bp-nav-links { display:none; }
  .bp-hero { padding:40px 22px 48px; }
  .bp-section, .bp-close { padding-left:22px; padding-right:22px; }
  .bp-rack, .bp-loop { grid-template-columns:1fr; }
  .bp-footer { padding-left:22px; padding-right:22px; }
}
@media (prefers-reduced-motion:reduce) {
  .bp-live-dot { animation:none; }
  .bp-btn:active { transform:none; }
}
`
