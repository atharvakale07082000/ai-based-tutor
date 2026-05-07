import { Suspense } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useQuery } from '@tanstack/react-query'
import { RadarChart, PolarGrid, PolarAngleAxis, Radar, ResponsiveContainer, Tooltip } from 'recharts'
import { PageWrapper } from '@/components/layout/PageWrapper'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { CardSkeleton, Skeleton } from '@/components/ui/Skeleton'
import { useLearnerStore } from '@/stores/learnerStore'
import { contentAPI, doubtsAPI } from '@/lib/api'

const MOOD_EMOJI: Record<string, string> = {
  POSITIVE: '😊',
  NEGATIVE: '😟',
  NEUTRAL: '😐',
}

function XPRing({ xp }: { xp: number }) {
  const max = 2000
  const pct = Math.min(xp / max, 1)
  const r = 38
  const circ = 2 * Math.PI * r
  const dash = circ * pct

  return (
    <div className="flex flex-col items-center gap-1">
      <div className="relative w-24 h-24">
        <svg className="w-24 h-24 xp-ring" viewBox="0 0 100 100">
          <circle cx="50" cy="50" r={r} fill="none" stroke="#1F2937" strokeWidth="8" />
          <motion.circle
            cx="50" cy="50" r={r} fill="none"
            stroke="url(#xpGrad)" strokeWidth="8"
            strokeLinecap="round"
            strokeDasharray={circ}
            initial={{ strokeDashoffset: circ }}
            animate={{ strokeDashoffset: circ - dash }}
            transition={{ duration: 1.2, ease: 'easeOut' }}
          />
          <defs>
            <linearGradient id="xpGrad" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#7C3AED" />
              <stop offset="100%" stopColor="#6366F1" />
            </linearGradient>
          </defs>
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-sm font-bold text-paper">{xp.toLocaleString()}</span>
          <span className="text-[10px] text-paper/40">XP</span>
        </div>
      </div>
      <span className="text-xs text-paper/50">Level {Math.floor(xp / 500) + 1}</span>
    </div>
  )
}

function RadarSkillMap({ proficiency }: { proficiency: Record<string, number> }) {
  const data = Object.entries(proficiency)
    .slice(0, 8)
    .map(([topic, score]) => ({
      topic: topic.length > 12 ? topic.slice(0, 12) + '…' : topic,
      score: Math.round((score / 1000) * 100),
    }))

  if (data.length === 0) {
    data.push(
      { topic: 'Python', score: 50 },
      { topic: 'ML', score: 30 },
      { topic: 'Math', score: 40 },
      { topic: 'Stats', score: 35 },
      { topic: 'Data Sci', score: 45 },
    )
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <RadarChart data={data} margin={{ top: 10, right: 20, bottom: 10, left: 20 }}>
        <PolarGrid stroke="#374151" />
        <PolarAngleAxis dataKey="topic" tick={{ fill: '#9CA3AF', fontSize: 11 }} />
        <Radar
          name="Proficiency"
          dataKey="score"
          stroke="#7C3AED"
          fill="#7C3AED"
          fillOpacity={0.3}
          strokeWidth={2}
        />
        <Tooltip
          contentStyle={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8 }}
          labelStyle={{ color: '#F9FAFB' }}
        />
      </RadarChart>
    </ResponsiveContainer>
  )
}

export default function DashboardPage() {
  const { name, xp, streak, topicProficiency, doubtSessions } = useLearnerStore()

  const { data: contentData, isLoading: contentLoading } = useQuery({
    queryKey: ['content', 'feed', {}],
    queryFn: () => contentAPI.list({ limit: 6 }).then((r) => r.data),
  })

  const { data: sessionsData } = useQuery({
    queryKey: ['doubts', 'sessions'],
    queryFn: () => doubtsAPI.getSessions().then((r) => r.data),
  })

  const stagger = {
    animate: { transition: { staggerChildren: 0.08 } },
  }
  const item = {
    initial: { opacity: 0, y: 16 },
    animate: { opacity: 1, y: 0 },
  }

  return (
    <PageWrapper>
      <div className="px-6 py-8 max-w-[1400px] mx-auto">
        {/* Greeting */}
        <div className="mb-8">
          <h1 className="font-display text-3xl text-paper">
            Good {new Date().getHours() < 12 ? 'morning' : new Date().getHours() < 18 ? 'afternoon' : 'evening'},{' '}
            <span className="gradient-text">{name || 'Learner'}</span>
          </h1>
          <p className="text-paper/50 mt-1">Ready to continue your learning journey?</p>
        </div>

        {/* 12-col grid */}
        <div className="grid grid-cols-12 gap-6">
          {/* Col 1-8: Daily learning feed */}
          <div className="col-span-12 lg:col-span-8">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-medium text-paper/70 uppercase tracking-wider">Today's Learning Feed</h2>
              <Link to="/learn" className="text-xs text-violet-light hover:underline">View all →</Link>
            </div>
            {contentLoading ? (
              <div className="flex gap-4 overflow-x-auto pb-2">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="min-w-[280px]"><CardSkeleton /></div>
                ))}
              </div>
            ) : (
              <motion.div variants={stagger} animate="animate" className="flex gap-4 overflow-x-auto pb-2 scrollbar-hide">
                {(contentData?.items ?? []).slice(0, 5).map((item_data) => (
                  <motion.div key={item_data.id} variants={item} className="min-w-[280px]">
                    <Link to={`/learn/${item_data.id}`}>
                      <Card hover className="h-full">
                        <div className="flex items-start justify-between mb-3">
                          <Badge variant={item_data.content_type === 'video' ? 'violet' : item_data.content_type === 'exercise' ? 'emerald' : 'indigo'}>
                            {item_data.content_type}
                          </Badge>
                          {item_data.is_ai_recommended && (
                            <Badge variant="amber">AI Pick</Badge>
                          )}
                        </div>
                        <h3 className="font-medium text-paper text-sm mb-2 line-clamp-2">{item_data.title}</h3>
                        <div className="flex items-center gap-3 text-xs text-paper/40 mt-auto">
                          <span>⏱ {item_data.estimated_minutes}m</span>
                          <span>📚 {item_data.topic}</span>
                        </div>
                        <div className="mt-3 h-1 bg-surface-3 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-gradient-to-r from-violet to-indigo-light rounded-full"
                            style={{ width: `${item_data.difficulty * 100}%` }}
                          />
                        </div>
                        <p className="text-[10px] text-paper/30 mt-1">
                          Difficulty: {Math.round(item_data.difficulty * 100)}%
                        </p>
                      </Card>
                    </Link>
                  </motion.div>
                ))}
              </motion.div>
            )}
          </div>

          {/* Col 9-12: Sidebar stats */}
          <div className="col-span-12 lg:col-span-4 space-y-4">
            {/* Streak + XP */}
            <Card>
              <div className="flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-2xl">🔥</span>
                    <span className="text-3xl font-bold text-amber">{streak}</span>
                  </div>
                  <p className="text-xs text-paper/50">Day streak</p>
                </div>
                <XPRing xp={xp} />
              </div>
            </Card>

            {/* Next quiz reminder */}
            <Card variant="bordered">
              <div className="flex items-start gap-3">
                <span className="text-2xl">📝</span>
                <div>
                  <p className="text-sm font-medium text-paper">Quiz due today</p>
                  <p className="text-xs text-paper/50 mt-0.5">Python Functions — 5 questions</p>
                  <Link to="/quiz/new" className="mt-2 block">
                    <Badge variant="violet" className="cursor-pointer hover:bg-violet/30 transition-colors">
                      Start Quiz →
                    </Badge>
                  </Link>
                </div>
              </div>
            </Card>
          </div>

          {/* Row 2: already covered by AgentStatusBar in PageWrapper */}

          {/* Row 3 Col 1-5: Skill mini-map */}
          <div className="col-span-12 lg:col-span-5">
            <Card>
              <h3 className="text-sm font-medium text-paper/70 uppercase tracking-wider mb-4">Skill Progress Map</h3>
              <Suspense fallback={<Skeleton className="h-48 w-full" />}>
                <RadarSkillMap proficiency={topicProficiency} />
              </Suspense>
              <p className="text-xs text-paper/30 text-center mt-2">Powered by Progress Tracker agent</p>
            </Card>
          </div>

          {/* Row 3 Col 6-12: Recent doubt sessions */}
          <div className="col-span-12 lg:col-span-7">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-medium text-paper/70 uppercase tracking-wider">Recent Doubt Sessions</h3>
              <Link to="/doubts" className="text-xs text-violet-light hover:underline">Open Chat →</Link>
            </div>
            <div className="space-y-3">
              {(sessionsData ?? doubtSessions).slice(0, 3).map((session) => (
                <Link key={session.id} to={`/doubts`}>
                  <Card hover padding="sm" className="flex items-center gap-3">
                    <span className="text-xl">{MOOD_EMOJI[session.sentiment_mood?.toUpperCase() ?? 'NEUTRAL'] ?? '💬'}</span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-paper truncate">{session.topic_context ?? 'General question'}</p>
                      <p className="text-xs text-paper/40">{new Date(session.started_at).toLocaleDateString()}</p>
                    </div>
                    {session.sentiment_mood && (
                      <Badge
                        variant={session.sentiment_mood === 'POSITIVE' ? 'emerald' : session.sentiment_mood === 'NEGATIVE' ? 'rose' : 'surface'}
                      >
                        {session.sentiment_mood.toLowerCase()}
                      </Badge>
                    )}
                  </Card>
                </Link>
              ))}
              {(!sessionsData || sessionsData.length === 0) && (
                <div className="text-center py-8 text-paper/30 text-sm">
                  <span className="text-3xl block mb-2">💬</span>
                  No doubt sessions yet. Ask your first question!
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </PageWrapper>
  )
}
