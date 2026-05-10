import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { learnerAPI } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'
import { useLearnerStore } from '@/stores/learnerStore'

const GOAL_OPTIONS = ['Machine Learning', 'Statistics', 'Python', 'Linear Algebra', 'Deep Learning', 'SQL', 'Probability', 'Calculus', 'Data Engineering']

export default function OnboardingPage() {
  const navigate = useNavigate()
  const setLearner = useLearnerStore((s) => s.setLearner)
  const [step, setStep] = useState(1)
  const [name, setNameLocal] = useState('Mira')
  const [goals, setGoals] = useState(['Machine Learning'])
  const [hours, setHours] = useState(6)
  const [diff, setDiff] = useState<'gentle' | 'balanced' | 'aggressive'>('balanced')
  const [loading, setLoading] = useState(false)

  const toggleGoal = (g: string) => setGoals(goals.includes(g) ? goals.filter((x) => x !== g) : [...goals, g])

  const handleComplete = async () => {
    setLoading(true)
    try {
      const { data } = await learnerAPI.onboard({ name: name.trim(), goals, hoursPerWeek: hours, difficulty: diff })
      setLearner({ name: data.name ?? name })
      navigate('/dashboard')
    } catch {
      toast.error('Could not save preferences')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ minHeight: '100%', display: 'grid', gridTemplateColumns: '1fr 1fr', background: 'var(--paper-0)' }}>
      {/* LEFT */}
      <div style={{ padding: '64px 56px', borderRight: '1px solid var(--line-1)', background: 'var(--paper-1)', display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 48 }}>
          <div style={{ width: 22, height: 22, borderRadius: 5, background: 'var(--ink-0)', color: 'var(--paper-0)', display: 'grid', placeItems: 'center', fontFamily: 'var(--font-serif)', fontSize: 13, fontStyle: 'italic' }}>æ</div>
          <span className="t-md fg-0" style={{ fontWeight: 600 }}>Atelier</span>
        </div>

        <div className="caps" style={{ color: 'var(--accent)', marginBottom: 12 }}>Step {step} of 4</div>
        <h1 className="serif" style={{ fontSize: 'clamp(32px,4vw,48px)', lineHeight: 1.05, fontWeight: 400, color: 'var(--ink-0)', margin: 0, letterSpacing: '-0.025em' }}>
          {step === 1 && <>Tell us your name.<br /><span style={{ fontStyle: 'italic', color: 'var(--ink-2)' }}>We'll keep it informal.</span></>}
          {step === 2 && <>What do you want<br /><span style={{ fontStyle: 'italic', color: 'var(--accent)' }}>to learn?</span></>}
          {step === 3 && <>How much time<br /><span style={{ fontStyle: 'italic', color: 'var(--accent)' }}>do you have?</span></>}
          {step === 4 && <>One last thing —<br /><span style={{ fontStyle: 'italic', color: 'var(--accent)' }}>your pace.</span></>}
        </h1>
        <p className="t-lg fg-2" style={{ marginTop: 20, maxWidth: 420, lineHeight: 1.65 }}>
          {step === 1 && 'Your tutor calls you by name. Choose anything you like — change it later.'}
          {step === 2 && 'Pick three to seven topics. The Curriculum agent will weave a plan around them.'}
          {step === 3 && 'We pace your modules to fit. You can always do more.'}
          {step === 4 && "How aggressive should we be when you're ready for harder material?"}
        </p>

        <div style={{ marginTop: 'auto', paddingTop: 40 }}>
          <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
            {[1, 2, 3, 4].map((s) => (
              <div key={s} style={{ flex: 1, height: 3, borderRadius: 2, background: s <= step ? 'var(--ink-0)' : 'var(--paper-3)', transition: 'background var(--dur-base)' }} />
            ))}
          </div>
          <div className="t-xs fg-3">~{Math.max(60 - step * 15, 15)} seconds remaining</div>
        </div>
      </div>

      {/* RIGHT */}
      <div style={{ padding: '64px 56px', display: 'flex', flexDirection: 'column' }}>
        <div style={{ flex: 1, maxWidth: 480 }}>
          {step === 1 && (
            <div>
              <label className="caps" style={{ color: 'var(--ink-2)' }}>Display name</label>
              <input
                value={name}
                onChange={(e) => setNameLocal(e.target.value)}
                autoFocus
                style={{ width: '100%', marginTop: 8, padding: '10px 0', fontSize: 28, fontFamily: 'var(--font-serif)', background: 'transparent', border: 0, borderBottom: '1px solid var(--line-2)', color: 'var(--ink-0)', outline: 'none' }}
              />
              <div className="t-xs fg-3" style={{ marginTop: 8 }}>3–24 characters</div>
            </div>
          )}

          {step === 2 && (
            <div>
              <label className="caps" style={{ color: 'var(--ink-2)' }}>Topics — pick 3 to 7</label>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 12 }}>
                {GOAL_OPTIONS.map((g) => {
                  const active = goals.includes(g)
                  return (
                    <button
                      key={g}
                      onClick={() => toggleGoal(g)}
                      style={{
                        padding: '6px 12px', fontSize: 13, fontWeight: 500, cursor: 'pointer',
                        background: active ? 'var(--ink-0)' : 'var(--paper-1)',
                        color: active ? 'var(--paper-0)' : 'var(--ink-1)',
                        border: `1px solid ${active ? 'var(--ink-0)' : 'var(--line-2)'}`,
                        borderRadius: 'var(--r-pill)',
                        fontFamily: 'inherit',
                        transition: 'background var(--dur-fast)',
                      }}
                    >{g}</button>
                  )
                })}
              </div>
              <div style={{ marginTop: 20, padding: 12, background: 'var(--accent-soft)', borderRadius: 'var(--r-2)', display: 'flex', gap: 8 }}>
                <Icon name="sparkle" size={14} style={{ color: 'var(--accent)', marginTop: 2, flexShrink: 0 }} />
                <div>
                  <div style={{ color: 'var(--accent)', fontWeight: 500, fontSize: 13 }}>Curriculum agent says</div>
                  <div className="t-sm fg-1" style={{ marginTop: 2 }}>Most learners pair Machine Learning with Linear Algebra and Statistics.</div>
                </div>
              </div>
            </div>
          )}

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
              <div style={{ marginTop: 28, padding: 14, background: 'var(--paper-1)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-2)' }}>
                <div className="t-sm fg-2">At {hours}h/week, your plan covers</div>
                <div className="t-md fg-0" style={{ marginTop: 4, fontWeight: 500 }}>{Math.round(hours * 4 * 0.6)} modules over 8 weeks</div>
              </div>
            </div>
          )}

          {step === 4 && (
            <div>
              <label className="caps" style={{ color: 'var(--ink-2)' }}>Difficulty pacing</label>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12 }}>
                {([
                  { v: 'gentle',     t: 'Gentle',     d: 'Build deep mastery before advancing.' },
                  { v: 'balanced',   t: 'Balanced',   d: "Push when you're ready, ease when you slip." },
                  { v: 'aggressive', t: 'Aggressive', d: 'Always one step ahead. Comfortable with friction.' },
                ] as const).map((o) => {
                  const active = diff === o.v
                  return (
                    <button
                      key={o.v}
                      onClick={() => setDiff(o.v)}
                      style={{
                        padding: 14, textAlign: 'left', cursor: 'pointer', fontFamily: 'inherit',
                        border: `1px solid ${active ? 'var(--ink-0)' : 'var(--line-1)'}`,
                        background: active ? 'var(--paper-2)' : 'var(--paper-1)',
                        borderRadius: 'var(--r-3)', display: 'flex', alignItems: 'center', gap: 12,
                      }}
                    >
                      <div style={{ width: 16, height: 16, borderRadius: '50%', border: `1.5px solid ${active ? 'var(--ink-0)' : 'var(--line-2)'}`, display: 'grid', placeItems: 'center', flexShrink: 0 }}>
                        {active && <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--ink-0)' }} />}
                      </div>
                      <div>
                        <div className="t-md fg-0" style={{ fontWeight: 500 }}>{o.t}</div>
                        <div className="t-sm fg-2">{o.d}</div>
                      </div>
                    </button>
                  )
                })}
              </div>
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: 8, marginTop: 32, paddingTop: 20, borderTop: '1px solid var(--line-1)' }}>
          <Button variant="ghost" onClick={() => setStep(Math.max(1, step - 1))} disabled={step === 1}>Back</Button>
          <span style={{ flex: 1 }} />
          <Button variant="ghost" onClick={() => step < 4 ? setStep(step + 1) : handleComplete()}>Skip</Button>
          <Button
            variant="primary"
            iconRight={step < 4 ? 'arrow' : 'check'}
            onClick={() => step < 4 ? setStep(step + 1) : handleComplete()}
            loading={loading}
          >
            {step < 4 ? 'Continue' : 'Build my plan'}
          </Button>
        </div>
      </div>
    </div>
  )
}
