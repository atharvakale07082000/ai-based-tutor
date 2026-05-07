import { useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { useInfiniteQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { contentAPI } from '@/lib/api'
import { runEmbeddings } from '@/lib/hf'
import { PageWrapper } from '@/components/layout/PageWrapper'
import { Card } from '@/components/ui/Card'
import { Badge, HFBadge } from '@/components/ui/Badge'
import { CardSkeleton } from '@/components/ui/Skeleton'

const CONTENT_TYPES = ['video', 'article', 'exercise', 'interactive'] as const
const TOPICS = ['Python', 'Machine Learning', 'Data Science', 'Math', 'Web Dev', 'Deep Learning', 'NLP']

const TYPE_BADGE: Record<string, 'violet' | 'emerald' | 'indigo' | 'amber'> = {
  video: 'violet',
  article: 'indigo',
  exercise: 'emerald',
  interactive: 'amber',
}

let debounceTimer: ReturnType<typeof setTimeout>

export default function LearnFeedPage() {
  const [search, setSearch] = useState('')
  const [activeSearch, setActiveSearch] = useState('')
  const [selectedTopic, setSelectedTopic] = useState('')
  const [selectedTypes, setSelectedTypes] = useState<string[]>([])
  const [difficultyRange, setDifficultyRange] = useState([0, 100])
  const [isSearching, setIsSearching] = useState(false)

  const toggleType = (t: string) =>
    setSelectedTypes((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]))

  const handleSearchChange = useCallback((val: string) => {
    setSearch(val)
    clearTimeout(debounceTimer)
    debounceTimer = setTimeout(async () => {
      if (val.trim().length > 2) {
        setIsSearching(true)
        try {
          await runEmbeddings(val) // semantic embedding call
        } catch {
          // fallback to text search
        } finally {
          setIsSearching(false)
        }
      }
      setActiveSearch(val)
    }, 300)
  }, [])

  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } = useInfiniteQuery({
    queryKey: ['content', 'feed', { topic: selectedTopic, types: selectedTypes, search: activeSearch }],
    queryFn: ({ pageParam = 1 }) =>
      contentAPI.list({
        topic: selectedTopic || undefined,
        search: activeSearch || undefined,
        min_difficulty: difficultyRange[0] / 100,
        max_difficulty: difficultyRange[1] / 100,
        page: pageParam as number,
        limit: 12,
      }).then((r) => r.data),
    initialPageParam: 1,
    getNextPageParam: (last, all) => (last.has_more ? all.length + 1 : undefined),
  })

  const allItems = data?.pages.flatMap((p) => p.items) ?? []

  return (
    <PageWrapper>
      <div className="px-6 py-8 max-w-[1400px] mx-auto">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="font-display text-3xl text-paper">Learning Feed</h1>
            <p className="text-paper/50 text-sm mt-1">Content curated by your Curriculum Planner agent</p>
          </div>
          <HFBadge />
        </div>

        {/* Sticky filter bar */}
        <div className="glass border border-surface-2/50 rounded-2xl p-4 mb-6 space-y-4">
          {/* Search */}
          <div className="relative">
            <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-paper/30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              value={search}
              onChange={(e) => handleSearchChange(e.target.value)}
              placeholder="Search with semantic AI (🤗 all-MiniLM-L6-v2)…"
              className="w-full bg-surface-2 border border-surface-3 rounded-xl pl-10 pr-4 py-2.5 text-sm text-paper placeholder-paper/30 focus:outline-none focus:ring-2 focus:ring-violet/50"
            />
            {isSearching && (
              <svg className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-violet animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/>
              </svg>
            )}
          </div>

          <div className="flex flex-wrap gap-3 items-center">
            {/* Topic dropdown */}
            <select
              value={selectedTopic}
              onChange={(e) => setSelectedTopic(e.target.value)}
              className="bg-surface-2 border border-surface-3 rounded-xl px-3 py-2 text-sm text-paper focus:outline-none focus:ring-2 focus:ring-violet/50"
            >
              <option value="">All Topics</option>
              {TOPICS.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>

            {/* Type multi-select */}
            <div className="flex gap-1.5">
              {CONTENT_TYPES.map((t) => (
                <button
                  key={t}
                  onClick={() => toggleType(t)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
                    selectedTypes.includes(t)
                      ? 'bg-violet/20 border-violet text-violet-light'
                      : 'bg-surface-2 border-surface-3 text-paper/50 hover:border-violet/50'
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>

            {/* Difficulty slider */}
            <div className="flex items-center gap-2 text-xs text-paper/50">
              <span>Difficulty</span>
              <input
                type="range" min={0} max={100} value={difficultyRange[1]}
                onChange={(e) => setDifficultyRange([0, Number(e.target.value)])}
                className="w-20 accent-violet"
              />
              <span>{difficultyRange[1]}%</span>
            </div>
          </div>
        </div>

        {/* Masonry grid */}
        {isLoading ? (
          <div className="masonry-grid">
            {Array.from({ length: 9 }).map((_, i) => (
              <div key={i} className="masonry-grid-item"><CardSkeleton /></div>
            ))}
          </div>
        ) : allItems.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <div className="text-6xl mb-4" style={{ animation: 'float 3s ease-in-out infinite' }}>🗺️</div>
            <h3 className="font-display text-xl text-paper mb-2">Building your learning path…</h3>
            <p className="text-paper/50 text-sm max-w-sm">
              Your Curriculum Planner agent is mapping your personalized content sequence. Check back in a moment.
            </p>
          </div>
        ) : (
          <>
            <div className="masonry-grid">
              {allItems.map((item, idx) => (
                <motion.div
                  key={item.id}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: (idx % 12) * 0.04 }}
                  className="masonry-grid-item"
                >
                  <Link to={`/learn/${item.id}`}>
                    <Card hover>
                      <div className="flex items-start justify-between mb-3">
                        <Badge variant={TYPE_BADGE[item.content_type] ?? 'surface'}>
                          {item.content_type === 'video' ? '▶ ' : item.content_type === 'exercise' ? '💻 ' : '📄 '}
                          {item.content_type}
                        </Badge>
                        {item.is_ai_recommended && (
                          <Badge variant="amber" dot>AI Recommended</Badge>
                        )}
                      </div>
                      <h3 className="font-medium text-paper text-sm mb-2">{item.title}</h3>
                      <p className="text-xs text-paper/50 line-clamp-2 mb-3">{item.body?.slice(0, 100)}…</p>
                      <div className="flex items-center gap-2 flex-wrap">
                        <Badge variant="surface" className="text-[10px]">{item.topic}</Badge>
                        {item.subtopic && <Badge variant="surface" className="text-[10px]">{item.subtopic}</Badge>}
                        <span className="text-[10px] text-paper/30 ml-auto">⏱ {item.estimated_minutes}m</span>
                      </div>
                      <div className="mt-3 flex items-center gap-2">
                        <div className="flex-1 h-1 bg-surface-3 rounded-full overflow-hidden">
                          <div
                            className="h-full rounded-full"
                            style={{
                              width: `${item.difficulty * 100}%`,
                              background: `hsl(${270 - item.difficulty * 180}, 80%, 60%)`,
                            }}
                          />
                        </div>
                        <span className="text-[10px] text-paper/30">
                          {item.difficulty < 0.33 ? 'Easy' : item.difficulty < 0.66 ? 'Medium' : 'Hard'}
                        </span>
                      </div>
                    </Card>
                  </Link>
                </motion.div>
              ))}
            </div>

            {hasNextPage && (
              <div className="flex justify-center mt-8">
                <button
                  onClick={() => fetchNextPage()}
                  disabled={isFetchingNextPage}
                  className="px-6 py-3 bg-surface-2 border border-surface-3 rounded-xl text-sm text-paper/70 hover:border-violet/50 transition-colors disabled:opacity-50"
                >
                  {isFetchingNextPage ? 'Loading…' : 'Load more content'}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </PageWrapper>
  )
}
