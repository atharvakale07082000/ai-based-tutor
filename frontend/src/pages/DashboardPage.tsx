import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { contentAPI, doubtsAPI, quizAPI, progressAPI, leaderboardAPI, learnerAPI } from '@/lib/api'
import { useLearnerStore } from '@/stores/learnerStore'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'
import { ValueBar } from '@/components/ui/Progress'
import { EmptyState } from '@/components/ui/EmptyState'
import { Skeleton } from '@/components/ui/Skeleton'

// Instrument readout: mono label over a big tabular display number.
// `signal` marks the one headline metric (job readiness) in amber.
function Stat({ label, value, sub, signal }: { label: string; value: string; sub?: string; signal?: boolean }) {
  return (
    <div style={{
      /* No inline `flex` — the .stat-row rule owns how these size, and an inline value
         would beat the stylesheet and keep five tiles crammed onto a 390px screen. */
      padding: '13px 15px 14px', minWidth: 0,
      background: 'var(--paper-1)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)',
      borderTop: `2px solid ${signal ? 'var(--signal)' : 'var(--line-2)'}`,
    }}>
      <div className="readout-label">{label}</div>
      <div className="readout-value tnum" style={{ fontSize: 30, marginTop: 9, color: signal ? 'var(--signal)' : 'var(--ink-0)' }}>{value}</div>
      {sub && <div className="t-xs fg-3" style={{ marginTop: 4 }}>{sub}</div>}
    </div>
  )
}

// Skill rating row: terracotta→amber fill under the concept's ELO, in mono figures.
function SkillBar({ name, value }: { name: string; value: number }) {
  const pct = Math.min(value * 100, 100)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '5px 0' }}>
      <span className="t-sm fg-1" style={{ width: 108, fontWeight: 500 }}>{name}</span>
      <div style={{ flex: 1, height: 6, background: 'var(--paper-3)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: 'linear-gradient(90deg, var(--accent), var(--signal))', borderRadius: 3 }} />
      </div>
      <span className="t-xs fg-2" style={{ width: 52, textAlign: 'right' }}>{Math.round(pct)}%</span>
    </div>
  )
}


/** Below this many ranked learners, a position on the board carries no information. */
const MIN_RANKED_LEARNERS = 3

export default function DashboardPage() {
  const navigate = useNavigate()
  const { name, xp: storedXp, streak: storedStreak, topicProficiency: storedProficiency } = useLearnerStore()
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

  // The dashboard used to read xp/streak/proficiency straight from the client store, which
  // nothing hydrates from the server — so it showed 0s while /progress reported real values
  // and the leaderboard below ranked the same user with XP the tile denied. One source now.
  const { data: progress } = useQuery({
    queryKey: ['progress'],
    queryFn: () => progressAPI.get().then((r) => r.data),
    staleTime: 1000 * 60,
  })

  const setLearner = useLearnerStore((st) => st.setLearner)
  useEffect(() => {
    if (!progress) return
    setLearner({
      xp: progress.xp,
      streak: progress.streak,
      topicProficiency: progress.topic_proficiency,
    })
  }, [progress, setLearner])

  const { data: dueTopicsData } = useQuery({
    queryKey: ['progress', 'due-topics'],
    queryFn: () => progressAPI.dueTopics().then((r) => r.data),
    staleTime: 1000 * 60 * 5,
  })

  const { data: leaderboardData, isLoading: leaderboardLoading } = useQuery({
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
      toast.error('Could not generate quiz — try again')
    } finally {
      setIsGeneratingQuiz(false)
    }
  }

  const items = contentData?.items ?? []
  const sessions = sessionsData ?? []
  const dueTopics = (dueTopicsData?.due_topics ?? []).filter((t) => t.is_due).slice(0, 5)

  // Server value wins; the store is only a pre-hydration placeholder.
  const xp = progress?.xp ?? storedXp
  const streak = progress?.streak ?? storedStreak
  const topicProficiency = progress?.topic_proficiency ?? storedProficiency
  const masteryElo = progress?.mastery_elo ?? 700
  // null = nothing graded yet. Render nothing rather than a 0% that reads as a verdict.
  const readiness = progress?.job_readiness ?? null
  const board = leaderboardData?.board ?? []
  const yourRank = leaderboardData?.your_rank

  return (
    <div className="page-pad" style={{ padding: '24px 28px', maxWidth: 1240, margin: '0 auto' }}>
      {/* Greeting */}
      <div style={{ marginBottom: 20, display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <div className="eyebrow" style={{ marginBottom: 6 }}>
            {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
          </div>
          <h1 className="display" style={{ fontSize: 38, fontWeight: 600, margin: 0, color: 'var(--ink-0)', letterSpacing: '-0.03em' }}>
            Good {new Date().getHours() < 12 ? 'morning' : 'afternoon'},{' '}
            <span style={{ color: 'var(--accent)' }}>{name || 'Learner'}</span>.
          </h1>
          <p className="t-md fg-2" style={{ marginTop: 4 }}>
            {learnerProfile?.target_role
              ? <>Targeting <strong>{learnerProfile.target_role}</strong>{streak > 0 ? <> · {streak}-day streak.</> : '.'}</>
              : streak > 0
                ? <>You're on a {streak}-day streak. Keep it going.</>
                : <>Answer a quiz or finish a lesson to start your streak.</>}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <Button size="sm" variant="ghost" icon="calendar" onClick={() => navigate('/learn')}>Schedule</Button>
          <Button size="sm" variant="accent" icon="sparkle" onClick={() => navigate('/atelier')}>Ask Atelier</Button>
        </div>
      </div>

      {/* Stat row */}
      <div className="stat-row" style={{ marginBottom: 16 }}>
        {readiness != null && (
          <Stat
            label="Job Readiness"
            value={`${Math.round(readiness)}%`}
            sub="from graded work"
            signal
          />
        )}
        <Stat label="Streak" value={String(streak)} sub="days · keep going!" />
        <Stat label="XP" value={xp.toLocaleString()} sub="lifetime" />
        <Stat label="Coaching sessions" value={String(sessions.length || 0)} sub="total" />
        <Stat label="Skills tracked" value={String(Object.keys(topicProficiency).length)} sub="topics rated" />
      </div>

      {/* Main grid */}
      <div className="page-grid">
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
              {items.slice(0, 5).map((m, i) => {
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
              {sessions.slice(0, 4).map((s) => (
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
              <span className="caps" style={{ color: 'var(--ink-2)' }}>Skill mastery</span>
              <span className="t-xs fg-3 mono">{Object.keys(topicProficiency).length} tracked</span>
            </div>
            {Object.entries(topicProficiency).slice(0, 6).map(([k, v]) => (
              <SkillBar key={k} name={k.slice(0, 14)} value={v / 1000} />
            ))}
            {Object.keys(topicProficiency).length === 0 && (
              <div className="t-xs fg-3" style={{ textAlign: 'center', padding: 8 }}>
                {learnerProfile?.target_role ? `Complete interviews to build your ${learnerProfile.target_role} readiness map.` : 'Take a quiz or an interview and your skills will appear here.'}
              </div>
            )}
            <div className="t-xs fg-3" style={{ marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--line-1)', display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--agent-prog)', display: 'inline-block' }} />
              Updated after each interview · <a style={{ color: 'var(--accent)', cursor: 'pointer' }} onClick={() => navigate('/progress')}>View full progress →</a>
            </div>
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
                <span className="t-xs fg-3">{t.elo >= masteryElo ? 'mastered' : t.elo >= 500 ? 'mid' : 'needs work'}</span>
                {/* `urgency` measures how overdue the review is, NOT how weak the skill is —
                    labelling it "Critical gap" put an alarming skill judgement on a scheduling
                    signal, and every due topic got it. */}
                <Badge size="xs" tone={t.urgency >= 0.8 ? 'neg' : t.urgency >= 0.5 ? 'warn' : 'outline'}>
                  {t.days_since_last_quiz === null
                    ? 'New'
                    : t.urgency >= 0.8
                      ? 'Overdue'
                      : 'Due soon'}
                </Badge>
              </div>
            )) : (
              <div className="t-xs fg-3" style={{ padding: '16px 14px', textAlign: 'center' }}>
                {dueTopicsData ? 'All caught up! No reviews due.' : 'Loading due topics…'}
              </div>
            )}
            <div style={{ padding: 10, borderTop: '1px solid var(--line-1)' }}>
              <Button size="sm" variant="signal" full iconRight="arrow" onClick={handleStartQuiz} loading={isGeneratingQuiz}>
                {dueTopics[0] ? `Practice ${dueTopics[0].topic}` : 'Start skill practice'}
              </Button>
            </div>
          </Card>

          {/* Leaderboard */}
          <Card padding="none">
            <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--line-1)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span className="caps" style={{ color: 'var(--ink-2)' }}>Leaderboard</span>
              {/* A rank is only meaningful against other people. With one or two learners on the
                  board, "You're #1" is technically true and completely hollow. */}
              {yourRank && board.length >= MIN_RANKED_LEARNERS && (
                <span className="t-xs fg-3">You're #{yourRank}</span>
              )}
            </div>
            {board.length > 0 && board.length < MIN_RANKED_LEARNERS && (
              <div className="t-xs fg-3" style={{ padding: '8px 14px' }}>
                Ranking starts once a few more learners are active.
              </div>
            )}
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
            {/* "Loading…" used to live in the empty branch, so a genuinely empty board
                showed a spinner that never resolved. Loading and empty are now distinct. */}
            {board.length === 0 && (
              leaderboardLoading ? (
                <Skeleton h={72} />
              ) : (
                <EmptyState
                  icon="target"
                  title="No one ranked yet"
                  body="Finish a quiz to put yourself on the board."
                  action={{ label: 'Find a quiz', onClick: () => navigate('/learn') }}
                  size="sm"
                />
              )
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}
