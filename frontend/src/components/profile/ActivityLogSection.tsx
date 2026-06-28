import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { activityAPI, type ActivityLogEntry } from '@/lib/api'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Skeleton } from '@/components/ui/Skeleton'
import { Icon } from '@/components/ui/Icon'

const PAGE_SIZE = 20

// Map a friendly action to a small icon — purely cosmetic, keeps the row readable.
function actionIcon(action: string): string {
  const a = action.toLowerCase()
  if (a.includes('quiz')) return 'quiz'
  if (a.includes('interview')) return 'interview'
  if (a.includes('course') || a.includes('curriculum')) return 'course'
  if (a.includes('job')) return 'target'
  if (a.includes('assistant') || a.includes('doubt')) return 'chat'
  if (a.includes('flashcard')) return 'cards'
  if (a.includes('study') || a.includes('onboarding')) return 'book'
  if (a.includes('logged in') || a.includes('profile')) return 'user'
  return 'dot'
}

function timeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime()
  const sec = Math.floor(diffMs / 1000)
  if (sec < 60) return 'just now'
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}m ago`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}h ago`
  const day = Math.floor(hr / 24)
  if (day < 30) return `${day}d ago`
  const mo = Math.floor(day / 30)
  return `${mo}mo ago`
}

function LogRow({ log }: { log: ActivityLogEntry }) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '10px 0',
        borderTop: '1px solid var(--line-1)',
      }}
    >
      <span style={{ width: 26, height: 26, borderRadius: '50%', background: 'var(--paper-2)', display: 'grid', placeItems: 'center', flexShrink: 0 }}>
        <Icon name={actionIcon(log.action)} size={13} style={{ color: 'var(--ink-2)' }} />
      </span>
      <div className="t-sm fg-0" style={{ flex: 1, minWidth: 0, fontWeight: 500 }}>{log.action}</div>
      <div className="t-xs fg-3" style={{ flexShrink: 0 }}>{timeAgo(log.timestamp)}</div>
    </div>
  )
}

export function ActivityLogSection() {
  const qc = useQueryClient()

  const { data: stats } = useQuery({
    queryKey: ['activity-stats'],
    queryFn: () => activityAPI.getStats().then((r) => r.data),
    staleTime: 60_000,
  })

  const { data, isLoading, fetchNextPage, hasNextPage, isFetchingNextPage } = useInfiniteQuery({
    queryKey: ['activity-logs'],
    queryFn: ({ pageParam = 0 }) => activityAPI.getLogs({ limit: PAGE_SIZE, skip: pageParam }).then((r) => r.data),
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((sum, p) => sum + p.logs.length, 0)
      return loaded < last.total ? loaded : undefined
    },
    initialPageParam: 0,
  })

  const clearMut = useMutation({
    mutationFn: () => activityAPI.clearLogs(),
    onSuccess: (res) => {
      toast.success(res.data.message)
      qc.invalidateQueries({ queryKey: ['activity-logs'] })
      qc.invalidateQueries({ queryKey: ['activity-stats'] })
    },
    onError: () => toast.error('Failed to clear activity logs.'),
  })

  const logs = data?.pages.flatMap((p) => p.logs) ?? []
  const total = data?.pages[0]?.total ?? 0

  const handleClear = () => {
    if (window.confirm('Clear all activity logs? This cannot be undone.')) {
      clearMut.mutate()
    }
  }

  const topActions = stats
    ? Object.entries(stats.action_counts).sort((a, b) => b[1] - a[1]).slice(0, 3)
    : []

  return (
    <Card padding="md">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <span className="caps fg-2" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Icon name="clock" size={13} />
          Recent Activity{total > 0 ? ` · ${total}` : ''}
        </span>
        <Button
          size="xs"
          variant="ghost"
          icon="trash"
          onClick={handleClear}
          disabled={clearMut.isPending || logs.length === 0}
        >
          Clear all logs
        </Button>
      </div>

      {stats && stats.total_actions > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
          {topActions.map(([action, count]) => (
            <Badge key={action} size="xs" tone="outline">{action} · {count}</Badge>
          ))}
          {stats.most_active_day && (
            <Badge size="xs" tone="outline">Most active: {stats.most_active_day}</Badge>
          )}
        </div>
      )}

      {isLoading && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} h={36} />)}
        </div>
      )}

      {!isLoading && logs.length === 0 && (
        <div style={{ padding: '24px 0', textAlign: 'center' }}>
          <Icon name="clock" size={24} style={{ color: 'var(--ink-3)', marginBottom: 8 }} />
          <div className="t-sm fg-3">No activity recorded yet.</div>
        </div>
      )}

      {logs.length > 0 && (
        <div style={{ maxHeight: 420, overflowY: 'auto' }}>
          {logs.map((log) => <LogRow key={log.id} log={log} />)}
        </div>
      )}

      {hasNextPage && (
        <div style={{ textAlign: 'center', marginTop: 12 }}>
          <Button variant="secondary" size="sm" onClick={() => fetchNextPage()} disabled={isFetchingNextPage}>
            {isFetchingNextPage ? 'Loading…' : 'Load more'}
          </Button>
        </div>
      )}
    </Card>
  )
}
