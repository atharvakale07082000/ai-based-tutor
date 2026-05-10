import { useState } from 'react'
import { useLearnerStore } from '@/stores/learnerStore'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Tabs } from '@/components/ui/Tabs'
import { Icon } from '@/components/ui/Icon'

const HEATMAP_DAYS = Array.from({ length: 35 }, () => ({
  active: Math.random() > 0.38,
  intensity: Math.floor(Math.random() * 4) + 1,
}))

export default function ProgressPage() {
  const [period, setPeriod] = useState('month')
  const { xp, streak, topicProficiency } = useLearnerStore()

  const skills = Object.entries(topicProficiency).length > 0
    ? Object.entries(topicProficiency).map(([k, v]) => ({ k, v: v / 1000 }))
    : [
        { k: 'Python',        v: 0.78 },
        { k: 'SQL',           v: 0.71 },
        { k: 'Statistics',    v: 0.62 },
        { k: 'Probability',   v: 0.58 },
        { k: 'Linear Algebra',v: 0.55 },
        { k: 'ML Theory',     v: 0.48 },
        { k: 'Calculus',      v: 0.41 },
        { k: 'Deep Learning', v: 0.34 },
      ]

  return (
    <div style={{ padding: '24px 28px', maxWidth: 1240, margin: '0 auto' }}>
      <div style={{ marginBottom: 18, display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <div>
          <div className="caps fg-3">Last 30 days</div>
          <h1 className="serif" style={{ fontSize: 36, fontWeight: 400, margin: 0, letterSpacing: '-0.02em' }}>Progress</h1>
        </div>
        <Tabs variant="segmented" value={period} onChange={setPeriod} tabs={[
          { value: 'week', label: 'Week' }, { value: 'month', label: 'Month' }, { value: 'all', label: 'All time' },
        ]} />
      </div>

      {/* Stat strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', overflow: 'hidden', background: 'var(--paper-1)', marginBottom: 16 }}>
        {[
          { l: 'XP earned',  v: xp.toLocaleString(), s: '+18%',        t: 'pos' },
          { l: 'Modules',    v: '32',                 s: '+6',           t: 'pos' },
          { l: 'Quizzes',    v: '14',                 s: '88% avg',      t: 'neutral' },
          { l: 'Doubts',     v: '38',                 s: 'all resolved', t: 'pos' },
          { l: 'Time',       v: '42h',                s: '6h/wk',        t: 'neutral' },
          { l: 'Mastery',    v: '48%',                s: '+4 pts',       t: 'pos' },
        ].map((s, i) => (
          <div key={i} style={{ padding: 14, borderRight: i < 5 ? '1px solid var(--line-1)' : 'none' }}>
            <div className="caps fg-2">{s.l}</div>
            <div className="serif" style={{ fontSize: 26, color: 'var(--ink-0)', marginTop: 2 }}>{s.v}</div>
            <div className="t-xs" style={{ color: s.t === 'pos' ? 'var(--pos)' : 'var(--ink-3)' }}>{s.s}</div>
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr', gap: 14 }}>
        {/* Skill mastery */}
        <Card padding="md">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <span className="caps fg-2">Skill mastery · {skills.length} sub-skills</span>
            <Tabs variant="segmented" value="proficiency" onChange={() => {}} tabs={[
              { value: 'proficiency', label: 'Proficiency' },
              { value: 'velocity',    label: 'Velocity' },
            ]} />
          </div>
          {skills.map((s, i) => (
            <div key={i} style={{ padding: '8px 0', borderTop: i ? '1px solid var(--line-1)' : 'none', display: 'grid', gridTemplateColumns: '120px 1fr 50px 60px', gap: 12, alignItems: 'center' }}>
              <span className="t-sm fg-0" style={{ fontWeight: 500 }}>{s.k}</span>
              <div style={{ height: 6, background: 'var(--paper-3)', borderRadius: 'var(--r-pill)', overflow: 'hidden' }}>
                <div style={{ width: `${s.v * 100}%`, height: '100%', background: 'var(--ink-0)', borderRadius: 'var(--r-pill)' }} />
              </div>
              <span className="t-sm fg-0 mono" style={{ textAlign: 'right' }}>{Math.round(s.v * 100)}</span>
              <Badge size="xs" tone={s.v > 0.6 ? 'pos' : s.v > 0.4 ? 'neutral' : 'warn'}>
                {s.v > 0.6 ? 'strong' : s.v > 0.4 ? 'mid' : 'needs work'}
              </Badge>
            </div>
          ))}
        </Card>

        {/* Right column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* Streak calendar */}
          <Card padding="md">
            <div className="caps fg-2" style={{ marginBottom: 8 }}>Streak calendar</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 4 }}>
              {HEATMAP_DAYS.map((d, i) => (
                <div key={i} style={{
                  aspectRatio: '1',
                  borderRadius: 4,
                  background: d.active ? `color-mix(in srgb, var(--accent) ${d.intensity * 20}%, var(--paper-3))` : 'var(--paper-2)',
                  border: '1px solid var(--line-1)',
                }} />
              ))}
            </div>
            <div className="t-xs fg-3" style={{ marginTop: 8 }}>{streak}-day streak</div>
          </Card>

          {/* Insights */}
          <Card padding="md">
            <div className="caps fg-2" style={{ marginBottom: 6 }}>Insights · this week</div>
            {[
              { i: 'arrowUR', t: 'Deep Learning velocity is up 12 pts', tone: 'pos' },
              { i: 'arrowDR', t: 'Calculus retention dipped 3 pts',     tone: 'neg' },
              { i: 'sparkle', t: 'Quiz agent suggests revisiting derivatives', tone: 'accent' },
            ].map((s, i) => (
              <div key={i} style={{ padding: '6px 0', borderTop: i ? '1px solid var(--line-1)' : 'none', display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                <Icon name={s.i} size={12} style={{ marginTop: 2, color: s.tone === 'pos' ? 'var(--pos)' : s.tone === 'neg' ? 'var(--neg)' : 'var(--accent)' }} />
                <span className="t-sm fg-1" style={{ flex: 1 }}>{s.t}</span>
              </div>
            ))}
          </Card>

          {/* Time chart (mini bars) */}
          <Card padding="md">
            <div className="caps fg-2" style={{ marginBottom: 8 }}>Time invested · this week</div>
            <div style={{ display: 'flex', gap: 6, height: 80, alignItems: 'flex-end' }}>
              {[0.4, 0.7, 0.5, 0.9, 0.3, 0.6, 0.85].map((h, i) => (
                <div key={i} style={{ flex: 1, height: `${h * 100}%`, background: 'var(--ink-0)', borderRadius: '2px 2px 0 0', opacity: 0.5 + h * 0.4 }} />
              ))}
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4, fontSize: 10, color: 'var(--ink-3)' }}>
              {['M', 'T', 'W', 'T', 'F', 'S', 'S'].map((d, i) => <span key={i}>{d}</span>)}
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
