import { useState, useRef, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import { contentAPI, quizAPI } from '@/lib/api'
import { runImageCaption } from '@/lib/hf'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Icon } from '@/components/ui/Icon'
import { Card } from '@/components/ui/Card'
import toast from 'react-hot-toast'

const SECTIONS = [
  { label: 'Introduction',  id: 'introduction'  },
  { label: 'Core Concepts', id: 'core-concepts'  },
  { label: 'Examples',      id: 'examples'       },
  { label: 'Practice',      id: 'practice'       },
  { label: 'Summary',       id: 'summary'        },
]

export default function ModulePlayerPage() {
  const { moduleId } = useParams<{ moduleId: string }>()
  const navigate = useNavigate()
  const [progress, setProgress] = useState(0)
  const [showQuizPrompt, setShowQuizPrompt] = useState(false)
  const [doubtInput, setDoubtInput] = useState('')
  const [captionLoading, setCaptionLoading] = useState(false)
  const [quizLoading, setQuizLoading] = useState(false)
  const dropRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const wasGenerating = useRef(false)

  const { data: module, isLoading } = useQuery({
    queryKey: ['content', 'module', moduleId],
    queryFn: () => contentAPI.get(moduleId!).then((r) => r.data),
    enabled: !!moduleId,
    staleTime: 0,
    refetchOnMount: true,
    // Poll every 3 s while content is still generating; stop once it arrives
    refetchInterval: (query) => {
      const body = (query.state.data as { body?: string } | undefined)?.body
      return !body || body.length < 400 ? 3000 : false
    },
  })

  // Notify the learner the moment content finishes generating
  useEffect(() => {
    if (!module) return
    const isGenerating = !module.body || module.body.length < 400
    if (wasGenerating.current && !isGenerating) {
      toast.success('Your content is ready!', { icon: '✨', duration: 4000 })
    }
    wasGenerating.current = isGenerating
  }, [module])

  const regenerateMutation = useMutation({
    mutationFn: () => contentAPI.regenerate(moduleId!),
    onSuccess: () => toast.success('Content regeneration started'),
    onError: () => toast.error('Could not regenerate content'),
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
    setQuizLoading(true)
    const tid = toast.loading('Creating your quiz…')
    try {
      const { data } = await quizAPI.generate(module.topic)
      toast.dismiss(tid)
      navigate(`/quiz/${data.quiz_id}`)
    } catch {
      toast.dismiss(tid)
      toast.error('Could not generate quiz — try again')
    } finally {
      setQuizLoading(false)
    }
  }

  const bodyIsShort = !module?.body || module.body.length < 400

  return (
    <div className="grid h-full grid-cols-1 overflow-hidden lg:grid-cols-[1fr_280px]">
      {/* Main content */}
      <div ref={contentRef} style={{ overflowY: 'auto', padding: '24px 32px' }}>
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
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 20 }}>
              <h1 className="serif" style={{ fontSize: 32, fontWeight: 400, margin: 0, letterSpacing: '-0.02em', lineHeight: 1.2, flex: 1 }}>{module.title}</h1>
              <Button
                size="sm"
                variant="ghost"
                icon="refresh"
                onClick={() => regenerateMutation.mutate()}
                disabled={regenerateMutation.isPending}
                style={{ flexShrink: 0, marginTop: 6 }}
              >
                {regenerateMutation.isPending ? 'Regenerating…' : 'Regenerate'}
              </Button>
            </div>

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
            {bodyIsShort ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxWidth: 680 }}>
                <div className="skel" style={{ height: 24, width: '45%', borderRadius: 4 }} />
                {[1, 2, 3].map((i) => <div key={i} className="skel" style={{ height: 14, borderRadius: 4 }} />)}
                <div className="skel" style={{ height: 24, width: '38%', borderRadius: 4, marginTop: 12 }} />
                {[1, 2, 3, 4].map((i) => <div key={i} className="skel" style={{ height: 14, borderRadius: 4 }} />)}
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 16, padding: '10px 14px', background: 'color-mix(in srgb, var(--accent) 8%, var(--paper-1))', border: '1px solid color-mix(in srgb, var(--accent) 20%, transparent)', borderRadius: 'var(--r-2)' }}>
                  <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--accent)', animation: 'pulse 1.2s ease-in-out infinite', flexShrink: 0 }} />
                  <span className="t-sm" style={{ color: 'var(--accent)' }}>Preparing your content — this takes about 10 seconds</span>
                </div>
              </div>
            ) : (
              <div className="t-md fg-1" style={{ maxWidth: 680 }}>
                <ReactMarkdown
                  components={{
                    h2: ({ children }) => {
                      const id = String(children).toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '')
                      return <h2 id={id} style={{ fontSize: 20, fontWeight: 600, marginTop: 32, marginBottom: 12, color: 'var(--ink-0)' }}>{children}</h2>
                    },
                    h3: ({ children }) => <h3 style={{ fontSize: 16, fontWeight: 600, marginTop: 20, marginBottom: 8 }}>{children}</h3>,
                    p: ({ children }) => <p style={{ marginBottom: 14, lineHeight: 1.75 }}>{children}</p>,
                    code: ({ children, className }) => {
                      const isBlock = className?.includes('language-')
                      return isBlock
                        ? <pre style={{ background: 'var(--paper-2)', border: '1px solid var(--line-1)', borderRadius: 8, padding: '14px 16px', overflowX: 'auto', marginBottom: 16 }}><code style={{ fontSize: 13, fontFamily: 'var(--font-mono)' }}>{children}</code></pre>
                        : <code style={{ background: 'var(--paper-2)', padding: '2px 6px', borderRadius: 4, fontSize: 13, fontFamily: 'var(--font-mono)' }}>{children}</code>
                    },
                    ul: ({ children }) => <ul style={{ paddingLeft: 20, marginBottom: 14, lineHeight: 1.75 }}>{children}</ul>,
                    ol: ({ children }) => <ol style={{ paddingLeft: 20, marginBottom: 14, lineHeight: 1.75 }}>{children}</ol>,
                    li: ({ children }) => <li style={{ marginBottom: 4 }}>{children}</li>,
                    strong: ({ children }) => <strong style={{ fontWeight: 600, color: 'var(--ink-0)' }}>{children}</strong>,
                  }}
                >
                  {module.body}
                </ReactMarkdown>
              </div>
            )}

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
                  Ask AI Tutor
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
      <div className="hidden lg:flex" style={{ borderLeft: '1px solid var(--line-1)', background: 'var(--paper-1)', overflowY: 'auto', flexDirection: 'column', gap: 0 }}>
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
          {SECTIONS.map((s) => (
            <button
              key={s.id}
              className="t-sm fg-1"
              style={{ display: 'block', width: '100%', textAlign: 'left', padding: '5px 8px', borderRadius: 'var(--r-1)', background: 'transparent', border: 0, cursor: 'pointer', fontFamily: 'inherit' }}
              onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--paper-2)')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
              onClick={() => {
                const el = document.getElementById(s.id)
                el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
              }}
            >{s.label}</button>
          ))}
        </div>

        {/* Doubt CTA */}
        <div style={{ padding: 16 }}>
          <Card padding="md" accent>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
              <Icon name="sparkle" size={12} style={{ color: 'var(--accent)' }} />
              <span className="t-sm fg-0" style={{ fontWeight: 500 }}>Got a doubt?</span>
            </div>
            <p className="t-xs fg-2" style={{ marginBottom: 10, lineHeight: 1.5 }}>Ask your AI tutor for instant, context-aware answers.</p>
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
            <Button size="sm" variant="primary" onClick={handleStartQuiz} loading={quizLoading}>Take Quiz</Button>
            <Button size="sm" variant="ghost" onClick={() => setShowQuizPrompt(false)}>Later</Button>
          </div>
        </div>
      )}
    </div>
  )
}
