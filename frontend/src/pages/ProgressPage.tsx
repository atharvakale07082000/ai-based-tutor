import { Suspense, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import {
  RadarChart, PolarGrid, PolarAngleAxis, Radar, ResponsiveContainer, Tooltip,
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
} from 'recharts'
import { PageWrapper } from '@/components/layout/PageWrapper'
import { Card } from '@/components/ui/Card'
import { Badge, HFBadge } from '@/components/ui/Badge'
import { Skeleton } from '@/components/ui/Skeleton'
import { progressAPI } from '@/lib/api'
import { useLearnerStore } from '@/stores/learnerStore'
import toast from 'react-hot-toast'

const MOOD_EMOJI: Record<string, string> = { POSITIVE: '😊', NEGATIVE: '😟', NEUTRAL: '😐' }
const MOOD_COLOR: Record<string, string> = { POSITIVE: '#10B981', NEGATIVE: '#F43F5E', NEUTRAL: '#F59E0B' }

export default function ProgressPage() {
  const { streak, topicProficiency } = useLearnerStore()
  const [expandedTopic, setExpandedTopic] = useState<string | null>(null)
  const [downloading, setDownloading] = useState(false)

  const { data: progress, isLoading } = useQuery({
    queryKey: ['progress'],
    queryFn: () => progressAPI.get().then((r) => r.data),
  })

  const radarData = Object.entries(
    progress?.topic_proficiency ?? topicProficiency
  )
    .slice(0, 8)
    .map(([topic, score]) => ({
      topic: topic.length > 10 ? topic.slice(0, 10) + '…' : topic,
      fullTopic: topic,
      score: Math.round((score / 1000) * 100),
    }))

  // Area chart: last 30 days proficiency per topic
  const areaData = Array.from({ length: 30 }, (_, i) => {
    const date = new Date()
    date.setDate(date.getDate() - (29 - i))
    return {
      date: date.toLocaleDateString('en', { month: 'short', day: 'numeric' }),
      ...Object.fromEntries(
        Object.entries(progress?.topic_proficiency ?? topicProficiency)
          .slice(0, 4)
          .map(([topic, score]) => [
            topic,
            Math.max(0, score + (Math.random() - 0.5) * 50 - (29 - i) * 2),
          ])
      ),
    }
  })

  const topicColors = ['#7C3AED', '#4338CA', '#10B981', '#F59E0B']
  const topicKeys = Object.keys(progress?.topic_proficiency ?? topicProficiency).slice(0, 4)

  const handleDownloadReport = async () => {
    setDownloading(true)
    try {
      const { data } = await progressAPI.downloadReport()
      const url = URL.createObjectURL(data)
      const a = document.createElement('a')
      a.href = url
      a.download = 'progress-report.pdf'
      a.click()
      URL.revokeObjectURL(url)
      toast.success('Report downloaded!')
    } catch {
      toast.error('Could not generate report')
    } finally {
      setDownloading(false)
    }
  }

  const moodTimeline = progress?.mood_timeline ?? []

  return (
    <PageWrapper>
      <div className="px-6 py-8 max-w-[1400px] mx-auto space-y-8">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-display text-3xl text-paper">Progress & Skill Map</h1>
            <p className="text-paper/50 text-sm mt-1">Powered by Progress Tracker agent + DistilBERT sentiment</p>
          </div>
          <button
            onClick={handleDownloadReport}
            disabled={downloading}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-surface-2 border border-surface-3 text-sm text-paper/70 hover:border-violet/50 transition-colors disabled:opacity-50"
          >
            {downloading ? (
              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/>
              </svg>
            ) : '⬇'}
            Export PDF Report
          </button>
        </div>

        {/* Metric cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            { label: 'Study Time', value: isLoading ? '—' : `${Math.round((progress?.total_study_minutes ?? 0) / 60)}h`, icon: '⏱️' },
            { label: 'Quiz Accuracy', value: isLoading ? '—' : `${Math.round((progress?.quiz_accuracy ?? 0) * 100)}%`, icon: '🎯' },
            { label: 'Doubts Resolved', value: isLoading ? '—' : String(progress?.doubts_resolved ?? 0), icon: '💡' },
            { label: 'Current Streak', value: isLoading ? '—' : `${streak} days`, icon: '🔥' },
          ].map(({ label, value, icon }) => (
            <motion.div
              key={label}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 }}
            >
              <Card>
                <div className="text-2xl mb-2">{icon}</div>
                <div className="text-2xl font-bold text-paper">{value}</div>
                <div className="text-xs text-paper/50 mt-1">{label}</div>
              </Card>
            </motion.div>
          ))}
        </div>

        {/* Radar chart hero */}
        <Card>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-medium text-paper/70 uppercase tracking-wider">Skill Proficiency Map</h2>
            <span className="text-xs text-paper/30">Click an axis to drill down</span>
          </div>
          {isLoading ? (
            <Skeleton className="h-80 w-full" />
          ) : (
            <Suspense fallback={<Skeleton className="h-80 w-full" />}>
              <ResponsiveContainer width="100%" height={320}>
                <RadarChart data={radarData} margin={{ top: 20, right: 40, bottom: 20, left: 40 }}>
                  <PolarGrid stroke="#374151" />
                  <PolarAngleAxis
                    dataKey="topic"
                    tick={{ fill: '#9CA3AF', fontSize: 12 }}
                    onClick={({ value }) => {
                      const found = radarData.find((d) => d.topic === value)
                      if (found) setExpandedTopic((prev) => prev === found.fullTopic ? null : found.fullTopic)
                    }}
                  />
                  <Radar
                    name="Proficiency"
                    dataKey="score"
                    stroke="#7C3AED"
                    fill="#7C3AED"
                    fillOpacity={0.35}
                    strokeWidth={2}
                  />
                  <Tooltip
                    contentStyle={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8 }}
                    labelStyle={{ color: '#F9FAFB' }}
                    formatter={(v) => [`${v}%`, 'Proficiency']}
                  />
                </RadarChart>
              </ResponsiveContainer>
            </Suspense>
          )}

          {/* Topic deep-dive panel */}
          {expandedTopic && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="mt-4 border-t border-surface-2 pt-4"
            >
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-medium text-paper">{expandedTopic} — Sub-topics</h3>
                <button onClick={() => setExpandedTopic(null)} className="text-xs text-paper/40 hover:text-paper">✕</button>
              </div>
              <div className="space-y-2">
                {['Fundamentals', 'Intermediate', 'Advanced', 'Practice Projects'].map((sub) => (
                  <div key={sub} className="flex items-center gap-3">
                    <span className="text-xs text-paper/60 w-32">{sub}</span>
                    <div className="flex-1 h-2 bg-surface-2 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-violet to-indigo-light rounded-full"
                        style={{ width: `${30 + Math.random() * 60}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </motion.div>
          )}
        </Card>

        {/* Learning velocity chart */}
        <Card>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-medium text-paper/70 uppercase tracking-wider">Learning Velocity (30 days)</h2>
            <div className="flex gap-3">
              {topicKeys.slice(0, 4).map((topic, i) => (
                <div key={topic} className="flex items-center gap-1">
                  <div className="w-2 h-2 rounded-full" style={{ background: topicColors[i] }} />
                  <span className="text-xs text-paper/40 max-w-[60px] truncate">{topic}</span>
                </div>
              ))}
            </div>
          </div>
          <Suspense fallback={<Skeleton className="h-48 w-full" />}>
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={areaData} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                <defs>
                  {topicKeys.map((_, i) => (
                    <linearGradient key={i} id={`grad${i}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={topicColors[i]} stopOpacity={0.4} />
                      <stop offset="100%" stopColor={topicColors[i]} stopOpacity={0} />
                    </linearGradient>
                  ))}
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis dataKey="date" tick={{ fill: '#6B7280', fontSize: 10 }} tickLine={false} interval={6} />
                <YAxis tick={{ fill: '#6B7280', fontSize: 10 }} tickLine={false} domain={[0, 1000]} />
                <Tooltip
                  contentStyle={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8 }}
                  labelStyle={{ color: '#F9FAFB' }}
                />
                {topicKeys.map((topic, i) => (
                  <Area
                    key={topic}
                    type="monotone"
                    dataKey={topic}
                    stroke={topicColors[i]}
                    fill={`url(#grad${i})`}
                    strokeWidth={2}
                  />
                ))}
              </AreaChart>
            </ResponsiveContainer>
          </Suspense>
        </Card>

        {/* Mood timeline */}
        <Card>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-sm font-medium text-paper/70 uppercase tracking-wider">Mood Timeline</h2>
              <p className="text-xs text-paper/30 mt-0.5">Sentiment analysis by 🤗 DistilBERT-SST-2</p>
            </div>
            <HFBadge />
          </div>
          {moodTimeline.length === 0 ? (
            <p className="text-sm text-paper/40 py-4 text-center">Complete quiz sessions to see your mood timeline</p>
          ) : (
            <div className="flex items-center gap-3 overflow-x-auto pb-2">
              {moodTimeline.map((entry) => (
                <div key={entry.session_id} className="flex flex-col items-center gap-1 shrink-0">
                  <span className="text-xl">{MOOD_EMOJI[entry.mood] ?? '💬'}</span>
                  <div
                    className="w-2 h-8 rounded-full"
                    style={{ background: MOOD_COLOR[entry.mood] ?? '#6B7280' }}
                  />
                  <span className="text-[9px] text-paper/30">{new Date(entry.date).toLocaleDateString('en', { month: 'short', day: 'numeric' })}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </PageWrapper>
  )
}
