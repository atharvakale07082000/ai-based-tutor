import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useInfiniteQuery } from '@tanstack/react-query'
import { contentAPI } from '@/lib/api'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Tabs } from '@/components/ui/Tabs'
import { Icon } from '@/components/ui/Icon'
import { ValueBar } from '@/components/ui/Progress'
import { CardSkeleton } from '@/components/ui/Skeleton'

const TYPE_ICON: Record<string, string> = { video: 'play', exercise: 'code', reading: 'book', lesson: 'sparkle' }

export default function LearnFeedPage() {
  const navigate = useNavigate()
  const [filter, setFilter] = useState('all')
  const [sort, setSort] = useState('relevance')

  const { data, isLoading, fetchNextPage, hasNextPage } = useInfiniteQuery({
    queryKey: ['content', 'feed', { type: filter }],
    queryFn: ({ pageParam = 0 }) =>
      contentAPI.list({ limit: 12, offset: pageParam, type: filter === 'all' ? undefined : filter }).then((r) => r.data),
    getNextPageParam: (last: any, all: any[]) =>
      last.has_more ? all.reduce((acc: number, p: any) => acc + p.items.length, 0) : undefined,
    initialPageParam: 0,
  })

  const items = data?.pages.flatMap((p: any) => p.items) ?? []

  return (
    <div style={{ padding: '24px 28px', maxWidth: 1240, margin: '0 auto' }}>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <div>
          <div className="caps fg-3">{new Date().toLocaleDateString('en-US', { weekday: 'long' })}</div>
          <h1 className="serif" style={{ fontSize: 36, fontWeight: 400, margin: 0, letterSpacing: '-0.02em', color: 'var(--ink-0)' }}>Today's feed</h1>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <Button size="sm" variant="ghost" icon="filter">Filters</Button>
          <Button size="sm" variant="ghost" icon="refresh">Refresh</Button>
        </div>
      </div>

      {/* Filter row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16, padding: 8, background: 'var(--paper-1)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)' }}>
        <Tabs
          variant="segmented"
          value={filter}
          onChange={setFilter}
          tabs={[
            { value: 'all',      label: 'All' },
            { value: 'lesson',   label: 'Lessons' },
            { value: 'video',    label: 'Video' },
            { value: 'reading',  label: 'Reading' },
            { value: 'exercise', label: 'Exercise' },
          ]}
        />
        <span style={{ flex: 1 }} />
        <span className="t-xs fg-3">Sort</span>
        <Tabs
          variant="segmented"
          value={sort}
          onChange={setSort}
          tabs={[
            { value: 'relevance',  label: 'Relevance' },
            { value: 'difficulty', label: 'Difficulty' },
            { value: 'time',       label: 'Time' },
          ]}
        />
      </div>

      {/* Cards */}
      {isLoading ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
          {[0, 1, 2, 3, 4, 5].map((i) => <CardSkeleton key={i} />)}
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
          {items.map((m: any) => (
            <Card
              key={m.id}
              hover
              padding="md"
              style={{ display: 'flex', flexDirection: 'column', gap: 10, cursor: 'pointer' }}
              onClick={() => navigate(`/learn/${m.id}`)}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <Badge tone="outline" size="xs" icon={TYPE_ICON[m.content_type] ?? 'book'}>{m.content_type}</Badge>
                {m.is_ai_recommended && <Badge tone="accent" size="xs">AI Pick</Badge>}
                <span style={{ flex: 1 }} />
                <span className="t-xs fg-3 mono">{m.estimated_minutes}m</span>
              </div>
              <div className="t-lg fg-0" style={{ fontWeight: 500, lineHeight: 1.3 }}>{m.title}</div>
              <div className="t-sm fg-2" style={{ flex: 1, lineHeight: 1.5 }}>{m.summary ?? m.topic}</div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: 8, borderTop: '1px solid var(--line-1)' }}>
                <span className="t-xs fg-3">{m.topic}</span>
                <ValueBar value={Math.round((m.difficulty ?? 0.5) * 5)} segments={5} />
              </div>
            </Card>
          ))}
        </div>
      )}

      {hasNextPage && (
        <div style={{ textAlign: 'center', marginTop: 20 }}>
          <Button variant="secondary" onClick={() => fetchNextPage()}>Load more</Button>
        </div>
      )}

      {!isLoading && items.length === 0 && (
        <div style={{ textAlign: 'center', padding: '48px 0' }}>
          <Icon name="book" size={24} style={{ color: 'var(--ink-3)', marginBottom: 8 }} />
          <div className="t-md fg-2">No content found. The Curriculum agent is building your feed.</div>
        </div>
      )}
    </div>
  )
}
