import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import toast from 'react-hot-toast'
import { contentAPI, doubtsAPI, quizAPI, progressAPI, leaderboardAPI, learnerAPI } from '@/lib/api'
import { useLearnerStore } from '@/stores/learnerStore'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'
import { ValueBar } from '@/components/ui/Progress'
import { EmptyState } from '@/components/ui/EmptyState'

function Stat({ label, value, change, sub, icon }: { label: string; value: string; change?: string; sub?: string; icon?: string }) {
  return (
    <div style={{ flex: 1, padding: 14, background: 'var(--paper-1)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <span className="caps" style={{ color: 'var(--ink-2)' }}>{label}</span>
        {icon && <Icon name={icon} size={12} style={{ color: 'var(--ink-3)' }} />}
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
        <span className="serif" style={{ fontSize: 28, color: 'var(--ink-0)', letterSpacing: '-0.02em' }}>{value}</span>
        {change && <span className="t-xs" style={{ color: change.startsWith('+') ? 'var(--pos)' : 'var(--neg)', fontWeight: 500 }}>{change}</span>}
      </div>
      {sub && <div className="t-xs fg-3" style={{ marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

function SkillBar({ name, value }: { name: string; value: number }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0' }}>
      <span className="t-sm fg-1" style={{ width: 110, fontWeight: 500 }}>{name}</span>
      <div style={{ flex: 1, height: 4, background: 'var(--paper-3)', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{ width: `${value * 100}%`, height: '100%', background: 'var(--ink-0)', borderRadius: 2 }} />
      </div>
      <span className="t-xs fg-3 mono" style={{ width: 30, textAlign: 'right' }}>{Math.round(value * 100)}</span>
    </div>
  )
}


export default function DashboardPage() {
  const navigate = useNavigate()
  const { name, xp, streak, topicProficiency } = useLearnerStore()
  const [isGeneratingQuiz, setIsGeneratingQuiz] = useState(false)
  const [loadingModuleId, setLoadingModuleId] = useState<string | null>(null)

  const { data: contentData, isLoading: contentLoading, isError: contentError, refetch: refetchContent } = useQuery({
    queryKey: ['content', 'feed', {}],
    queryFn: () => contentAPI.list({ limit: 6 }).then((r) => r.data),
    staleTime: 1000 * 60 * 2,   // content list: 2 min
    gcTime: 1000 * 60 * 10,
  })

  const { data: sessionsData } = useQuery({
    queryKey: ['doubts', 'sessions'],
    queryFn: () => doubtsAPI.getSessions().then((r) => r.data),
    staleTime: 1000 * 30,        // doubt sessions: 30 s
    gcTime: 1000 * 60 * 5,
  })

  const { data: dueTopicsData } = useQuery({
    queryKey: ['progress', 'due-topics'],
    queryFn: () => progressAPI.dueTopics().then((r) => r.data),
    staleTime: 1000 * 60 * 5,
  })

  const { data: leaderboardData } = useQuery({
    queryKey: ['leaderboard'],
    queryFn: () => leaderboardAPI.get().then((r) => r.data),
    staleTime: 1000 * 60 * 2,
    gcTime: 1000 * 60 * 10,
  })

  const { data: learnerProfile } = useQuery({
    queryKey: ['learner', 'profile'],
    queryFn: () => learnerAPI.getProfile().then((r) => r.data),
    staleTime: 1000 * 60 * 5,
  })

  const handleStartQuiz = async () => {
    setIsGeneratingQuiz(true)
    try {
      const dueTopic = dueTopics[0]?.topic
      const topic = dueTopic ?? Object.keys(topicProficiency)[0] ?? 'Python'
      const { data } = await quizAPI.generate(topic)
      toast.success('Quiz ready — good luck!', { duration: 2000 })
      navigate(`/quiz/${data.quiz_id}`)
    } catch {
      toast.error('Could not generate quiz')
    } finally {
      setIsGeneratingQuiz(false)
    }
  }

  const items = contentData?.items ?? []
  const sessions = sessionsData ?? []
  const dueTopics = (dueTopicsData?.due_topics ?? []).filter((t) => t.is_due).slice(0, 5)
  const board = leaderboardData?.board ?? []
  const yourRank = leaderboardData?.your_rank

  return (
    <div style={{ padding: '24px 28px', maxWidth: 1240, margin: '0 auto' }}>
      {/* Greeting */}
      <div style={{ marginBottom: 20, display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between' }}>
        <div>
          <div className="caps" style={{ color: 'var(--ink-3)', marginBottom: 4 }}>
            {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
          </div>
          <h1 className="serif" style={{ fontSize: 36, fontWeight: 400, margin: 0, color: 'var(--ink-0)', letterSpacing: '-0.02em' }}>
            Good {new Date().getHours() < 12 ? 'morning' : 'afternoon'},{' '}
            <span style={{ fontStyle: 'italic', color: 'var(--accent)' }}>{name || 'Learner'}</span>.
          </h1>
          <p className="t-md fg-2" style={{ marginTop: 4 }}>
            {learnerProfile?.target_role
              ? <>Targeting <strong>{learnerProfile.target_role}</strong> · {streak}-day streak.</>
              : <>You're on a {streak}-day streak. Keep building your readiness.</>}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <Button size="sm" variant="ghost" icon="calendar">Schedule</Button>
          <Button size="sm" variant="accent" icon="sparkle" onClick={() => navigate('/atelier')}>Ask Atelier</Button>
        </div>
      </div>

      {/* Stat row */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
        <Stat
          label="Job Readiness"
          value={learnerProfile?.job_readiness_score != null ? `${Math.round(learnerProfile.job_readiness_score)}%` : `${Math.min(Math.round((Object.keys(topicProficiency).length / 10) * 100), 100)}%`}
          icon="target"
        />
        <Stat label="Streak" value={String(streak)} sub="days · keep going!" icon="flame" />
        <Stat label="XP" value={xp.toLocaleString()} icon="bolt" />
        <Stat label="Coaching sessions" value={String(sessions.length || 0)} sub="total" icon="chat" />
        <Stat label="Skills" value={String(Object.keys(topicProficiency).length)} sub="topics tracked" icon="book" />
      </div>

      {/* Main grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr', gap: 16 }}>
        {/* Column 1 */}
        <div>
          {/* Career next-step card */}
          <Card accent padding="md" style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
              <div style={{ width: 32, height: 32, borderRadius: 'var(--r-2)', background: 'var(--accent)', color: '#fff', display: 'grid', placeItems: 'center', flexShrink: 0 }}>
                <Icon name="sparkle" size={16} />
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span className="caps" style={{ color: 'var(--accent)' }}>
                    {learnerProfile?.target_role ? `${learnerProfile.target_role} Prep` : 'Career Path'}
                  </span>
                  <span className="t-xs fg-3">· today's focus</span>
                </div>
                <div className="t-md fg-0" style={{ fontWeight: 500, marginTop: 4 }}>
                  {dueTopics[0]
                    ? `${dueTopics[0].topic} is due for practice — reviewing it now will lift your readiness score.`
                    : learnerProfile?.target_role
                      ? `Start a mock interview or build a career path for ${learnerProfile.target_role}.`
                      : 'Build your personalised career roadmap to start closing skill gaps.'}
                </div>
                <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                  <Button size="sm" variant="accent" iconRight="arrow" onClick={() => navigate('/courses')}>
                    {learnerProfile?.target_role ? 'Build career path' : 'Plan career path'}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => navigate('/atelier')}>Mock interview</Button>
                </div>
              </div>
            </div>
          </Card>

          {/* Today's feed */}
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 8 }}>
            <span className="caps" style={{ color: 'var(--ink-2)' }}>Today's prep · {items.length} modules</span>
            <a className="t-sm fg-2" style={{ cursor: 'pointer' }} onClick={() => navigate('/learn')}>Career feed →</a>
          </div>

          {contentLoading ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              {[0, 1, 2].map((i) => <div key={i} className="skel" style={{ height: 48, borderRadius: 'var(--r-2)', marginBottom: 1 }} />)}
            </div>
          ) : contentError ? (
            <div style={{ padding: '16px', textAlign: 'center' }}>
              <p className="t-sm fg-2" style={{ marginBottom: 8 }}>Could not load lessons.</p>
              <button onClick={() => refetchContent()} style={{ fontSize: 13, color: 'var(--accent)', background: 'none', border: 0, cursor: 'pointer', fontFamily: 'inherit' }}>Retry →</button>
            </div>
          ) : (
            <Card padding="none">
              {items.slice(0, 5).map((m: any, i: number) => {
                const isOpening = loadingModuleId === m.id
                return (
                  <div
                    key={m.id}
                    style={{ padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 12, borderTop: i ? '1px solid var(--line-1)' : 'none', cursor: 'pointer', transition: 'background 0.1s' }}
                    onClick={() => {
                      setLoadingModuleId(m.id)
                      navigate(`/learn/${m.id}`)
                    }}
                    onMouseEnter={(e) => { if (!isOpening) e.currentTarget.style.background = 'var(--paper-2)' }}
                    onMouseLeave={(e) => { if (!isOpening) e.currentTarget.style.background = 'transparent' }}
                  >
                    <div style={{ width: 28, height: 28, borderRadius: 'var(--r-2)', background: isOpening ? 'color-mix(in srgb, var(--accent) 12%, var(--paper-2))' : 'var(--paper-3)', display: 'grid', placeItems: 'center', transition: 'background 0.2s', flexShrink: 0 }}>
                      {isOpening ? (
                        <Icon name="refresh" size={13} style={{ color: 'var(--accent)', animation: 'spin 0.8s linear infinite' }} />
                      ) : (
                        <Icon name={m.content_type === 'video' ? 'play' : m.content_type === 'exercise' ? 'code' : 'book'} size={13} style={{ color: 'var(--ink-1)' }} />
                      )}
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span className="t-md fg-0" style={{ fontWeight: 500 }}>{m.title}</span>
                        {m.is_ai_recommended && <Badge tone="accent" size="xs">AI Pick</Badge>}
                      </div>
                      <div className="t-xs fg-3" style={{ marginTop: 2 }}>{isOpening ? 'Loading your content…' : `${m.topic} · ${m.estimated_minutes}m`}</div>
                    </div>
                    <ValueBar value={Math.round((m.difficulty ?? 0.5) * 5)} segments={5} />
                    <Icon name={isOpening ? 'chevR' : 'chevR'} size={14} style={{ color: isOpening ? 'var(--accent)' : 'var(--ink-3)' }} />
                  </div>
                )
              })}
              {items.length === 0 && (
                <div className="t-sm fg-3" style={{ padding: '20px 14px', textAlign: 'center' }}>No content yet — building your career path…</div>
              )}
            </Card>
          )}

          {/* Recent coaching sessions */}
          <div style={{ marginTop: 20, display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 8 }}>
            <span className="caps" style={{ color: 'var(--ink-2)' }}>Recent coaching sessions</span>
            <a className="t-sm fg-2" style={{ cursor: 'pointer' }} onClick={() => navigate('/doubts')}>All sessions →</a>
          </div>
          {sessions.length === 0 ? (
            <Card padding="none">
              <EmptyState
                icon="chat"
                title="No coaching sessions yet"
                body="Ask your career coach a question to get started."
                action={{ label: 'Open coach', onClick: () => navigate('/doubts') }}
                size="sm"
              />
            </Card>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 10 }}>
              {sessions.slice(0, 4).map((s: any) => (
                <Card key={s.id} hover padding="sm" style={{ cursor: 'pointer' }} onClick={() => navigate('/doubts')}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                    <Badge size="xs" tone={s.sentiment_mood === 'POSITIVE' ? 'pos' : s.sentiment_mood === 'NEGATIVE' ? 'neg' : 'neutral'} dot>
                      {(s.sentiment_mood ?? 'neutral').toLowerCase()}
                    </Badge>
                    <span className="t-xs fg-3">{new Date(s.started_at).toLocaleDateString()}</span>
                  </div>
                  <div className="t-sm fg-0" style={{ fontWeight: 500, marginBottom: 2 }}>{s.topic_context ?? 'General question'}</div>
                </Card>
              ))}
            </div>
          )}
        </div>

        {/* Column 2 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {/* Skill map */}
          <Card padding="md">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
              <span className="caps" style={{ color: 'var(--ink-2)' }}>Role readiness by skill</span>
              <span className="t-xs fg-3 mono">{Object.keys(topicProficiency).length} tracked</span>
            </div>
            {Object.entries(topicProficiency).slice(0, 6).map(([k, v]) => (
              <SkillBar key={k} name={k.slice(0, 14)} value={v / 1000} />
            ))}
            {Object.keys(topicProficiency).length === 0 && (
              <div className="t-xs fg-3" style={{ textAlign: 'center', padding: 8 }}>
                {learnerProfile?.target_role ? `Complete interviews to build your ${learnerProfile.target_role} readiness map.` : 'Tracking your skills…'}
              </div>
            )}
            <div className="t-xs fg-3" style={{ marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--line-1)', display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--agent-prog)', display: 'inline-block' }} />
              Updated after each interview · <a style={{ color: 'var(--accent)', cursor: 'pointer' }} onClick={() => navigate('/progress')}>View full readiness →</a>
            </div>
          </Card>

          {/* Streak & activity */}
          <Card padding="md">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
              <span className="caps" style={{ color: 'var(--ink-2)' }}>Your streak</span>
              <a className="t-xs fg-2" style={{ cursor: 'pointer' }} onClick={() => navigate('/progress')}>Full activity →</a>
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 6 }}>
              <span className="serif" style={{ fontSize: 40, letterSpacing: '-0.02em', color: streak > 0 ? 'var(--ink-0)' : 'var(--ink-3)' }}>{streak}</span>
              <span className="t-sm fg-2">day{streak !== 1 ? 's' : ''} in a row</span>
            </div>
            {streak > 0 ? (
              <div className="t-xs fg-2" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <Icon name="flame" size={11} style={{ color: 'var(--accent)' }} />
                Keep it going — consistency beats intensity.
              </div>
            ) : (
              <div className="t-xs fg-3">Complete a quiz or study session to start your streak.</div>
            )}
          </Card>

          {/* Due for review */}
          <Card padding="none">
            <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--line-1)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span className="caps" style={{ color: 'var(--ink-2)' }}>Due for review</span>
              <Badge size="xs" tone="warn">{dueTopics.length} due</Badge>
            </div>
            {dueTopics.length > 0 ? dueTopics.map((t, i) => (
              <div key={t.topic} style={{ padding: '8px 14px', display: 'flex', alignItems: 'center', gap: 10, borderTop: i ? '1px solid var(--line-1)' : 'none' }}>
                <div className="t-sm fg-0" style={{ fontWeight: 500, flex: 1 }}>{t.topic}</div>
                <span className="t-xs fg-3 mono">{Math.round(t.elo)} ELO</span>
                <Badge size="xs" tone={t.urgency >= 0.8 ? 'neg' : t.urgency >= 0.5 ? 'warn' : 'outline'}>
                  {t.days_since_last_quiz === null ? 'New' : t.urgency >= 0.8 ? 'Critical gap' : 'Practice due'}
                </Badge>
              </div>
            )) : (
              <div className="t-xs fg-3" style={{ padding: '16px 14px', textAlign: 'center' }}>
                {dueTopicsData ? 'All caught up! No reviews due.' : 'Loading due topics…'}
              </div>
            )}
            <div style={{ padding: 10, borderTop: '1px solid var(--line-1)' }}>
              <Button size="sm" variant="primary" full iconRight="arrow" onClick={handleStartQuiz} loading={isGeneratingQuiz}>
                {dueTopics[0] ? `Practice ${dueTopics[0].topic}` : 'Start skill practice'}
              </Button>
            </div>
          </Card>

          {/* Leaderboard */}
          <Card padding="none">
            <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--line-1)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span className="caps" style={{ color: 'var(--ink-2)' }}>Leaderboard</span>
              {yourRank && <span className="t-xs fg-3">You're #{yourRank}</span>}
            </div>
            {board.slice(0, 5).map((entry, i) => (
              <div
                key={entry.rank}
                style={{
                  padding: '7px 14px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  borderTop: i ? '1px solid var(--line-1)' : 'none',
                  background: entry.is_you ? 'var(--paper-2)' : 'transparent',
                }}
              >
                <span className="t-xs mono fg-3" style={{ width: 18 }}>#{entry.rank}</span>
                <span className="t-sm fg-0" style={{ flex: 1, fontWeight: entry.is_you ? 600 : 400 }}>
                  {entry.name}{entry.is_you ? ' (you)' : ''}
                </span>
                <span className="t-xs fg-3 mono">{entry.xp.toLocaleString()} xp</span>
                {entry.streak > 0 && <span className="t-xs fg-2" style={{ display: 'inline-flex', alignItems: 'center', gap: 2 }}><Icon name="flame" size={10} />{entry.streak}</span>}
              </div>
            ))}
            {board.length === 0 && (
              <EmptyState icon="target" title="Leaderboard loading…" body="Rankings update after quiz sessions." size="sm" />
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}
