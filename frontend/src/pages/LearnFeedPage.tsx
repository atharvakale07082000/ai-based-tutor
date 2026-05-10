import { useState } from 'react'
import { useQuery, useMutation, useQueryClient, useInfiniteQuery } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { feedAPI, type FeedItem, type TrendTopic } from '@/lib/api'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'
import { ValueBar } from '@/components/ui/Progress'
import { CardSkeleton } from '@/components/ui/Skeleton'

// ── Type icon map ─────────────────────────────────────────────────────────────

const TYPE_ICON: Record<string, string> = {
  video: 'play', course: 'course', article: 'book', news: 'feed',
}

const DOMAIN_COLOR: Record<string, string> = {
  'Data Engineering': 'var(--amber)',
  'DevOps': 'var(--blue)',
  'Cloud Computing': 'var(--teal)',
  'AI Engineering': 'var(--purple)',
  'Machine Learning': 'var(--violet)',
  'Deep Learning': 'var(--violet)',
  'Data Science': 'var(--green)',
  'Cybersecurity': 'var(--red)',
  'Software Engineering': 'var(--ink-1)',
  'Natural Language Processing': 'var(--purple)',
  'Statistics': 'var(--green)',
  'Mathematics': 'var(--ink-1)',
}

function domainColor(domain: string) {
  return DOMAIN_COLOR[domain] ?? 'var(--accent)'
}

// ── Schedule picker modal ─────────────────────────────────────────────────────

function ScheduleModal({ item, onClose, onSchedule }: {
  item: FeedItem
  onClose: () => void
  onSchedule: (iso: string) => void
}) {
  const [dt, setDt] = useState(() => {
    const tomorrow = new Date()
    tomorrow.setDate(tomorrow.getDate() + 1)
    tomorrow.setHours(9, 0, 0, 0)
    return tomorrow.toISOString().slice(0, 16)
  })

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: 'var(--paper-1)', border: '1px solid var(--line-1)',
          borderRadius: 'var(--r-3)', padding: 24, width: 360, boxShadow: 'var(--shadow-lg)',
        }}
      >
        <div className="t-lg fg-0" style={{ fontWeight: 600, marginBottom: 4 }}>Schedule for later</div>
        <div className="t-sm fg-2" style={{ marginBottom: 16, lineHeight: 1.4 }}>{item.title}</div>

        <label className="t-xs fg-3" style={{ display: 'block', marginBottom: 6 }}>Study date & time</label>
        <input
          type="datetime-local"
          value={dt}
          onChange={(e) => setDt(e.target.value)}
          style={{
            width: '100%', padding: '8px 10px', borderRadius: 'var(--r-2)',
            border: '1px solid var(--line-1)', background: 'var(--paper-0)',
            color: 'var(--ink-0)', fontSize: 13, marginBottom: 16,
          }}
        />

        <div style={{ display: 'flex', gap: 8 }}>
          <Button size="sm" variant="ghost" onClick={onClose} style={{ flex: 1 }}>Cancel</Button>
          <Button
            size="sm"
            onClick={() => {
              const iso = new Date(dt).toISOString()
              onSchedule(iso)
              onClose()
            }}
            style={{ flex: 1 }}
          >
            <Icon name="calendar" size={13} /> Schedule
          </Button>
        </div>
      </div>
    </div>
  )
}

// ── Trending topic chip ───────────────────────────────────────────────────────

function TrendChip({ topic }: { topic: TrendTopic }) {
  return (
    <div
      style={{
        display: 'inline-flex', flexDirection: 'column', gap: 3,
        padding: '10px 14px', borderRadius: 'var(--r-2)',
        border: '1px solid var(--line-1)', background: 'var(--paper-1)',
        minWidth: 160, maxWidth: 220, cursor: 'default',
        borderLeft: `3px solid ${domainColor(topic.domain)}`,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span
          className="caps"
          style={{ fontSize: 9, color: domainColor(topic.domain), letterSpacing: '0.08em' }}
        >
          {topic.domain}
        </span>
        {topic._started && (
          <Icon name="check" size={10} style={{ color: 'var(--pos)' }} />
        )}
      </div>
      <div className="t-sm fg-0" style={{ fontWeight: 500, lineHeight: 1.3 }}>{topic.subtopic}</div>
      {topic.description && (
        <div className="t-xs fg-3" style={{ lineHeight: 1.4, marginTop: 2 }}>{topic.description.slice(0, 80)}</div>
      )}
    </div>
  )
}

// ── Feed card ─────────────────────────────────────────────────────────────────

function FeedCard({ item, onSnooze, onSchedule, onClear }: {
  item: FeedItem
  onSnooze: (id: string) => void
  onSchedule: (item: FeedItem) => void
  onClear: (id: string) => void
}) {
  const snoozed = item._snoozed

  return (
    <Card
      padding="md"
      style={{
        display: 'flex', flexDirection: 'column', gap: 10,
        opacity: snoozed ? 0.55 : 1,
        transition: 'opacity 0.2s',
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <Badge tone="outline" size="xs" icon={TYPE_ICON[item.content_type] ?? 'book'}>
          {item.content_type}
        </Badge>
        {item.is_trending && <Badge tone="accent" size="xs" icon="bolt">Trending</Badge>}
        {item.is_ai_recommended && !item.is_trending && (
          <Badge tone="accent" size="xs" icon="sparkle">AI Pick</Badge>
        )}
        {snoozed && <Badge tone="outline" size="xs" icon="clock">Snoozed</Badge>}
        {item._scheduled_for && !snoozed && (
          <Badge tone="outline" size="xs" icon="calendar">Scheduled</Badge>
        )}
        <span style={{ flex: 1 }} />
        <span className="t-xs fg-3 mono">{item.estimated_minutes}m</span>
      </div>

      {/* Domain */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span
          className="caps"
          style={{ fontSize: 9, color: domainColor(item.domain), letterSpacing: '0.08em' }}
        >
          {item.domain}
        </span>
        {item.subtopic && (
          <>
            <span className="fg-3" style={{ fontSize: 10 }}>·</span>
            <span className="t-xs fg-3">{item.subtopic}</span>
          </>
        )}
      </div>

      {/* Title */}
      <a
        href={item.url}
        target="_blank"
        rel="noopener noreferrer"
        className="t-md fg-0"
        style={{ fontWeight: 500, lineHeight: 1.35, textDecoration: 'none' }}
        onMouseEnter={(e) => (e.currentTarget.style.textDecoration = 'underline')}
        onMouseLeave={(e) => (e.currentTarget.style.textDecoration = 'none')}
      >
        {item.title}
      </a>

      {/* Summary */}
      <div className="t-sm fg-2" style={{ flex: 1, lineHeight: 1.5 }}>
        {item.summary.slice(0, 160)}{item.summary.length > 160 ? '…' : ''}
      </div>

      {/* Footer */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        paddingTop: 8, borderTop: '1px solid var(--line-1)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span className="t-xs fg-3">{item.source}</span>
          <ValueBar value={Math.round((item.difficulty ?? 0.5) * 5)} segments={5} />
        </div>

        <div style={{ display: 'flex', gap: 4 }}>
          {snoozed ? (
            <button
              title="Clear snooze"
              onClick={() => onClear(item.id)}
              style={{
                padding: '3px 6px', borderRadius: 'var(--r-1)', border: '1px solid var(--line-1)',
                background: 'none', color: 'var(--ink-2)', fontSize: 11, cursor: 'pointer',
                display: 'flex', alignItems: 'center', gap: 4,
              }}
            >
              <Icon name="x" size={11} /> Unsnooze
            </button>
          ) : (
            <>
              <button
                title="Snooze for 24h"
                onClick={() => onSnooze(item.id)}
                style={{
                  padding: '3px 8px', borderRadius: 'var(--r-1)', border: '1px solid var(--line-1)',
                  background: 'none', color: 'var(--ink-2)', fontSize: 11, cursor: 'pointer',
                  display: 'flex', alignItems: 'center', gap: 4,
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--paper-2)' }}
                onMouseLeave={(e) => { e.currentTarget.style.background = 'none' }}
              >
                <Icon name="clock" size={11} /> Snooze
              </button>
              <button
                title="Schedule for later"
                onClick={() => onSchedule(item)}
                style={{
                  padding: '3px 8px', borderRadius: 'var(--r-1)', border: '1px solid var(--line-1)',
                  background: 'none', color: 'var(--ink-2)', fontSize: 11, cursor: 'pointer',
                  display: 'flex', alignItems: 'center', gap: 4,
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--paper-2)' }}
                onMouseLeave={(e) => { e.currentTarget.style.background = 'none' }}
              >
                <Icon name="calendar" size={11} /> Schedule
              </button>
            </>
          )}
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            title="Open link"
            style={{
              padding: '3px 8px', borderRadius: 'var(--r-1)', border: '1px solid var(--line-1)',
              background: 'none', color: 'var(--ink-2)', fontSize: 11, cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: 4, textDecoration: 'none',
            }}
          >
            <Icon name="arrowUR" size={11} />
          </a>
        </div>
      </div>
    </Card>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function LearnFeedPage() {
  const qc = useQueryClient()
  const [domainFilter, setDomainFilter] = useState<string>('all')
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [scheduleItem, setScheduleItem] = useState<FeedItem | null>(null)
  const [showTrending, setShowTrending] = useState(true)

  // Feed items (infinite scroll)
  const { data, isLoading, fetchNextPage, hasNextPage, isFetchingNextPage } = useInfiniteQuery({
    queryKey: ['feed', domainFilter, typeFilter],
    queryFn: ({ pageParam = 1 }) =>
      feedAPI.list({
        page: pageParam,
        limit: 12,
        domain: domainFilter === 'all' ? undefined : domainFilter,
        content_type: typeFilter === 'all' ? undefined : typeFilter,
      }).then((r) => r.data),
    getNextPageParam: (last) => last.has_more ? last.page + 1 : undefined,
    initialPageParam: 1,
  })

  // Trending topics
  const { data: trendingData, isLoading: trendingLoading } = useQuery({
    queryKey: ['feed', 'trending'],
    queryFn: () => feedAPI.trending(24).then((r) => r.data),
    staleTime: 1000 * 60 * 30, // 30m
  })

  const items = data?.pages.flatMap((p) => p.items) ?? []
  const topics = trendingData?.topics ?? []

  // Mutations
  const snoozeMut = useMutation({
    mutationFn: ({ id, hours }: { id: string; hours: number }) => feedAPI.snooze(id, hours),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['feed'] })
      toast.success('Snoozed for 24 hours')
    },
  })

  const scheduleMut = useMutation({
    mutationFn: ({ id, iso }: { id: string; iso: string }) => feedAPI.schedule(id, iso),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['feed'] })
      const dt = new Date(vars.iso).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' })
      toast.success(`Scheduled for ${dt}`)
    },
  })

  const clearMut = useMutation({
    mutationFn: (id: string) => feedAPI.clearInteraction(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['feed'] })
      toast.success('Removed')
    },
  })

  const discoveryMut = useMutation({
    mutationFn: () => feedAPI.runDiscovery(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['feed'] })
      toast.success('Trend discovery started — feed will refresh shortly')
    },
    onError: () => toast.error('Discovery failed'),
  })

  const DOMAINS = ['all', 'Data Engineering', 'DevOps', 'Cloud Computing', 'AI Engineering', 'Machine Learning', 'Data Science', 'Cybersecurity', 'Software Engineering']
  const TYPES = ['all', 'article', 'video', 'course', 'news']

  return (
    <div style={{ padding: '24px 28px', maxWidth: 1300, margin: '0 auto' }}>

      {/* Header */}
      <div style={{ marginBottom: 20, display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div>
          <div className="caps fg-3">{new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}</div>
          <h1 className="serif" style={{ fontSize: 34, fontWeight: 400, margin: '2px 0 4px', letterSpacing: '-0.02em', color: 'var(--ink-0)' }}>
            Today's feed
          </h1>
          <div className="t-sm fg-3">AI-curated content from across the tech industry</div>
        </div>
        <div style={{ display: 'flex', gap: 6, paddingTop: 4 }}>
          <Button
            size="sm" variant="ghost" icon="bolt"
            onClick={() => discoveryMut.mutate()}
            disabled={discoveryMut.isPending}
          >
            {discoveryMut.isPending ? 'Discovering…' : 'Discover trends'}
          </Button>
          <Button
            size="sm" variant="ghost" icon="refresh"
            onClick={() => qc.invalidateQueries({ queryKey: ['feed'] })}
          >
            Refresh
          </Button>
        </div>
      </div>

      {/* ── Trending Topics Section ─────────────────────────────────────────── */}
      <div style={{
        background: 'var(--paper-1)', border: '1px solid var(--line-1)',
        borderRadius: 'var(--r-3)', marginBottom: 20, overflow: 'hidden',
      }}>
        <button
          onClick={() => setShowTrending((s) => !s)}
          style={{
            width: '100%', padding: '12px 16px', background: 'none', border: 0,
            borderBottom: showTrending ? '1px solid var(--line-1)' : 'none',
            display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer',
            textAlign: 'left',
          }}
        >
          <Icon name="bolt" size={14} style={{ color: 'var(--accent)' }} />
          <span className="t-sm fg-0" style={{ fontWeight: 600 }}>24 Trending Topics</span>
          {trendingData?.discovered_at && (
            <span className="t-xs fg-3">
              · updated {new Date(trendingData.discovered_at).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
          <span style={{ flex: 1 }} />
          <Icon name={showTrending ? 'chevU' : 'chevD'} size={13} style={{ color: 'var(--ink-3)' }} />
        </button>

        {showTrending && (
          <div style={{ padding: 16 }}>
            {trendingLoading ? (
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {Array.from({ length: 8 }).map((_, i) => (
                  <div key={i} style={{
                    width: 180, height: 72, borderRadius: 'var(--r-2)',
                    background: 'var(--paper-2)', animation: 'pulse 1.5s ease-in-out infinite',
                  }} />
                ))}
              </div>
            ) : topics.length === 0 ? (
              <div className="t-sm fg-3" style={{ padding: '8px 0' }}>
                No trending topics yet. Click "Discover trends" to fetch the latest.
              </div>
            ) : (
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {topics.map((t) => <TrendChip key={t.id} topic={t} />)}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Filters ────────────────────────────────────────────────────────── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16,
        padding: '8px 12px', background: 'var(--paper-1)',
        border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', flexWrap: 'wrap',
      }}>
        <span className="t-xs fg-3">Domain</span>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {DOMAINS.map((d) => (
            <button
              key={d}
              onClick={() => setDomainFilter(d)}
              style={{
                padding: '3px 10px', borderRadius: 'var(--r-1)',
                border: '1px solid var(--line-1)',
                background: domainFilter === d ? 'var(--ink-0)' : 'none',
                color: domainFilter === d ? 'var(--paper-0)' : 'var(--ink-1)',
                fontSize: 12, cursor: 'pointer', fontFamily: 'inherit',
              }}
            >
              {d === 'all' ? 'All' : d}
            </button>
          ))}
        </div>
        <div style={{ width: 1, height: 20, background: 'var(--line-1)', margin: '0 4px' }} />
        <span className="t-xs fg-3">Type</span>
        <div style={{ display: 'flex', gap: 4 }}>
          {TYPES.map((t) => (
            <button
              key={t}
              onClick={() => setTypeFilter(t)}
              style={{
                padding: '3px 10px', borderRadius: 'var(--r-1)',
                border: '1px solid var(--line-1)',
                background: typeFilter === t ? 'var(--ink-0)' : 'none',
                color: typeFilter === t ? 'var(--paper-0)' : 'var(--ink-1)',
                fontSize: 12, cursor: 'pointer', fontFamily: 'inherit',
              }}
            >
              {t === 'all' ? 'All' : t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* ── Feed grid ──────────────────────────────────────────────────────── */}
      {isLoading ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 12 }}>
          {Array.from({ length: 6 }).map((_, i) => <CardSkeleton key={i} />)}
        </div>
      ) : items.length === 0 ? (
        <div style={{
          textAlign: 'center', padding: '56px 0',
          background: 'var(--paper-1)', borderRadius: 'var(--r-3)',
          border: '1px solid var(--line-1)',
        }}>
          <Icon name="feed" size={28} style={{ color: 'var(--ink-3)', marginBottom: 12 }} />
          <div className="t-md fg-1" style={{ marginBottom: 8 }}>Your feed is empty</div>
          <div className="t-sm fg-3" style={{ marginBottom: 20 }}>
            Click "Discover trends" to populate it with AI-curated content.
          </div>
          <Button onClick={() => discoveryMut.mutate()} disabled={discoveryMut.isPending} icon="bolt">
            {discoveryMut.isPending ? 'Discovering…' : 'Discover now'}
          </Button>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 12 }}>
          {items.map((item: FeedItem) => (
            <FeedCard
              key={item.id}
              item={item}
              onSnooze={(id) => snoozeMut.mutate({ id, hours: 24 })}
              onSchedule={setScheduleItem}
              onClear={(id) => clearMut.mutate(id)}
            />
          ))}
        </div>
      )}

      {/* Load more */}
      {hasNextPage && (
        <div style={{ textAlign: 'center', marginTop: 20 }}>
          <Button variant="secondary" onClick={() => fetchNextPage()} disabled={isFetchingNextPage}>
            {isFetchingNextPage ? 'Loading…' : 'Load more'}
          </Button>
        </div>
      )}

      {/* Schedule modal */}
      {scheduleItem && (
        <ScheduleModal
          item={scheduleItem}
          onClose={() => setScheduleItem(null)}
          onSchedule={(iso) => scheduleMut.mutate({ id: scheduleItem.id, iso })}
        />
      )}
    </div>
  )
}
