import { useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { quizAPI } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Icon } from '@/components/ui/Icon'
import { ValueBar } from '@/components/ui/Progress'
import { CardSkeleton } from '@/components/ui/Skeleton'

function FlipCard({ card, revealed, onReveal }: {
  card: { id: string; front: string; back: string; hint: string; difficulty: number; topic: string }
  revealed: boolean
  onReveal: () => void
}) {
  return (
    <div
      onClick={!revealed ? onReveal : undefined}
      style={{
        width: '100%', maxWidth: 540, minHeight: 280,
        perspective: 1200, cursor: revealed ? 'default' : 'pointer',
      }}
    >
      <div
        style={{
          position: 'relative', width: '100%', minHeight: 280,
          transformStyle: 'preserve-3d',
          transform: revealed ? 'rotateY(180deg)' : 'rotateY(0deg)',
          transition: 'transform 0.45s cubic-bezier(0.4, 0, 0.2, 1)',
        }}
      >
        {/* Front */}
        <div
          style={{
            position: revealed ? 'absolute' : 'relative',
            width: '100%', minHeight: 280,
            backfaceVisibility: 'hidden',
            background: 'var(--paper-1)', border: '1px solid var(--line-1)',
            borderRadius: 'var(--r-3)', padding: '32px 36px',
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            gap: 16, textAlign: 'center', boxShadow: 'var(--shadow-2)',
          }}
        >
          <div className="caps fg-3" style={{ alignSelf: 'flex-start' }}>{card.topic}</div>
          <div className="serif" style={{ fontSize: 22, lineHeight: 1.4, color: 'var(--ink-0)', fontWeight: 400 }}>
            {card.front}
          </div>
          {card.hint && (
            <div className="t-xs fg-3" style={{ padding: '4px 10px', background: 'var(--paper-2)', borderRadius: 'var(--r-pill)' }}>
              Hint: {card.hint}
            </div>
          )}
          <div className="t-xs fg-3" style={{ marginTop: 8 }}>Tap to reveal answer</div>
        </div>

        {/* Back */}
        <div
          style={{
            position: 'absolute', inset: 0,
            backfaceVisibility: 'hidden',
            transform: 'rotateY(180deg)',
            background: 'var(--paper-0)', border: '2px solid var(--accent)',
            borderRadius: 'var(--r-3)', padding: '32px 36px',
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            gap: 16, textAlign: 'center', boxShadow: 'var(--shadow-2)',
          }}
        >
          <div className="caps" style={{ color: 'var(--accent)', alignSelf: 'flex-start' }}>Answer</div>
          <div className="t-lg fg-0" style={{ lineHeight: 1.6, fontWeight: 400 }}>
            {card.back}
          </div>
          <ValueBar value={Math.round(card.difficulty * 5)} segments={5} />
        </div>
      </div>
    </div>
  )
}

export default function FlashcardsPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const topic = params.get('topic') ?? 'Python Programming'
  const [idx, setIdx] = useState(0)
  const [revealed, setRevealed] = useState(false)
  const [ratings, setRatings] = useState<Record<string, 'easy' | 'hard' | 'skip'>>({})
  const [done, setDone] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['flashcards', topic],
    queryFn: () => quizAPI.flashcards(topic, 10).then((r) => r.data),
    staleTime: 1000 * 60 * 5,
  })

  const cards = data?.cards ?? []
  const card = cards[idx]

  const advance = (rating: 'easy' | 'hard' | 'skip') => {
    if (!card) return
    setRatings((r) => ({ ...r, [card.id]: rating }))
    setRevealed(false)
    if (idx + 1 >= cards.length) {
      setDone(true)
    } else {
      setIdx((i) => i + 1)
    }
  }

  if (isLoading) {
    return (
      <div style={{ padding: '48px 28px', maxWidth: 600, margin: '0 auto' }}>
        <CardSkeleton />
      </div>
    )
  }

  if (done) {
    const easy = Object.values(ratings).filter((r) => r === 'easy').length
    const hard = Object.values(ratings).filter((r) => r === 'hard').length
    return (
      <div style={{ padding: '48px 28px', maxWidth: 600, margin: '0 auto', textAlign: 'center' }}>
        <div style={{ fontSize: 48, marginBottom: 16 }}>🎉</div>
        <h2 className="serif" style={{ fontSize: 28, fontWeight: 400, marginBottom: 8 }}>Session complete</h2>
        <div className="t-sm fg-2" style={{ marginBottom: 24 }}>
          {easy} easy · {hard} need review · {cards.length} total
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
          <Button variant="secondary" onClick={() => { setIdx(0); setRevealed(false); setRatings({}); setDone(false) }}>
            Go again
          </Button>
          <Button onClick={() => navigate(-1)}>Back</Button>
        </div>
      </div>
    )
  }

  return (
    <div style={{ padding: '32px 28px', maxWidth: 640, margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
        <button
          onClick={() => navigate(-1)}
          style={{ background: 'none', border: 0, cursor: 'pointer', color: 'var(--ink-2)', padding: 4 }}
        >
          <Icon name="arrowL" size={16} />
        </button>
        <div>
          <div className="caps fg-3">Flashcards</div>
          <div className="t-md fg-0" style={{ fontWeight: 600 }}>{topic}</div>
        </div>
        <span style={{ flex: 1 }} />
        <Badge tone="outline" size="sm">{idx + 1} / {cards.length}</Badge>
      </div>

      {/* Progress bar */}
      <div style={{ height: 3, background: 'var(--paper-3)', borderRadius: 2, marginBottom: 24, overflow: 'hidden' }}>
        <div
          style={{
            width: `${((idx + (revealed ? 0.5 : 0)) / cards.length) * 100}%`,
            height: '100%', background: 'var(--accent)', borderRadius: 2, transition: 'width 0.3s',
          }}
        />
      </div>

      {/* Card */}
      {card && (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 20 }}>
          <FlipCard card={card} revealed={revealed} onReveal={() => setRevealed(true)} />

          {revealed && (
            <div style={{ display: 'flex', gap: 10, width: '100%', maxWidth: 540 }}>
              <button
                onClick={() => advance('hard')}
                style={{
                  flex: 1, padding: '10px 0', borderRadius: 'var(--r-2)',
                  border: '1px solid var(--neg)', background: 'none',
                  color: 'var(--neg)', fontSize: 13, cursor: 'pointer',
                  fontFamily: 'inherit', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                }}
              >
                <Icon name="refresh" size={13} /> Hard
              </button>
              <button
                onClick={() => advance('skip')}
                style={{
                  padding: '10px 16px', borderRadius: 'var(--r-2)',
                  border: '1px solid var(--line-1)', background: 'none',
                  color: 'var(--ink-2)', fontSize: 13, cursor: 'pointer',
                  fontFamily: 'inherit',
                }}
              >
                Skip
              </button>
              <button
                onClick={() => advance('easy')}
                style={{
                  flex: 1, padding: '10px 0', borderRadius: 'var(--r-2)',
                  border: '1px solid var(--pos)', background: 'none',
                  color: 'var(--pos)', fontSize: 13, cursor: 'pointer',
                  fontFamily: 'inherit', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                }}
              >
                <Icon name="check" size={13} /> Got it
              </button>
            </div>
          )}

          {!revealed && (
            <button
              onClick={() => setRevealed(true)}
              style={{
                padding: '8px 20px', borderRadius: 'var(--r-pill)',
                border: '1px solid var(--line-1)', background: 'var(--paper-1)',
                color: 'var(--ink-1)', fontSize: 13, cursor: 'pointer',
                fontFamily: 'inherit',
              }}
            >
              Show answer
            </button>
          )}
        </div>
      )}
    </div>
  )
}
