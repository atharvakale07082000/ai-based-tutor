import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import { AgentPill } from '@/components/ui/AgentPill'
import { Icon } from '@/components/ui/Icon'

export default function LandingPage() {
  const navigate = useNavigate()

  return (
    <div style={{ minHeight: '100%', background: 'var(--paper-0)', overflow: 'auto' }}>
      {/* Nav */}
      <nav style={{ position: 'sticky', top: 0, zIndex: 10, background: 'rgba(250,248,242,0.9)', backdropFilter: 'blur(8px)', borderBottom: '1px solid var(--line-1)' }}>
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
          <Button size="sm" variant="ghost" onClick={() => navigate('/onboarding')}>Sign in</Button>
          <Button size="sm" variant="primary" onClick={() => navigate('/onboarding')}>Get started</Button>
        </div>
      </nav>

      {/* Hero */}
      <section style={{ maxWidth: 1100, margin: '0 auto', padding: '72px 32px 56px' }}>
        <div className="caps" style={{ color: 'var(--accent)', marginBottom: 16 }}>Adaptive AI tutoring · Beta 0429</div>
        <h1 className="serif" style={{ fontSize: 'clamp(44px,6vw,78px)', lineHeight: 0.98, margin: 0, fontWeight: 400, color: 'var(--ink-0)', letterSpacing: '-0.03em', maxWidth: 860 }}>
          A tutor that learns<br />
          <span style={{ fontStyle: 'italic', color: 'var(--accent)' }}>how you learn.</span>
        </h1>
        <p className="t-lg fg-2" style={{ maxWidth: 560, marginTop: 24, lineHeight: 1.65 }}>
          Four specialized agents — Curriculum, Quiz, Progress, and Doubt-Solver — collaborate to plan your week, generate questions on demand, track every concept, and answer your questions with full context.
        </p>
        <div style={{ marginTop: 28, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <Button size="lg" variant="primary" iconRight="arrow" onClick={() => navigate('/onboarding')} >
            Start your first lesson
          </Button>
          <Button size="lg" variant="ghost" icon="play">Watch a 90s tour</Button>
          <span className="t-sm fg-3" style={{ marginLeft: 4 }}>Free · no card · 3-minute setup</span>
        </div>

        {/* Agents row */}
        <div style={{ marginTop: 48, padding: 16, background: 'var(--paper-1)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)' }}>
          <div className="caps" style={{ color: 'var(--ink-3)', marginBottom: 10 }}>Agents on call</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16 }}>
            {([
              { kind: 'curr',  name: 'Curriculum Planner', desc: 'Sketches your week, adapts on Sunday.' },
              { kind: 'quiz',  name: 'Quiz Generator',     desc: 'Spawns questions calibrated to your retention.' },
              { kind: 'prog',  name: 'Progress Tracker',   desc: 'Tracks 32 sub-skills. Surfaces gaps.' },
              { kind: 'doubt', name: 'Doubt-Solver',       desc: 'Cites your own materials when answering.' },
            ] as const).map((a) => (
              <div key={a.kind}>
                <AgentPill kind={a.kind} state="active" />
                <div className="t-md fg-0" style={{ fontWeight: 500, marginTop: 8 }}>{a.name}</div>
                <div className="t-sm fg-2" style={{ marginTop: 2 }}>{a.desc}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* App preview */}
      <section style={{ maxWidth: 1100, margin: '0 auto', padding: '0 32px 80px' }}>
        <div style={{ border: '1px solid var(--line-2)', borderRadius: 'var(--r-4)', overflow: 'hidden', boxShadow: 'var(--shadow-3)' }}>
          <div style={{ padding: '8px 12px', background: 'var(--paper-1)', borderBottom: '1px solid var(--line-1)', display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ display: 'flex', gap: 5 }}>
              {[0, 1, 2].map((i) => <span key={i} style={{ width: 9, height: 9, borderRadius: '50%', background: 'var(--line-2)' }} />)}
            </div>
            <span className="t-xs fg-3 mono">atelier.app/dashboard</span>
          </div>
          <div style={{ padding: 24, display: 'grid', gridTemplateColumns: '160px 1fr 220px', gap: 20, minHeight: 320, background: 'var(--paper-0)' }}>
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
                <div className="serif" style={{ fontSize: 28, color: 'var(--ink-0)', marginTop: 4 }}>12 <span className="t-xs fg-3" style={{ fontSize: 12 }}>days</span></div>
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
          <span className="t-sm fg-3">© 2026 Atelier Learning · Original design system</span>
          <div style={{ display: 'flex', gap: 12 }}>
            {['Privacy', 'Terms', 'Status'].map((l) => <a key={l} className="t-sm fg-2" style={{ cursor: 'pointer' }}>{l}</a>)}
          </div>
        </div>
      </footer>
    </div>
  )
}
