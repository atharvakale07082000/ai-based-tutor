import { useState, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import { contentAPI, quizAPI } from '@/lib/api'
import { runImageCaption } from '@/lib/hf'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Icon } from '@/components/ui/Icon'
import { Card } from '@/components/ui/Card'
import toast from 'react-hot-toast'

export default function ModulePlayerPage() {
  const { moduleId } = useParams<{ moduleId: string }>()
  const navigate = useNavigate()
  const [progress, setProgress] = useState(0)
  const [showQuizPrompt, setShowQuizPrompt] = useState(false)
  const [doubtInput, setDoubtInput] = useState('')
  const [captionLoading, setCaptionLoading] = useState(false)
  const dropRef = useRef<HTMLDivElement>(null)

  const { data: module, isLoading } = useQuery({
    queryKey: ['content', 'module', moduleId],
    queryFn: () => contentAPI.get(moduleId!).then((r) => r.data),
    enabled: !!moduleId,
  })

  const handleImageDrop = async (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (!file || !file.type.startsWith('image/')) return
    setCaptionLoading(true)
    try {
      const caption = await runImageCaption(file)
      setDoubtInput((prev) => `[Image: ${caption}]\n${prev}`)
      toast.success('Image captioned')
    } catch {
      toast.error('Could not caption image')
    } finally {
      setCaptionLoading(false)
    }
  }

  const handleStartQuiz = async () => {
    if (!module) return
    try {
      const { data } = await quizAPI.generate(module.topic)
      navigate(`/quiz/${data.quiz_id}`)
    } catch {
      toast.error('Could not generate quiz')
    }
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 280px', height: '100%', overflow: 'hidden' }}>
      {/* Main content */}
      <div style={{ overflowY: 'auto', padding: '24px 32px' }}>
        {isLoading ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div className="skel" style={{ height: 32, width: '60%', borderRadius: 6 }} />
            <div className="skel" style={{ height: 16, width: '40%', borderRadius: 4 }} />
            {[1, 2, 3, 4].map((i) => <div key={i} className="skel" style={{ height: 14, borderRadius: 4 }} />)}
          </div>
        ) : module ? (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 14 }}>
              <Badge tone="outline" size="xs" icon={module.content_type === 'video' ? 'play' : 'book'}>{module.content_type}</Badge>
              <Badge tone="neutral" size="xs">{module.estimated_minutes}m</Badge>
              <Badge tone="outline" size="xs">{module.topic}</Badge>
            </div>
            <h1 className="serif" style={{ fontSize: 32, fontWeight: 400, margin: '0 0 20px', letterSpacing: '-0.02em', lineHeight: 1.2 }}>{module.title}</h1>

            {/* Video player */}
            {module.content_type === 'video' && module.video_url && (
              <div style={{ aspectRatio: '16/9', background: 'var(--paper-2)', borderRadius: 'var(--r-3)', overflow: 'hidden', marginBottom: 24, border: '1px solid var(--line-1)' }}>
                <video
                  src={module.video_url}
                  controls
                  style={{ width: '100%', height: '100%' }}
                  onTimeUpdate={(e) => {
                    const el = e.currentTarget
                    setProgress((el.currentTime / el.duration) * 100)
                    if (el.currentTime >= el.duration * 0.9) setShowQuizPrompt(true)
                  }}
                />
              </div>
            )}

            {/* Body */}
            <div className="t-md fg-1" style={{ lineHeight: 1.7, maxWidth: 680 }}>
              <ReactMarkdown>{module.body}</ReactMarkdown>
            </div>

            {/* Image drop zone */}
            <div
              ref={dropRef}
              onDragOver={(e) => e.preventDefault()}
              onDrop={handleImageDrop}
              style={{
                marginTop: 32, border: '2px dashed var(--line-2)', borderRadius: 'var(--r-3)',
                padding: '28px 0', textAlign: 'center', cursor: 'pointer', transition: 'border-color var(--dur-fast)',
              }}
              onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--ink-2)')}
              onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--line-2)')}
            >
              {captionLoading ? (
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, color: 'var(--accent)' }}>
                  <Icon name="refresh" size={20} style={{ animation: 'spin 1s linear infinite' }} />
                  <span className="t-sm">Captioning image…</span>
                </div>
              ) : (
                <>
                  <Icon name="upload" size={18} style={{ color: 'var(--ink-3)', marginBottom: 6 }} />
                  <div className="t-sm fg-3">Drop an image to caption it and add to your doubt</div>
                </>
              )}
            </div>

            {/* Doubt prefill */}
            {doubtInput && (
              <div style={{ marginTop: 14 }}>
                <div className="t-xs fg-3" style={{ marginBottom: 4 }}>Pre-filled from image caption</div>
                <textarea
                  value={doubtInput}
                  onChange={(e) => setDoubtInput(e.target.value)}
                  style={{ width: '100%', background: 'var(--paper-2)', border: '1px solid var(--line-2)', borderRadius: 'var(--r-2)', padding: '10px 12px', fontSize: 13, color: 'var(--ink-0)', fontFamily: 'inherit', outline: 'none', resize: 'none', height: 80 }}
                />
                <Button size="sm" style={{ marginTop: 6 }} onClick={() => navigate('/doubts', { state: { prefill: doubtInput, topic: module.topic } })}>
                  Ask Doubt-Solver
                </Button>
              </div>
            )}

            <div style={{ marginTop: 24, paddingTop: 20, borderTop: '1px solid var(--line-1)' }}>
              <Button variant="secondary" icon="check" onClick={() => { setProgress(100); setShowQuizPrompt(true) }}>Mark as Complete</Button>
            </div>
          </>
        ) : null}
      </div>

      {/* Right panel */}
      <div style={{ borderLeft: '1px solid var(--line-1)', background: 'var(--paper-1)', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 0 }}>
        {/* Progress */}
        <div style={{ padding: '16px 16px 14px', borderBottom: '1px solid var(--line-1)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
            <span className="caps fg-2">Progress</span>
            <span className="t-xs fg-3 mono">{Math.round(progress)}%</span>
          </div>
          <div style={{ height: 4, background: 'var(--paper-3)', borderRadius: 'var(--r-pill)', overflow: 'hidden' }}>
            <div style={{ width: `${progress}%`, height: '100%', background: 'var(--ink-0)', borderRadius: 'var(--r-pill)', transition: 'width 0.5s ease' }} />
          </div>
        </div>

        {/* Table of contents */}
        <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--line-1)' }}>
          <div className="caps fg-2" style={{ marginBottom: 8 }}>Contents</div>
          {['Introduction', 'Core Concepts', 'Examples', 'Practice', 'Summary'].map((s) => (
            <button
              key={s}
              className="t-sm fg-1"
              style={{ display: 'block', width: '100%', textAlign: 'left', padding: '5px 8px', borderRadius: 'var(--r-1)', background: 'transparent', border: 0, cursor: 'pointer', fontFamily: 'inherit' }}
              onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--paper-2)')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
            >{s}</button>
          ))}
        </div>

        {/* Doubt CTA */}
        <div style={{ padding: 16 }}>
          <Card padding="md" accent>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
              <Icon name="sparkle" size={12} style={{ color: 'var(--accent)' }} />
              <span className="t-sm fg-0" style={{ fontWeight: 500 }}>Got a doubt?</span>
            </div>
            <p className="t-xs fg-2" style={{ marginBottom: 10, lineHeight: 1.5 }}>Ask the Doubt-Solver AI agent for instant, context-aware answers.</p>
            <Button size="sm" variant="secondary" full onClick={() => navigate('/doubts', { state: { topic: module?.topic } })}>
              Open Doubt Chat
            </Button>
          </Card>
        </div>
      </div>

      {/* Quiz prompt banner */}
      {showQuizPrompt && (
        <div style={{
          position: 'fixed', bottom: 24, left: '50%', transform: 'translateX(-50%)',
          zIndex: 50, background: 'var(--paper-0)', border: '1px solid var(--line-2)',
          borderRadius: 'var(--r-3)', padding: '16px 20px', boxShadow: 'var(--shadow-2)',
          display: 'flex', alignItems: 'center', gap: 16, maxWidth: 420, width: 'calc(100% - 48px)',
        }}>
          <div style={{ flex: 1 }}>
            <div className="t-md fg-0" style={{ fontWeight: 500, marginBottom: 2 }}>Module complete!</div>
            <div className="t-sm fg-2">Ready to test your knowledge with a quiz?</div>
          </div>
          <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
            <Button size="sm" variant="primary" onClick={handleStartQuiz}>Take Quiz</Button>
            <Button size="sm" variant="ghost" onClick={() => setShowQuizPrompt(false)}>Later</Button>
          </div>
        </div>
      )}
    </div>
  )
}
